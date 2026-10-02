from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy import select

from ..config import settings
from ..db import Payment, Session, User
from ..remnawave import PanelError, panel
from ..services import admin_give, collect_stats, reconcile_stars, refresh_from_panel, safe_send, traffic_top
from ..texts import fmt_date

router = Router()
router.message.filter(F.from_user.id.in_(settings.admins))
log = logging.getLogger(__name__)

HELP = (
    "🛠 <b>Админка</b>\n\n"
    "/stats — статистика\n"
    "/nodes — состояние нод и автораспределение по странам\n"
    "/top [дни] [кол-во] — кто больше всех тратит трафик (по умолчанию 30 дн., топ-20)\n"
    "/user &lt;tg_id&gt; — инфо о пользователе\n"
    "/give &lt;tg_id&gt; &lt;дни&gt; — выдать/продлить подписку\n"
    "/ban &lt;tg_id&gt; · /unban &lt;tg_id&gt; — отключить/включить VPN\n"
    "/refund &lt;id оплаты&gt; — вернуть звёзды (только Stars)\n"
    "/broadcast — ответь этой командой на сообщение, чтобы разослать его всем\n"
    "/stars_check — найти оплаты Stars, которые бот пропустил (/stars_check apply — выдать их)"
)


@router.message(Command("admin"))
async def admin_help(message: Message):
    await message.answer(HELP)


@router.message(Command("stats"))
async def stats(message: Message):
    st = await collect_stats()

    def fmt(d: dict) -> str:
        return "; ".join(f"{m}: {v['count']} шт · {v['sum']} {'⭐' if m == 'stars' else '₽'}"
                         for m, v in d.items()) or "—"

    await message.answer(
        f"📊 <b>Статистика</b>\n\n"
        f"Пользователей: {st['total']} (новых за сутки: {st['new_day']})\n"
        f"Активных подписок: {st['active']}\n"
        f"Заблокировали бота: {st['blocked']}\n\n"
        f"Оплаты за 24ч: {fmt(st['day'])}\n"
        f"Оплаты за 30д: {fmt(st['month'])}"
    )


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


@router.message(Command("refund"))
async def refund(message: Message, command: CommandObject):
    pid = _parse_id(command)
    async with Session() as s:
        p = await s.get(Payment, pid) if pid else None
        if not p or p.method != "stars" or p.status != "paid":
            return await message.answer("Нужен id оплаченного Stars-платежа (см. /user).")
        await message.bot.refund_star_payment(user_id=p.tg_id, telegram_payment_charge_id=p.external_id)
        p.status = "refunded"
        await s.commit()
    await message.answer(f"↩️ Звёзды по оплате #{pid} возвращены. "
                         f"Срок подписки при необходимости уменьши в панели вручную или /ban.")


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
            except Exception:
                fail += 1
                break
        await asyncio.sleep(0.05)  # ~20 сообщений/сек — ниже лимита Telegram
    await safe_send(bot, admin_chat, f"✅ Рассылка завершена: доставлено {ok}, ошибок {fail}")
