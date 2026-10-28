from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from sqlalchemy import func, select, update

from .config import settings
from .db import Payment, Session, User, utcnow
from .remnawave import panel, parse_dt, short_uuid_from_url
from . import promo as promos, texts
from .emoji import e

log = logging.getLogger(__name__)


async def get_or_create_user(tg_id: int, username: str | None, first_name: str | None,
                             referrer_id: int | None = None, source: str | None = None) -> tuple[User, bool]:
    async with Session() as s:
        user = await s.get(User, tg_id)
        if user:
            changed = False
            if user.username != username or user.first_name != first_name:
                user.username, user.first_name = username, first_name
                changed = True
            if user.is_blocked:
                user.is_blocked, user.blocked_at = False, None
                changed = True
            if changed:
                await s.commit()
            return user, False
        if referrer_id == tg_id or (referrer_id and not await s.get(User, referrer_id)):
            referrer_id = None
        if not source and referrer_id:
            source = "ref"
        user = User(tg_id=tg_id, username=username, first_name=first_name, referrer_id=referrer_id,
                    source=source)
        s.add(user)
        await s.commit()
        return user, True


async def grant_days(tg_id: int, days: int, plan=None) -> User:
    """Добавить дни в панели и обновить кэш в БД.
    plan — оплаченный тариф: семейный ставит лимит FAMILY_DEVICE_LIMIT, обычный после семейного
    возвращает DEVICE_LIMIT. Без plan (пробник, бонусы, /give) лимит не меняется."""
    async with Session() as s:
        user = await s.get(User, tg_id)
        set_limit = None
        if plan is not None and plan.code != "test" and (plan.family or user.family):
            set_limit = settings.plan_devices(plan)
        pu = await panel.add_days(user.panel_username, tg_id, days,
                                  short_uuid=short_uuid_from_url(user.sub_url), set_limit=set_limit)
        if set_limit is not None:
            user.family = plan.family
        user.sub_url = pu.get("subscriptionUrl")
        user.expire_at = parse_dt(pu["expireAt"])
        # стадии, которые уже наступили к моменту выдачи (например, /give 1), не присылаем
        stage = texts.reminder_stage(user.expire_at - utcnow())
        user.notice = "" if stage == "exp" else stage
        await s.commit()
        return user


async def process_payment(bot: Bot, payment_id: int) -> bool:
    """Идемпотентно выдаёт подписку за оплату. True — если выдали сейчас."""
    async with Session() as s:
        res = await s.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status.in_(("pending", "grant_error")))
            .values(status="processing")
            .returning(Payment.id)
        )
        await s.commit()
        if res.scalar_one_or_none() is None:
            return False  # уже обработан другим обработчиком
        payment = await s.get(Payment, payment_id)

    try:
        user = await grant_days(payment.tg_id, payment.days, plan=settings.plan(payment.plan_code))
    except Exception:
        log.exception("grant failed for payment %s", payment_id)
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment_id).values(status="grant_error"))
            await s.commit()
        await notify_admins(bot, f"{e('alert')} Оплата #{payment_id} получена, но панель не ответила. "
                                 f"Бот повторит выдачу автоматически.")
        return False

    async with Session() as s:
        await s.execute(update(Payment).where(Payment.id == payment_id)
                        .values(status="paid", paid_at=utcnow()))
        await s.commit()

    promo_note = ""
    if payment.promo_id:  # код использован — снимаем его с пользователя
        async with Session() as s:
            await s.execute(update(User).where(User.tg_id == payment.tg_id, User.promo_id == payment.promo_id)
                            .values(promo_id=None))
            await s.commit()
        p = await promos.get(payment.promo_id)
        promo_note = f", промокод {p.code} −{p.percent}%" if p else ""
    await safe_send(bot, payment.tg_id, texts.paid(user, payment.days))
    await reward_referrer(bot, payment.tg_id)
    await notify_admins(bot, f"{e('coin')} Оплата #{payment_id}: {payment.amount} от {payment.tg_id} ({payment.days} дн.{promo_note})")
    return True


async def reward_referrer(bot: Bot, tg_id: int) -> None:
    if settings.referral_bonus_days <= 0:
        return
    async with Session() as s:
        res = await s.execute(
            update(User)
            .where(User.tg_id == tg_id, User.referrer_id.is_not(None), User.referral_rewarded.is_(False))
            .values(referral_rewarded=True)
            .returning(User.referrer_id)
        )
        await s.commit()
        referrer_id = res.scalar_one_or_none()
    if not referrer_id:
        return
    try:
        await grant_days(referrer_id, settings.referral_bonus_days)
        await safe_send(bot, referrer_id, texts.referral_bonus(settings.referral_bonus_days))
    except Exception:
        log.exception("referral bonus failed for %s", referrer_id)


async def reward_referral_trial(bot: Bot, tg_id: int, notify_friend: bool = True) -> User | None:
    """Друг пришёл по реф-ссылке и взял бесплатные дни (пробник или бонус за канал):
    +REFERRAL_TRIAL_DAYS ему и пригласившему. Один раз на друга; пригласившему — не больше
    REFERRAL_TRIAL_LIMIT таких бонусов за 30 дней (защита от накрутки фейковыми аккаунтами).
    Возвращает обновлённого друга, если ему начислили дни."""
    days = settings.referral_trial_days
    if days <= 0:
        return None
    async with Session() as s:
        res = await s.execute(
            update(User).where(User.tg_id == tg_id, User.referrer_id.is_not(None),
                               User.ref_trial_rewarded.is_(False))
            .values(ref_trial_rewarded=True).returning(User.referrer_id))
        await s.commit()
        referrer_id = res.scalar_one_or_none()
    if not referrer_id:
        return None
    friend = None
    try:
        friend = await grant_days(tg_id, days)
        if notify_friend:
            await safe_send(bot, tg_id, texts.referral_trial_friend(days))
    except Exception:
        log.exception("referral trial: friend %s", tg_id)
    async with Session() as s:  # лимит считаем по друзьям, получившим бонус за последние 30 дней
        recent = await s.scalar(select(func.count()).select_from(User).where(
            User.referrer_id == referrer_id, User.ref_trial_rewarded.is_(True),
            User.created_at > utcnow() - timedelta(days=30))) or 0
    if settings.referral_trial_limit and recent > settings.referral_trial_limit:
        log.warning("referral trial: limit reached for referrer %s (%s)", referrer_id, recent)
        return friend
    try:
        await grant_days(referrer_id, days)
        await safe_send(bot, referrer_id, texts.referral_trial_inviter(days))
    except Exception:
        log.exception("referral trial: referrer %s", referrer_id)
    return friend


async def activate_trial(tg_id: int) -> User | None:
    async with Session() as s:
        res = await s.execute(
            update(User).where(User.tg_id == tg_id, User.trial_used.is_(False))
            .values(trial_used=True).returning(User.tg_id)
        )
        await s.commit()
        if res.scalar_one_or_none() is None:
            return None
    try:
        return await grant_days(tg_id, settings.trial_days)
    except Exception:
        async with Session() as s:  # вернуть возможность попробовать ещё раз
            await s.execute(update(User).where(User.tg_id == tg_id).values(trial_used=False))
            await s.commit()
        raise


async def refresh_from_panel(user: User) -> User:
    """Подтянуть актуальный срок и ссылку из панели (например, если админ менял вручную)."""
    pu = await panel.get_user(user.panel_username)
    async with Session() as s:
        db_user = await s.get(User, user.tg_id)
        if pu:
            new_expire = parse_dt(pu["expireAt"])
            if db_user.expire_at != new_expire:
                db_user.notice = ""
            db_user.sub_url, db_user.expire_at = pu.get("subscriptionUrl"), new_expire
        await s.commit()
    # реальный лимит устройств из панели (админ мог увеличить) — не хранится в БД, только для показа
    db_user.device_limit = (pu or {}).get("hwidDeviceLimit") or settings.device_limit
    return db_user


async def restore_deleted(apply: bool) -> dict:
    """Вернуть в панель пользователей с активной подпиской, которых удалили из панели,
    с прежними ссылками (shortUuid из сохранённой ссылки) и прежним сроком.
    apply=False — только посчитать. Истёкших не трогаем: при продлении бот сам создаст их
    с прежней ссылкой (grant_days)."""
    import asyncio
    res = {"checked": 0, "missing": 0, "restored": 0, "new_link": 0, "failed": [], "no_link": 0}
    async with Session() as s:
        users = (await s.scalars(select(User).where(User.expire_at > utcnow()))).all()
    for u in users:
        res["checked"] += 1
        try:
            if await panel.get_user(u.panel_username) is not None:
                continue
        except Exception:
            log.exception("restore: get_user %s", u.tg_id)
            res["failed"].append(u.tg_id)
            continue
        res["missing"] += 1
        su = short_uuid_from_url(u.sub_url)
        if not su:
            res["no_link"] += 1
        if not apply:
            continue
        try:
            pu = await panel.create_user(u.panel_username, u.tg_id, u.expire_at, short_uuid=su)
        except Exception:
            log.exception("restore: create %s", u.tg_id)
            res["failed"].append(u.tg_id)
            continue
        res["restored"] += 1
        new_url = pu.get("subscriptionUrl")
        if su and short_uuid_from_url(new_url) != su:
            res["new_link"] += 1
        async with Session() as s:
            db_user = await s.get(User, u.tg_id)
            db_user.sub_url = new_url or db_user.sub_url
            await s.commit()
        await asyncio.sleep(0.05)
    return res


class RevokeError(Exception):
    """Понятная пользователю причина, почему ссылку заменить нельзя."""


async def revoke_link(tg_id: int, by_admin: bool = False) -> User:
    """Выдать новую ссылку-подписку: старая ссылка и ключи перестают работать.
    Срок подписки и лимит устройств не меняются. Устройства сбрасываются (REVOKE_RESET_DEVICES),
    чтобы чужие устройства, подключённые по утёкшей ссылке, не занимали лимит."""
    async with Session() as s:
        user = await s.get(User, tg_id)
        if not user or not user.expire_at or user.expire_at <= utcnow():
            raise RevokeError("Заменить ссылку можно при активной подписке.")
        wait = settings.revoke_cooldown_min * 60
        if not by_admin and user.revoked_at and (utcnow() - user.revoked_at).total_seconds() < wait:
            left = max(1, int((wait - (utcnow() - user.revoked_at).total_seconds()) // 60) + 1)
            raise RevokeError(f"Ссылку недавно меняли. Повторить можно через {left} мин.")
        # отметку ставим до запроса в панель: двойное нажатие не выпустит две ссылки подряд
        prev, user.revoked_at = user.revoked_at, utcnow()
        await s.commit()
    try:
        pu = await panel.revoke_subscription(f"tg_{tg_id}")
        if not pu:
            raise RevokeError("Подписка не найдена. Напиши в поддержку.")
    except Exception:
        async with Session() as s:  # не получилось — не заставляем ждать перед повтором
            u = await s.get(User, tg_id)
            u.revoked_at = prev
            await s.commit()
        raise
    if settings.revoke_reset_devices:
        try:
            await panel.reset_devices(f"tg_{tg_id}")
        except Exception:
            log.exception("revoke: reset devices failed")
    async with Session() as s:
        user = await s.get(User, tg_id)
        user.sub_url = pu.get("subscriptionUrl") or (await panel.get_user(f"tg_{tg_id}") or {}).get("subscriptionUrl")
        await s.commit()
    log.info("subscription link revoked: tg_id=%s by_admin=%s", tg_id, by_admin)
    return user


def is_block_error(err: Exception) -> bool:
    """Только настоящая блокировка или удалённый аккаунт. «chat not found» / «can't initiate conversation» —
    человек просто ни разу не запускал этого бота (например, пользовался только старым GalacticVPN)."""
    msg = str(err).lower()
    return "blocked by the user" in msg or "user is deactivated" in msg


async def mark_blocked(tg_id: int, blocked: bool = True) -> None:
    """Отметить, что пользователь заблокировал (или разблокировал) бота. Дату блокировки не сдвигаем."""
    async with Session() as s:
        q = update(User).where(User.tg_id == tg_id)
        if blocked:
            q = q.where(User.is_blocked.is_(False)).values(is_blocked=True, blocked_at=utcnow())
        else:
            q = q.values(is_blocked=False, blocked_at=None)
        await s.execute(q)
        await s.commit()


async def blocked_users(old: bool = False) -> list[User]:
    """Кто заблокировал бота: сначала с активной подпиской, потом по дате блокировки (свежие сверху).
    old=True — старые отметки без даты (до v49: в т.ч. те, кто не запускал нового бота после переезда)."""
    now = utcnow()
    async with Session() as s:
        cond = User.blocked_at.is_(None) if old else User.blocked_at.is_not(None)
        users = list((await s.execute(select(User).where(User.is_blocked.is_(True), cond))).scalars())
    far = now.replace(year=1970)
    users.sort(key=lambda u: (bool(u.expire_at and u.expire_at > now), u.blocked_at or far), reverse=True)
    return users


async def reset_old_blocked() -> int:
    """Снять старые отметки без даты. Настоящие блокировки бот снова отметит сам (Telegram сообщает сразу
    или при следующей рассылке)."""
    async with Session() as s:
        res = await s.execute(update(User).where(User.is_blocked.is_(True), User.blocked_at.is_(None))
                              .values(is_blocked=False))
        await s.commit()
    return res.rowcount or 0


async def safe_send(bot: Bot, chat_id: int, text: str, **kw) -> bool:
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except Exception as e:  # пользователь заблокировал бота и т.п.
        log.info("send to %s failed: %s", chat_id, e)
        if is_block_error(e):
            await mark_blocked(chat_id)
        return False


async def notify_admins(bot: Bot, text: str) -> None:
    for admin in settings.admins:
        await safe_send(bot, admin, text)


async def pending_crypto_payments() -> list[Payment]:
    async with Session() as s:
        res = await s.execute(select(Payment).where(Payment.method == "crypto", Payment.status == "pending"))
        return list(res.scalars())


# ---------- общее для бота и мини-приложения ----------

async def create_crypto_payment(tg_id: int, plan, promo=None) -> Payment | None:
    """Создаёт счёт CryptoBot (со скидкой по промокоду, если он есть). None — если CryptoBot недоступен."""
    from .cryptopay import crypto
    rub, _ = promos.price(plan, promo)
    async with Session() as s:
        payment = Payment(tg_id=tg_id, plan_code=plan.code, days=plan.days,
                          method="crypto", amount=f"{rub} RUB", promo_id=promo.id if promos.applies(plan, promo) else None)
        s.add(payment)
        await s.commit()
        try:
            inv = await crypto.create_invoice(
                rub=rub,
                description=f"{settings.brand_name}: подписка {plan.title}",
                payload=str(payment.id),
            )
        except Exception:
            log.exception("cryptopay createInvoice failed")
            payment.status = "expired"
            await s.commit()
            return None
        payment.external_id = str(inv["invoice_id"])
        payment.pay_url = inv.get("bot_invoice_url") or inv.get("pay_url")
        await s.commit()
        return payment


# ---------- Platega (карты / СБП) ----------

CARD_INVOICE_TTL = timedelta(hours=2)   # неоплаченный счёт считаем истёкшим через 2 часа


async def create_card_payment(tg_id: int, plan, promo=None, bot_username: str = "") -> Payment | None:
    """Создаёт счёт Platega (со скидкой по промокоду). None — если Platega недоступна."""
    from .platega import platega
    rub, _ = promos.price(plan, promo)
    async with Session() as s:
        payment = Payment(tg_id=tg_id, plan_code=plan.code, days=plan.days, method="card",
                          amount=f"{rub} RUB", promo_id=promo.id if promos.applies(plan, promo) else None)
        s.add(payment)
        await s.commit()
        try:
            inv = await platega.create(
                rub=rub, description=f"{settings.brand_name}: подписка {plan.title}",
                payload=f"pay:{payment.id}", user_id=tg_id,
                return_url=f"https://t.me/{bot_username}" if bot_username else (settings.site_url("info") or "https://t.me"),
            )
        except Exception:
            log.exception("platega create failed")
            payment.status = "expired"
            await s.commit()
            return None
        payment.external_id, payment.pay_url = inv["id"], inv["url"]
        await s.commit()
        return payment


async def apply_card_status(bot: Bot, payment: Payment, status: str, amount: float | None = None) -> str:
    """Применяет статус Platega к нашему платежу. Возвращает paid | pending | expired."""
    from .platega import FAILED, PAID
    if status in PAID:
        if amount is not None and payment.amount.endswith("RUB") and float(amount) + 0.01 < int(payment.amount.split()[0]):
            await notify_admins(bot, f"{e('alert')} Platega: по счёту #{payment.id} пришло {amount} ₽ вместо "
                                     f"{payment.amount}. Подписка не выдана — проверь в кабинете Platega.")
            return "pending"
        await process_payment(bot, payment.id)
        return "paid"
    if status == "CHARGEBACKED":
        await notify_admins(bot, f"{e('alert')} Platega: возврат через банк (chargeback) по счёту #{payment.id}, "
                                 f"пользователь {payment.tg_id}, {payment.amount}.")
        return "paid" if payment.status == "paid" else "expired"
    if status in FAILED and payment.status == "pending":
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment.id, Payment.status == "pending")
                            .values(status="expired"))
            await s.commit()
        return "expired"
    return "pending"


async def check_card_payment(bot: Bot, payment: Payment) -> str:
    from .platega import platega
    if payment.status == "paid":
        return "paid"
    if payment.status in ("processing", "grant_error"):
        return "pending"
    if payment.status != "pending" or not payment.external_id:
        return "expired"
    status = await platega.status(payment.external_id)
    result = await apply_card_status(bot, payment, status)
    if result == "pending" and utcnow() - payment.created_at > CARD_INVOICE_TTL:
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment.id, Payment.status == "pending")
                            .values(status="expired"))
            await s.commit()
        return "expired"
    return result


async def pending_card_payments() -> list[Payment]:
    async with Session() as s:
        res = await s.execute(select(Payment).where(Payment.method == "card", Payment.status == "pending",
                                                    Payment.external_id.is_not(None)))
        return list(res.scalars())


async def check_payment(bot: Bot, payment: Payment) -> str:
    """Проверка любого счёта с внешней оплатой (крипта, карта)."""
    if payment.method == "card":
        return await check_card_payment(bot, payment)
    return await check_crypto_payment(bot, payment)


async def check_crypto_payment(bot: Bot, payment: Payment) -> str:
    """Проверяет счёт в CryptoBot. Возвращает paid | pending | expired."""
    from .cryptopay import crypto
    if payment.status == "paid":
        return "paid"
    if payment.status not in ("pending", "grant_error", "processing"):
        return "expired"
    if payment.status != "pending":
        return "pending"  # деньги пришли, выдача в процессе
    items = await crypto.get_invoices([payment.external_id])
    status = items[0]["status"] if items else None
    if status == "paid":
        await process_payment(bot, payment.id)
        return "paid"
    if status == "expired":
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment.id, Payment.status == "pending")
                            .values(status="expired"))
            await s.commit()
        return "expired"
    return "pending"


async def admin_give(bot: Bot, tg_id: int, days: int) -> User:
    async with Session() as s:
        if not await s.get(User, tg_id):
            s.add(User(tg_id=tg_id))
            await s.commit()
    user = await grant_days(tg_id, days)
    async with Session() as s:
        s.add(Payment(tg_id=tg_id, plan_code="admin", days=days, method="admin", amount="0",
                      status="paid", paid_at=utcnow()))
        await s.commit()
    await safe_send(bot, tg_id, f"{e('gift')} Тебе начислено {days} дн. подписки. "
                                f"Действует до {texts.fmt_date(user.expire_at)}.")
    return user


async def collect_stats() -> dict:
    from sqlalchemy import func
    now = utcnow()
    day_ago, month_ago = now - timedelta(days=1), now - timedelta(days=30)
    async with Session() as s:
        out = {
            "total": await s.scalar(select(func.count()).select_from(User)),
            "active": await s.scalar(select(func.count()).where(User.expire_at > now)),
            "new_day": await s.scalar(select(func.count()).where(User.created_at > day_ago)),
            "blocked": await s.scalar(select(func.count()).where(User.is_blocked.is_(True),
                                                                 User.blocked_at.is_not(None))),
            "blocked_old": await s.scalar(select(func.count()).where(User.is_blocked.is_(True),
                                                                     User.blocked_at.is_(None))),
        }
        for key, since in (("day", day_ago), ("month", month_ago)):
            rows = await s.execute(
                select(Payment.method, func.count(), func.array_agg(Payment.amount))
                .where(Payment.status == "paid", Payment.paid_at > since, Payment.method != "admin")
                .group_by(Payment.method)
            )
            out[key] = {m: {"count": c, "sum": sum(int(a.split()[0]) for a in amts)} for m, c, amts in rows}
    return out


def _money(amounts) -> tuple[int, int]:
    """Список строк "199 RUB" / "150 XTR" → (рубли, звёзды)."""
    rub = stars = 0
    for a in amounts or []:
        parts = (a or "").split()
        if not parts or not parts[0].isdigit():
            continue
        if len(parts) > 1 and parts[1] == "XTR":
            stars += int(parts[0])
        else:
            rub += int(parts[0])
    return rub, stars


async def source_stats(days: int | None = None) -> list[dict]:
    """По каждому источнику: пришло, взяли пробник, активны сейчас, купили (людей / оплат), выручка.
    days — учитывать только пользователей, пришедших за последние N дней."""
    from sqlalchemy import Integer, case, cast, func
    now = utcnow()
    num = case((Payment.amount.op("~")(r"^\d+( |$)"),
                cast(func.split_part(Payment.amount, " ", 1), Integer)), else_=0)
    is_star = func.split_part(Payment.amount, " ", 2) == "XTR"
    paid = (select(Payment.tg_id, func.count().label("n"),
                   func.sum(case((is_star, 0), else_=num)).label("rub"),
                   func.sum(case((is_star, num), else_=0)).label("stars"))
            .where(Payment.status == "paid", Payment.method != "admin")
            .group_by(Payment.tg_id).subquery())
    src = func.coalesce(User.source, "—")
    q = (select(src, func.count(),
                func.sum(case((User.trial_used.is_(True), 1), else_=0)),
                func.sum(case((User.expire_at > now, 1), else_=0)),
                func.count(paid.c.tg_id), func.coalesce(func.sum(paid.c.n), 0),
                func.coalesce(func.sum(paid.c.rub), 0), func.coalesce(func.sum(paid.c.stars), 0))
         .select_from(User).outerjoin(paid, paid.c.tg_id == User.tg_id).group_by(src))
    if days:
        q = q.where(User.created_at > now - timedelta(days=days))
    out = []
    async with Session() as s:
        for source, users, trial, active, payers, payments, rub, stars in await s.execute(q):
            out.append(dict(source=source, users=users, trial=int(trial or 0), active=int(active or 0),
                            payers=payers, payments=int(payments), rub=int(rub), stars=int(stars)))
    out.sort(key=lambda r: (r["rub"] + r["stars"], r["users"]), reverse=True)
    return out


async def promo_revenue() -> list[dict]:
    """Общие промокоды: сколько ввели (как источник), сколько оплат и выручка по скидке."""
    from sqlalchemy import func
    from .db import PromoCode
    async with Session() as s:
        rows = await s.execute(
            select(PromoCode.code, func.count(Payment.id), func.count(func.distinct(Payment.tg_id)),
                   func.array_agg(Payment.amount))
            .outerjoin(Payment, (Payment.promo_id == PromoCode.id) & (Payment.status == "paid"))
            .where(PromoCode.owner_tg_id.is_(None)).group_by(PromoCode.code))
        entered = dict((await s.execute(
            select(User.source, func.count()).where(User.source.like("promo:%")).group_by(User.source))).all())
    out = []
    for code, n, payers, amts in rows:
        rub, stars = _money([a for a in amts if a])
        out.append(dict(code=code, entered=entered.get(f"promo:{code}", 0), payments=n, payers=payers,
                        rub=rub, stars=stars))
    out.sort(key=lambda r: (r["rub"] + r["stars"], r["entered"]), reverse=True)
    return out


async def referrer_stats(limit: int = 15) -> list[dict]:
    """Топ пригласивших: сколько привели, сколько из них купили, сколько те заплатили."""
    from sqlalchemy import func
    async with Session() as s:
        rows = await s.execute(
            select(User.referrer_id, func.count(func.distinct(User.tg_id)),
                   func.count(func.distinct(Payment.tg_id)), func.array_agg(Payment.amount))
            .outerjoin(Payment, (Payment.tg_id == User.tg_id) & (Payment.status == "paid")
                       & (Payment.method != "admin"))
            .where(User.referrer_id.is_not(None)).group_by(User.referrer_id))
        data = []
        for ref_id, invited, payers, amts in rows:
            rub, stars = _money([a for a in amts if a])
            data.append(dict(tg_id=ref_id, invited=invited, payers=payers, rub=rub, stars=stars))
        data.sort(key=lambda r: (r["payers"], r["invited"]), reverse=True)
        data = data[:limit]
        names = {u.tg_id: u for u in (await s.execute(
            select(User).where(User.tg_id.in_([r["tg_id"] for r in data])))).scalars()} if data else {}
    for r in data:
        u = names.get(r["tg_id"])
        r["name"] = ("@" + u.username) if u and u.username else (u.first_name if u and u.first_name else str(r["tg_id"]))
    return data


async def traffic_top(days: int, limit: int) -> dict:
    """Кто сколько потратил трафика за последние days суток (по данным нод Remnawave)."""
    today = utcnow().date()
    start, end = (today - timedelta(days=days - 1)).isoformat(), today.isoformat()
    nodes = [n for n in await panel.nodes_usage(start, end) if n.get("total")]
    users = await panel.top_users([n["uuid"] for n in nodes], start, end, limit) if nodes else []
    ids = [int(u["username"][3:]) for u in users
           if u["username"].startswith("tg_") and u["username"][3:].isdigit()]
    async with Session() as s:
        known = {u.tg_id: u for u in (await s.execute(select(User).where(User.tg_id.in_(ids)))).scalars()} \
            if ids else {}
    for u in users:
        name = u["username"]
        tg_id = int(name[3:]) if name.startswith("tg_") and name[3:].isdigit() else None
        db_user = known.get(tg_id)
        u["tg_id"] = tg_id
        u["tg_username"] = db_user.username if db_user else None
        u["expire_at"] = db_user.expire_at if db_user else None
    return {"days": days, "start": start, "end": end, "nodes": nodes, "users": users,
            "total": sum(n["total"] for n in nodes)}


# ---------- Telegram Stars: запись оплаты и сверка ----------

async def record_stars_payment(bot: Bot, tg_id: int, payload: str, amount: int, charge_id: str) -> str:
    """Записывает Stars-оплату и выдаёт дни. Идемпотентно по charge_id.
    Возвращает: granted | duplicate | unknown_plan | grant_error."""
    from sqlalchemy.dialects.postgresql import insert
    code, promo_id = promos.parse_payload(payload)
    plan = settings.plan(code) if code else None
    values = dict(tg_id=tg_id, method="stars", amount=f"{amount} XTR", external_id=charge_id, promo_id=promo_id)
    if plan:
        values.update(plan_code=plan.code, days=plan.days)
    else:  # записываем, чтобы сверка не находила эту оплату снова каждые 10 минут
        values.update(plan_code=(code or "?")[:16], days=0, status="unknown_plan")
    async with Session() as s:
        if not await s.get(User, tg_id):
            s.add(User(tg_id=tg_id))
            await s.commit()
        res = await s.execute(
            insert(Payment)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["method", "external_id"])
            .returning(Payment.id)
        )
        await s.commit()
        payment_id = res.scalar_one_or_none()
    if not payment_id:
        return "duplicate"
    if plan is None:
        await notify_admins(bot, f"{e('alert')} Stars-оплата #{payment_id} с неизвестным тарифом: {payload}, user {tg_id}, "
                                 f"charge {charge_id}. Выдай дни вручную: /give {tg_id} <дни>")
        return "unknown_plan"
    return "granted" if await process_payment(bot, payment_id) else "grant_error"


async def reconcile_stars(bot: Bot, apply: bool = True, days: int = 30) -> list[dict]:
    """Сверяет входящие Stars-платежи бота (Telegram) с базой и выдаёт пропущенные.
    Нужна, если бот был выключен/перезапускался или апдейт об оплате потерялся."""
    since = utcnow() - timedelta(days=days)
    txs, offset = [], 0
    while offset < 2000:
        batch = (await bot.get_star_transactions(offset=offset, limit=100)).transactions
        txs += batch
        if len(batch) < 100:
            break
        offset += 100
    refunded = {t.id for t in txs if t.receiver is not None and getattr(t.receiver, "type", "") == "user"}
    out = []
    for t in txs:
        src = t.source
        if src is None or getattr(src, "type", "") != "user" or t.id in refunded:
            continue
        payload = getattr(src, "invoice_payload", None) or ""
        if not payload.startswith("vpn:") or t.date < since:
            continue
        async with Session() as s:
            exists = await s.scalar(select(Payment.id).where(Payment.method == "stars", Payment.external_id == t.id))
        if exists:
            continue
        item = {"tg_id": src.user.id, "username": src.user.username, "payload": payload,
                "amount": t.amount, "charge_id": t.id, "date": t.date}
        if apply:
            item["result"] = await record_stars_payment(bot, src.user.id, payload, t.amount, t.id)
            log.warning("stars reconcile: %s", item)
        out.append(item)
    return out
