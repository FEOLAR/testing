from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from sqlalchemy import select, update

from .config import settings
from .db import Payment, Session, User, utcnow
from .remnawave import panel, parse_dt
from . import texts

log = logging.getLogger(__name__)


async def get_or_create_user(tg_id: int, username: str | None, first_name: str | None,
                             referrer_id: int | None = None) -> tuple[User, bool]:
    async with Session() as s:
        user = await s.get(User, tg_id)
        if user:
            changed = False
            if user.username != username or user.first_name != first_name:
                user.username, user.first_name = username, first_name
                changed = True
            if user.is_blocked:
                user.is_blocked = False
                changed = True
            if changed:
                await s.commit()
            return user, False
        if referrer_id == tg_id or (referrer_id and not await s.get(User, referrer_id)):
            referrer_id = None
        user = User(tg_id=tg_id, username=username, first_name=first_name, referrer_id=referrer_id)
        s.add(user)
        await s.commit()
        return user, True


async def grant_days(tg_id: int, days: int) -> User:
    """Добавить дни в панели и обновить кэш в БД."""
    async with Session() as s:
        user = await s.get(User, tg_id)
        pu = await panel.add_days(user.panel_username, tg_id, days)
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
        user = await grant_days(payment.tg_id, payment.days)
    except Exception:
        log.exception("grant failed for payment %s", payment_id)
        async with Session() as s:
            await s.execute(update(Payment).where(Payment.id == payment_id).values(status="grant_error"))
            await s.commit()
        await notify_admins(bot, f"⚠️ Оплата #{payment_id} получена, но панель не ответила. "
                                 f"Бот повторит выдачу автоматически.")
        return False

    async with Session() as s:
        await s.execute(update(Payment).where(Payment.id == payment_id)
                        .values(status="paid", paid_at=utcnow()))
        await s.commit()

    await safe_send(bot, payment.tg_id, texts.paid(user, payment.days))
    await reward_referrer(bot, payment.tg_id)
    await notify_admins(bot, f"💰 Оплата #{payment_id}: {payment.amount} от {payment.tg_id} ({payment.days} дн.)")
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
        return db_user


async def safe_send(bot: Bot, chat_id: int, text: str, **kw) -> bool:
    try:
        await bot.send_message(chat_id, text, **kw)
        return True
    except Exception as e:  # пользователь заблокировал бота и т.п.
        log.info("send to %s failed: %s", chat_id, e)
        if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
            async with Session() as s:
                await s.execute(update(User).where(User.tg_id == chat_id).values(is_blocked=True))
                await s.commit()
        return False


async def notify_admins(bot: Bot, text: str) -> None:
    for admin in settings.admins:
        await safe_send(bot, admin, text)


async def pending_crypto_payments() -> list[Payment]:
    async with Session() as s:
        res = await s.execute(select(Payment).where(Payment.method == "crypto", Payment.status == "pending"))
        return list(res.scalars())


# ---------- общее для бота и мини-приложения ----------

async def create_crypto_payment(tg_id: int, plan) -> Payment | None:
    """Создаёт счёт CryptoBot. None — если CryptoBot недоступен."""
    from .cryptopay import crypto
    async with Session() as s:
        payment = Payment(tg_id=tg_id, plan_code=plan.code, days=plan.days,
                          method="crypto", amount=f"{plan.rub} RUB")
        s.add(payment)
        await s.commit()
        try:
            inv = await crypto.create_invoice(
                rub=plan.rub,
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
    await safe_send(bot, tg_id, f"🎁 Вам начислено {days} дн. подписки. "
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
            "blocked": await s.scalar(select(func.count()).where(User.is_blocked.is_(True))),
        }
        for key, since in (("day", day_ago), ("month", month_ago)):
            rows = await s.execute(
                select(Payment.method, func.count(), func.array_agg(Payment.amount))
                .where(Payment.status == "paid", Payment.paid_at > since, Payment.method != "admin")
                .group_by(Payment.method)
            )
            out[key] = {m: {"count": c, "sum": sum(int(a.split()[0]) for a in amts)} for m, c, amts in rows}
    return out


# ---------- Telegram Stars: запись оплаты и сверка ----------

async def record_stars_payment(bot: Bot, tg_id: int, payload: str, amount: int, charge_id: str) -> str:
    """Записывает Stars-оплату и выдаёт дни. Идемпотентно по charge_id.
    Возвращает: granted | duplicate | unknown_plan | grant_error."""
    from sqlalchemy.dialects.postgresql import insert
    plan = settings.plan(payload.split(":", 1)[1]) if payload.startswith("vpn:") else None
    if plan is None:
        await notify_admins(bot, f"⚠️ Stars-оплата с неизвестным тарифом: {payload}, user {tg_id}, "
                                 f"charge {charge_id}. Выдай дни вручную: /give {tg_id} <дни>")
        return "unknown_plan"
    async with Session() as s:
        if not await s.get(User, tg_id):
            s.add(User(tg_id=tg_id))
            await s.commit()
        res = await s.execute(
            insert(Payment)
            .values(tg_id=tg_id, plan_code=plan.code, days=plan.days, method="stars",
                    amount=f"{amount} XTR", external_id=charge_id)
            .on_conflict_do_nothing(index_elements=["method", "external_id"])
            .returning(Payment.id)
        )
        await s.commit()
        payment_id = res.scalar_one_or_none()
    if not payment_id:
        return "duplicate"
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
