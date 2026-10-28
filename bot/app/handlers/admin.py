from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, FSInputFile, InputSticker, Message
from sqlalchemy import func, select

from ..config import settings
from ..db import Payment, Session, User, utcnow
from ..remnawave import PanelError, panel
from ..texts import TZ as MSK
from ..services import (is_block_error, mark_blocked, blocked_users, RevokeError, admin_give, collect_stats, reconcile_stars, refresh_from_panel,
                        restore_deleted, revoke_link, safe_send, traffic_top)
from ..texts import fmt_date

router = Router()
router.message.filter(F.from_user.id.in_(settings.admins))
log = logging.getLogger(__name__)

HELP = (
    "🛠 <b>Админка</b>\n\n"
    "/stats — статистика\n"
    "/link метка — ссылка для рекламы (например /link techno), по ней видно, сколько пришло и купило\n"
    "/sources [дни] — откуда пришли люди: метки ссылок, промокоды, рефералка → пробники, покупки, выручка\n"
    "/promo_stats — промокоды: сколько ввели, сколько оплат и на какую сумму\n"
    "/refs — топ пригласивших друзей\n"
    "/blocked — кто заблокировал бота (ID, @ник, подписка); полный список — файлом\n"
    "/nodes — состояние нод и автораспределение по странам\n"
    "/wlcheck IP1 IP2 … — ссылка для клиента: проверить, какие IP проходят «белые списки» его оператора\n"
    "/top [дни] [кол-во] — кто больше всех тратит трафик (по умолчанию 30 дн., топ-20)\n"
    "/user &lt;tg_id&gt; — инфо о пользователе\n"
    "/give &lt;tg_id&gt; &lt;дни&gt; — выдать/продлить подписку\n"
    "/ban &lt;tg_id&gt; · /unban &lt;tg_id&gt; — отключить/включить VPN\n"
    "/revoke &lt;tg_id&gt; — заменить пользователю ссылку-подписку (старая перестанет работать)\n"
    "/compensate &lt;дни&gt; — добавить дни всем активным подпискам (например, после сбоя)\n"
    "/restore — найти пользователей с активной подпиской, удалённых из панели; /restore apply — вернуть их с прежними ссылками\n"
    "/refund &lt;id оплаты&gt; — вернуть звёзды и забрать оплаченные дни\n"
    "/promo — промокоды; /promo_add КОД СКИДКА% [ЛИМИТ]; /promo_on|/promo_off КОД; /promo_limit КОД N; /promo_uses КОД\n"
    "/broadcast — ответь этой командой на сообщение, чтобы разослать его всем\n"
    "/preview текст — текст с метками :zap: :logo: … бот пришлёт его с фирменными эмодзи; ответь на него /broadcast\n"
    "/broadcast_old — то же, но через старого бота (сообщить о переезде)\n"
    "/test_stars — тестовая оплата 1 ⭐ (проверка автовыдачи)\n"
    "/stars_check — найти оплаты Stars, которые бот пропустил (/stars_check apply — выдать их)\n"
    "/emoji &lt;пак&gt; — ID премиум-эмодзи из пака; ответом на сообщение — его текст в HTML с эмодзи\n"
    "/emoji_mypack — бот создаёт свой пак эмодзи (с логотипом) и проверяет, может ли его показывать\n"
    "/icons — фирменные иконки бота (пак загружается сам при запуске)"
)


@router.message(Command("admin"))
async def admin_help(message: Message):
    await message.answer(HELP)


@router.message(Command("stats"))
async def stats(message: Message):
    st = await collect_stats()

    def fmt(d: dict) -> str:
        names = {"stars": "Stars", "crypto": "Крипта", "card": "Карта/СБП"}
        return "; ".join(f"{names.get(m, m)}: {v['count']} шт · {v['sum']} {'⭐' if m == 'stars' else '₽'}"
                         for m, v in d.items()) or "—"

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: {st['total']} (новых за сутки: {st['new_day']})\n"
        f"Активных подписок: {st['active']}\n"
        f"Заблокировали бота: {st['blocked']}\n\n"
        f"Оплаты за 24ч: {fmt(st['day'])}\n"
        f"Оплаты за 30д: {fmt(st['month'])}"
    )


def _money_text(rub: int, stars: int) -> str:
    parts = [f"{rub} ₽"] if rub or not stars else []
    if stars:
        parts.append(f"{stars} ⭐")
    return " + ".join(parts)


def _blocked_line(u, now) -> str:
    who = f"@{u.username}" if u.username else escape(u.first_name or "без имени")
    when = u.blocked_at.astimezone(MSK).strftime("%d.%m %H:%M") if u.blocked_at else "дата неизвестна"
    sub = (f"подписка до {u.expire_at.astimezone(MSK).strftime('%d.%m')}" if u.expire_at and u.expire_at > now
           else "без подписки")
    return f"{who} · <code>{u.tg_id}</code> · {when} · {sub}"


@router.message(Command("blocked"))
async def blocked(message: Message):
    from ..db import utcnow
    users = await blocked_users()
    if not users:
        return await message.answer("Никто не заблокировал бота 🎉")
    now = utcnow()
    active = sum(1 for u in users if u.expire_at and u.expire_at > now)
    head = (f"🚫 <b>Заблокировали бота: {len(users)}</b> (из них с активной подпиской: {active})\n"
            "Сначала — с подпиской, дальше свежие сверху. Время — МСК.\n\n")
    shown = users[:40]
    text = head + "\n".join(_blocked_line(u, now) for u in shown)
    if len(users) > len(shown):
        text += f"\n\n…и ещё {len(users) - len(shown)} — полный список в файле."
    await message.answer(text)
    if len(users) > len(shown):
        import re
        rows = ["tg_id;username;имя;заблокировал (МСК);подписка до;источник"]
        for u in users:
            rows.append(";".join([
                str(u.tg_id), ("@" + u.username) if u.username else "", re.sub(r"[;\n]", " ", u.first_name or ""),
                u.blocked_at.astimezone(MSK).strftime("%Y-%m-%d %H:%M") if u.blocked_at else "",
                u.expire_at.astimezone(MSK).strftime("%Y-%m-%d") if u.expire_at else "", u.source or ""]))
        await message.answer_document(BufferedInputFile("\n".join(rows).encode("utf-8-sig"), "blocked.csv"))


@router.message(Command("link"))
async def ad_link(message: Message, command: CommandObject, bot: Bot):
    from .user import source_tag
    tag = source_tag((command.args or "").strip())
    if not tag:
        return await message.answer("Формат: <code>/link метка</code> — латиница, цифры, _ и -, до 32 символов.\n"
                                    "Например <code>/link tech_chan1</code>. Для каждого канала — своя метка.")
    me = await bot.get_me()
    await message.answer(f"🔗 Ссылка для метки <b>{tag}</b>:\n<code>https://t.me/{me.username}?start=src_{tag}</code>\n\n"
                         "Засчитываются только новые пользователи. Результат — /sources")


@router.message(Command("sources"))
async def sources(message: Message, command: CommandObject):
    from ..services import source_stats
    arg = (command.args or "").strip()
    days = int(arg) if arg.isdigit() and int(arg) > 0 else None
    rows = await source_stats(days)
    if not rows:
        return await message.answer("Пока пусто.")
    lines = []
    for r in rows[:40]:
        name = "без метки" if r["source"] == "—" else r["source"]
        conv = f"{round(100 * r['payers'] / r['users'])}%" if r["users"] else "—"
        lines.append(f"<b>{escape(name)}</b>: пришло {r['users']} · пробник {r['trial']} · купили {r['payers']} ({conv})"
                     f" · оплат {r['payments']} · {_money_text(r['rub'], r['stars'])} · активны {r['active']}")
    period = f"за {days} дн." if days else "за всё время"
    await message.answer(f"📈 <b>Источники</b> ({period}, по дате прихода)\n\n" + "\n".join(lines) +
                         "\n\nМетки: ссылки /link, <i>promo:КОД</i> — ввёл промокод до первой покупки, <i>ref</i> — от друга.")


@router.message(Command("promo_stats"))
async def promo_stats(message: Message):
    from ..services import promo_revenue
    rows = await promo_revenue()
    if not rows:
        return await message.answer("Промокодов пока нет.")
    lines = [f"<code>{escape(r['code'])}</code>: ввели новые {r['entered']} · оплат {r['payments']} "
             f"({r['payers']} чел.) · {_money_text(r['rub'], r['stars'])}" for r in rows]
    await message.answer("🎟 <b>Промокоды: отдача</b>\n\n" + "\n".join(lines) +
                         "\n\n«Ввели новые» — ввели код до первой покупки (то есть пришли по рекламе с этим кодом).")


@router.message(Command("refs"))
async def refs(message: Message):
    from ..services import referrer_stats
    rows = await referrer_stats()
    if not rows:
        return await message.answer("По реф-ссылкам пока никто не пришёл.")
    lines = [f"{escape(r['name'])}: привёл {r['invited']} · купили {r['payers']} · {_money_text(r['rub'], r['stars'])}"
             for r in rows]
    await message.answer("👥 <b>Топ пригласивших</b>\n\n" + "\n".join(lines))


@router.message(Command("wlcheck"))
async def wlcheck(message: Message, command: CommandObject):
    import re
    ips = list(dict.fromkeys(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", command.args or "")))[:150]
    if not ips:
        return await message.answer("Формат: /wlcheck 1.2.3.4 5.6.7.8 … (до 150 адресов, через пробел или запятую)")
    if not settings.miniapp_url:
        return await message.answer("Не задан MINIAPP_URL — некуда вести клиента.")
    link = f"{settings.miniapp_url.rstrip('/')}/wlcheck/?ips={','.join(ips)}"
    await message.answer(
        f"🧪 Ссылка для клиента ({len(ips)} адр.) — перешли ему вместе с текстом ниже:\n\n"
        "Здравствуйте! Помогите, пожалуйста, подобрать сервер, который работает у вашего оператора. "
        "Откройте ссылку на Wi‑Fi, потом выключите Wi‑Fi и VPN, нажмите «Начать проверку», "
        "а после неё снова включите Wi‑Fi и нажмите «Отправить результат». Это займёт 2 минуты.\n\n"
        f"{escape(link)}\n\n"
        "Результат придёт сюда. На серверах должен быть открыт порт 443 (на новом сервере он открыт, если не включать ufw) — запускать тест не нужно.",
        disable_web_page_preview=True)


@router.message(Command("nodes"))
async def nodes(message: Message):
    from ..balancer import status_text
    try:
        text = await status_text()
    except PanelError as e:
        return await message.answer(f"Панель не ответила: {escape(str(e)[:300])}")
    await message.answer(text)


def fmt_bytes(b: float) -> str:
    gb = b / 1024**3
    return f"{gb / 1024:.2f} ТБ" if gb >= 1024 else f"{gb:.1f} ГБ"


@router.message(Command("top"))
async def top(message: Message, command: CommandObject):
    args = (command.args or "").split()
    if not all(a.isdigit() for a in args) or len(args) > 2:
        return await message.answer("Формат: /top [дни] [кол-во], например /top 7 30")
    days = min(max(int(args[0]), 1), 90) if args else 30
    limit = min(max(int(args[1]), 1), 50) if len(args) > 1 else 20
    try:
        t = await traffic_top(days, limit)
    except PanelError as e:
        if "-> 403" in str(e):
            return await message.answer("Панель не дала доступ к статистике трафика. В Remnawave → API-токены "
                                        "создай токен с правами на bandwidth-stats (или «*») и пропиши его "
                                        "в PANEL_TOKEN в .env бота.")
        raise
    if not t["nodes"]:
        return await message.answer(f"За {days} дн. трафика на нодах нет.")
    lines = [f"📶 <b>Трафик за {days} дн.</b> ({t['start']} — {t['end']}, UTC)\n", "<b>Ноды:</b>"]
    for n in t["nodes"]:
        per_day = n["total"] / days
        lines.append(f"• {escape(n['name'])} — {fmt_bytes(n['total'])} "
                     f"(≈{fmt_bytes(per_day)}/сут → ~{fmt_bytes(per_day * 30)} за 30 дн.)")
    lines.append(f"Всего: <b>{fmt_bytes(t['total'])}</b>\n")
    lines.append(f"<b>Топ-{len(t['users'])} пользователей:</b>")
    for i, u in enumerate(t["users"], 1):
        who = f"@{u['tg_username']} " if u["tg_username"] else ""
        who += f"<code>{u['tg_id']}</code>" if u["tg_id"] else escape(u["username"])
        share = u["total"] * 100 / t["total"] if t["total"] else 0
        until = f" · до {fmt_date(u['expire_at'])[:5]}" if u["expire_at"] else ""
        lines.append(f"{i}. {who} — {fmt_bytes(u['total'])} · {share:.1f}%{until}")
    top10 = sum(u["total"] for u in t["users"][:10])
    if t["total"] and len(t["users"]) >= 10:
        lines.append(f"\nТоп-10 = {top10 * 100 / t['total']:.0f}% всего трафика. Подробнее: /user &lt;id&gt;")
    await message.answer("\n".join(lines))


def _parse_id(command: CommandObject) -> int | None:
    arg = (command.args or "").split()
    return int(arg[0]) if arg and arg[0].isdigit() else None


@router.message(Command("user"))
async def user_info(message: Message, command: CommandObject):
    tg_id = _parse_id(command)
    async with Session() as s:
        user = await s.get(User, tg_id) if tg_id else None
        if not user:
            return await message.answer("Не найден. Формат: /user 123456789")
        pays = (await s.execute(select(Payment).where(Payment.tg_id == tg_id, Payment.status == "paid")
                                .order_by(Payment.id.desc()).limit(5))).scalars().all()
    try:
        user = await refresh_from_panel(user)
    except Exception:
        pass
    pay_lines = "\n".join(f"#{p.id} {p.method} {p.amount} {p.days}д {fmt_date(p.paid_at)}" for p in pays) or "—"
    await message.answer(
        f"👤 <code>{user.tg_id}</code> @{user.username or '—'} {user.first_name or ''}\n"
        f"Подписка до: {fmt_date(user.expire_at) if user.expire_at else '—'}\n"
        f"Триал: {'да' if user.trial_used else 'нет'} · реферер: {user.referrer_id or '—'}\n"
        f"Ссылка: <code>{user.sub_url or '—'}</code>\n\nПоследние оплаты:\n{pay_lines}"
    )


@router.message(Command("give"))
async def give(message: Message, command: CommandObject):
    args = (command.args or "").split()
    if len(args) != 2 or not all(a.isdigit() for a in args):
        return await message.answer("Формат: /give 123456789 30")
    tg_id, days = int(args[0]), int(args[1])
    user = await admin_give(message.bot, tg_id, days)
    await message.answer(f"✅ Выдано {days} дн. Подписка до {fmt_date(user.expire_at)}")


@router.message(Command("ban", "unban"))
async def ban(message: Message, command: CommandObject):
    tg_id = _parse_id(command)
    if not tg_id:
        return await message.answer("Формат: /ban 123456789")
    enable = command.command == "unban"
    await panel.set_enabled(f"tg_{tg_id}", enable)
    await message.answer("✅ Включён" if enable else "⛔ Отключён")


@router.message(Command("compensate"))
async def compensate_cmd(message: Message, command: CommandObject):
    from ..outage import compensate_all
    args = (command.args or "").split()
    if not args or not args[0].isdigit() or not 1 <= int(args[0]) <= 30:
        return await message.answer("Формат: /compensate 2 — покажет, скольким подпискам добавится 2 дня")
    days = int(args[0])
    async with Session() as s:
        count = await s.scalar(select(func.count()).select_from(User).where(User.expire_at > utcnow())) or 0
    if len(args) < 2 or args[1].lower() != "yes":
        return await message.answer(f"Добавлю +{days} дн. {count} активным подпискам и пришлю им сообщение "
                                    f"«Извини за перебои».\nПодтверди: <code>/compensate {days} yes</code>")
    note = await message.answer(f"⏳ Начисляю +{days} дн. {count} подпискам…")
    ok, failed = await compensate_all(message.bot, days)
    await note.edit_text(f"✅ Начислено +{days} дн.: {ok}" + (f", ошибок: {failed}" if failed else ""))


@router.message(Command("restore"))
async def restore_cmd(message: Message, command: CommandObject):
    apply = (command.args or "").strip().lower() == "apply"
    note = await message.answer("⏳ Проверяю пользователей в панели…")
    r = await restore_deleted(apply)
    lines = [f"Активных подписок в боте: {r['checked']}",
             f"Нет в панели: {r['missing']}" + (f" (у {r['no_link']} нет сохранённой ссылки — получат новую)" if r['no_link'] else "")]
    if apply:
        lines.append(f"✅ Возвращено: {r['restored']}")
        if r["new_link"]:
            lines.append(f"⚠️ С новой ссылкой (прежнюю панель не приняла): {r['new_link']}")
    elif r["missing"]:
        lines.append("\nЧтобы вернуть их с прежними ссылками и сроком: /restore apply")
    if r["failed"]:
        lines.append(f"❌ Ошибки: {len(r['failed'])} — " + ", ".join(map(str, r["failed"][:20])))
    await note.edit_text("\n".join(lines))


@router.message(Command("revoke"))
async def revoke_cmd(message: Message, command: CommandObject):
    tg_id = _parse_id(command)
    if not tg_id:
        return await message.answer("Формат: /revoke 123456789")
    try:
        user = await revoke_link(tg_id, by_admin=True)
    except RevokeError as err:
        return await message.answer(f"⚠️ {err}")
    await message.answer(f"✅ Ссылка заменена. Новая:\n<code>{user.sub_url}</code>\n"
                         "Пользователю нужно удалить старую подписку в Happ и добавить новую.")


@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject):
    pid = _parse_id(command)
    async with Session() as s:
        p = await s.get(Payment, pid) if pid else None
        if not p or p.method != "stars" or p.status != "paid":
            return await message.answer("Нужен id оплаченного Stars-платежа (см. /user).")
        try:
            await message.bot.refund_star_payment(user_id=p.tg_id, telegram_payment_charge_id=p.external_id)
        except Exception:
            if not settings.legacy_bot_token:
                raise
            # оплата могла пройти ещё в старом боте — вернуть звёзды может только он
            old = Bot(settings.legacy_bot_token)
            try:
                await old.refund_star_payment(user_id=p.tg_id, telegram_payment_charge_id=p.external_id)
            finally:
                await old.session.close()
        p.status = "refunded"
        await s.commit()
    try:  # забираем оплаченные дни обратно
        await panel.remove_days(f"tg_{p.tg_id}", p.days)
        async with Session() as s2:
            u = await s2.get(User, p.tg_id)
        if u:
            await refresh_from_panel(u)
        days_note = f"Срок подписки уменьшен на {p.days} дн."
    except Exception:
        log.exception("refund: remove days failed")
        days_note = "⚠️ Срок в панели уменьшить не удалось — сделай вручную."
    await message.answer(f"↩️ Звёзды по оплате #{pid} возвращены. {days_note}")


@router.message(Command("test_stars"))
async def test_stars(message: Message):
    """Счёт на 1 ⭐ (1 день) — проверить всю цепочку: оплата → запись → выдача дней → уведомление."""
    from aiogram.types import LabeledPrice
    from ..config import TEST_PLAN
    await message.answer_invoice(
        title="Тест оплаты", description="Проверка Telegram Stars: 1 ⭐ = 1 день подписки",
        payload=f"vpn:{TEST_PLAN.code}", currency="XTR",
        prices=[LabeledPrice(label="Тест", amount=TEST_PLAN.stars)])


@router.message(Command("stars_check"))
async def stars_check(message: Message, command: CommandObject):
    apply = (command.args or "").strip() == "apply"
    try:
        found = await reconcile_stars(message.bot, apply=apply, days=30)
    except Exception as e:
        return await message.answer(f"Не удалось получить транзакции Stars: {e}")
    if not found:
        return await message.answer("✅ Все оплаты Stars за 30 дней учтены в базе.")
    lines = [f"• {i['tg_id']} @{i['username'] or '—'} · {i['amount']}⭐ · {i['payload']} · {fmt_date(i['date'])}"
             + (f" → {i['result']}" if apply else "") for i in found]
    tail = "\n\nВыдано." if apply else "\n\nЧтобы выдать дни: /stars_check apply"
    await message.answer("🔎 Оплаты Stars без записи в базе:\n" + "\n".join(lines) + tail)


@router.message(Command("preview"))
async def preview(message: Message):
    """Текст для рассылки с фирменными эмодзи: /preview, дальше текст (можно в несколько строк, HTML-теги <b>, <i>, <a>).
    Метки :имя: заменяются на иконки пака, список имён — /icons."""
    from .. import emoji
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        names = " ".join(f":{n}:" for n, _ in emoji.ICONS)
        return await message.answer("Напиши <code>/preview</code> и текст. Метки иконок:\n" + escape(names))
    try:
        await message.answer(emoji.render(raw[1]), disable_web_page_preview=True)
    except Exception as err:
        return await message.answer(f"Не получилось отправить — проверь HTML-теги.\n<code>{escape(str(err))}</code>")
    await message.answer("👆 Так увидят пользователи. Чтобы разослать — ответь на сообщение выше командой /broadcast")


@router.message(Command("broadcast"))
async def broadcast(message: Message):
    src = message.reply_to_message
    if not src:
        return await message.answer("Ответь командой /broadcast на сообщение, которое нужно разослать.")
    async with Session() as s:
        ids = (await s.execute(select(User.tg_id).where(User.is_blocked.is_(False)))).scalars().all()
    await message.answer(f"📤 Рассылка на {len(ids)} пользователей запущена…")
    asyncio.create_task(_run_broadcast(message.bot, message.chat.id, src, ids))


async def _run_broadcast(bot: Bot, admin_chat: int, src: Message, ids: list[int]) -> None:
    ok = fail = 0
    for tg_id in ids:
        for _ in range(3):
            try:
                await src.copy_to(tg_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                fail += 1
                if is_block_error(e):
                    await mark_blocked(tg_id)
                break
        await asyncio.sleep(0.05)  # ~20 сообщений/сек — ниже лимита Telegram
    await safe_send(bot, admin_chat, f"✅ Рассылка завершена: доставлено {ok}, ошибок {fail}")


@router.message(Command("broadcast_old"))
async def broadcast_old(message: Message):
    """Рассылка через СТАРОГО бота (после переезда): пишет и тем, кто ещё не запускал нового."""
    if not settings.legacy_bot_token:
        return await message.answer("Не задан LEGACY_BOT_TOKEN — рассылать через старого бота нечем.")
    src = message.reply_to_message
    if not src or not (src.text or src.caption):
        return await message.answer("Ответь командой /broadcast_old на текстовое сообщение — его разошлёт старый бот "
                                    "с кнопкой «Открыть нового бота».")
    async with Session() as s:
        ids = (await s.execute(select(User.tg_id))).scalars().all()
    me = await message.bot.me()
    await message.answer(f"📤 Рассылка через старого бота на {len(ids)} пользователей запущена…")
    asyncio.create_task(_run_broadcast_old(message.bot, message.chat.id, src.html_text, me.username, ids))


async def _run_broadcast_old(bot: Bot, admin_chat: int, text: str, new_username: str, ids: list[int]) -> None:
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="➡️ Открыть нового бота", url=f"https://t.me/{new_username}")]])
    old = Bot(settings.legacy_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ok = fail = 0
    try:
        for tg_id in ids:
            for _ in range(3):
                try:
                    await old.send_message(tg_id, text, reply_markup=kb)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except Exception:
                    fail += 1  # заблокировал старого бота или удалил аккаунт
                    break
            await asyncio.sleep(0.05)
    finally:
        await old.session.close()
    await safe_send(bot, admin_chat, f"✅ Рассылка через старого бота завершена: доставлено {ok}, не доставлено {fail}")


@router.message(Command("emoji"))
async def emoji(message: Message, command: CommandObject, bot: Bot):
    """Помогает вставить премиум-эмодзи в тексты бота.

    /emoji <имя пака или ссылка t.me/addemoji/...> — список эмодзи пака с их ID и пробная отправка;
    /emoji ответом на сообщение — HTML этого сообщения с тегами <tg-emoji> (копировать в texts.py).
    """
    src = message.reply_to_message
    if src and (src.text or src.caption):
        html_text = src.html_text  # aiogram превращает custom_emoji в <tg-emoji emoji-id="...">
        ids = [e.custom_emoji_id for e in (src.entities or src.caption_entities or []) if e.type == "custom_emoji"]
        await message.answer(f"Премиум-эмодзи в сообщении: {len(ids)}\n\n<pre>{escape(html_text)}</pre>")
        if ids:
            await message.answer("👇 Так это сообщение отправит бот (если эмодзи обычные — боту они недоступны):")
            await message.answer(html_text)
        return
    name = (command.args or "").strip().rstrip("/").split("/")[-1]
    if not name:
        return await message.answer("Использование:\n/emoji &lt;имя пака или ссылка t.me/addemoji/...&gt;\n"
                                    "или ответь /emoji на сообщение с премиум-эмодзи")
    try:
        pack = await bot.get_sticker_set(name)
    except Exception as e:
        return await message.answer(f"Пак не найден: {escape(str(e))}")
    items = [(st.emoji or "⭐", st.custom_emoji_id) for st in pack.stickers if st.custom_emoji_id]
    if not items:
        return await message.answer("Это не пак эмодзи (нет custom_emoji_id).")
    # сами эмодзи с номерами (по 5 в строке) — выбирать по картинке; в тексте/копии видны только заменители
    cells = [f'<code>{i:>3}</code> <tg-emoji emoji-id="{cid}">{e}</tg-emoji>' for i, (e, cid) in enumerate(items, 1)]
    await message.answer(f"<b>{escape(pack.title)}</b> — {len(items)} шт.\n"
                         "Если ниже видны значки из пака (а не обычные эмодзи) — бот может их использовать. "
                         "Выбирай по номерам; ID — командой <code>/emoji_ids ИМЯ</code>.")
    for i in range(0, len(cells), 100):
        chunk = cells[i:i + 100]
        await message.answer("\n".join("   ".join(chunk[j:j + 5]) for j in range(0, len(chunk), 5)))


@router.message(Command("emoji_ids"))
async def emoji_ids(message: Message, command: CommandObject, bot: Bot):
    name = (command.args or "").strip().rstrip("/").split("/")[-1]
    try:
        pack = await bot.get_sticker_set(name)
    except Exception as e:
        return await message.answer(f"Пак не найден: {escape(str(e))}")
    lines = [f"{i}. {st.emoji} <code>{st.custom_emoji_id}</code>"
             for i, st in enumerate(pack.stickers, 1) if st.custom_emoji_id]
    for i in range(0, len(lines), 100):
        await message.answer("\n".join(lines[i:i + 100]))


@router.message(Command("emoji_mypack"))
async def emoji_mypack(message: Message, bot: Bot):
    """Создаёт пак эмодзи от имени бота (владелец пака — админ) и пробует отправить эмодзи из него."""
    from pathlib import Path
    me = await bot.me()
    name = f"whitehole_by_{me.username}"
    try:
        pack = await bot.get_sticker_set(name)
    except Exception:
        logo = Path(__file__).resolve().parent.parent / "web" / "emoji_logo.png"
        try:
            await bot.create_new_sticker_set(
                user_id=message.from_user.id, name=name, title=f"{settings.brand_name} emoji",
                stickers=[InputSticker(sticker=FSInputFile(logo), format="static", emoji_list=["🕳"])],
                sticker_type="custom_emoji")
        except Exception as e:
            return await message.answer(f"Не удалось создать пак: {escape(str(e))}")
        pack = await bot.get_sticker_set(name)
    cid = pack.stickers[0].custom_emoji_id
    await message.answer(f"Пак: https://t.me/addemoji/{name}\nID: <code>{cid}</code>\n\n"
                         f'Проверка: <tg-emoji emoji-id="{cid}">🕳</tg-emoji> ← если здесь логотип, а не 🕳, '
                         "бот может показывать эмодзи из своего пака.")


@router.message(Command("icons"))
async def icons(message: Message, bot: Bot):
    from .. import emoji
    if command_args := (message.text or "").split()[1:]:
        if command_args[0] == "reload":
            await emoji.setup(bot)
    loaded = len(emoji._ids)
    pack = settings.emoji_pack or "не задан"
    await message.answer(f"Иконок загружено: {loaded}/{len(emoji.ICONS)} · фирменный пак: {escape(pack)}\n"
                         "/icons reload — перезагрузить. Если иконка не из пака — задай её номер в .env, "
                         "например <code>EMOJI_MAP=bot=12,apple=7</code> (номера: <code>/emoji ИМЯ_ПАКА</code>).\n\n"
                         + emoji.report())


# ---------- промокоды ----------

def _promo_line(p: dict) -> str:
    limit = f"{p['used']}/{p['max_uses']}" if p["max_uses"] else f"{p['used']} (без лимита)"
    state = "🟢" if p["active"] and not (p["max_uses"] and p["used"] >= p["max_uses"]) else ("🟡" if p["active"] else "🔴")
    return f"{state} <code>{escape(p['code'])}</code> −{p['percent']}% · активаций {limit}"


@router.message(Command("promo"))
async def promo_list(message: Message):
    from .. import promo as promos
    items = await promos.list_all()
    body = "\n".join(_promo_line(p) for p in items) or "Промокодов пока нет."
    issued, used = await promos.personal_stats()
    if issued:
        body += (f"\n\nЛичные скидки −{settings.renew_promo_percent}% в напоминании о продлении: "
                 f"выдано {issued}, использовано {used}")
    await message.answer("🎟 <b>Промокоды</b>\n🟢 работает · 🟡 закончились активации · 🔴 выключен\n\n" + body +
                         "\n\nСоздать: <code>/promo_add КОД 20 100</code> (скидка 20%, 100 активаций; без лимита — 0)")


@router.message(Command("promo_add"))
async def promo_add(message: Message, command: CommandObject):
    from .. import promo as promos
    args = (command.args or "").split()
    try:
        code, percent = args[0], int(args[1].rstrip("%"))
        max_uses = int(args[2]) if len(args) > 2 else 0
    except (IndexError, ValueError):
        return await message.answer("Формат: <code>/promo_add КОД СКИДКА [ЛИМИТ]</code>, например <code>/promo_add START20 20 100</code>")
    promo, error = await promos.create(code, percent, max_uses)
    if error:
        return await message.answer(f"❌ {escape(error)}")
    await message.answer(f"✅ Промокод <code>{promo.code}</code> создан: −{promo.percent}%, "
                         f"{'лимит ' + str(promo.max_uses) if promo.max_uses else 'без лимита'}.")


async def _promo_by_arg(message: Message, command: CommandObject):
    from .. import promo as promos
    code = (command.args or "").split()[0] if command.args else ""
    promo = await promos.find(code) if code else None
    if not promo:
        await message.answer("Промокод не найден. Список — /promo")
    return promo


@router.message(Command("promo_on", "promo_off"))
async def promo_toggle(message: Message, command: CommandObject):
    from .. import promo as promos
    promo = await _promo_by_arg(message, command)
    if promo:
        on = command.command == "promo_on"
        await promos.update_promo(promo.id, active=on)
        await message.answer(f"{'🟢 Включён' if on else '🔴 Выключен'} промокод <code>{promo.code}</code>")


@router.message(Command("promo_limit"))
async def promo_limit(message: Message, command: CommandObject):
    from .. import promo as promos
    args = (command.args or "").split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("Формат: <code>/promo_limit КОД ЧИСЛО</code> (0 — без лимита)")
    promo = await _promo_by_arg(message, command)
    if promo:
        await promos.update_promo(promo.id, max_uses=int(args[1]))
        await message.answer(f"Лимит <code>{promo.code}</code>: {int(args[1]) or 'без лимита'}")


@router.message(Command("promo_uses"))
async def promo_uses(message: Message, command: CommandObject):
    from .. import promo as promos
    from datetime import datetime
    promo = await _promo_by_arg(message, command)
    if not promo:
        return
    uses = await promos.uses(promo.id)
    lines = []
    for u in uses[:100]:
        who = f"@{u['username']}" if u["username"] else escape(u["first_name"] or "")
        when = fmt_date(datetime.fromisoformat(u["paid_at"])) if u["paid_at"] else "—"
        lines.append(f"• {who} <code>{u['tg_id']}</code> — {u['days']} дн., {escape(u['amount'])}, {when}")
    await message.answer(f"🎟 <code>{promo.code}</code> использовали: {len(uses)}\n\n" + ("\n".join(lines) or "Пока никто."))
