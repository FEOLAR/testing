from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from . import keyboards as kb, texts
from .config import settings
from .cryptopay import crypto
from .db import Payment, Session, User
from .services import notify_admins, pending_crypto_payments, process_payment, reconcile_stars, refresh_from_panel, safe_send

log = logging.getLogger(__name__)


async def poll_crypto(bot: Bot) -> None:
    """Проверяем неоплаченные счета CryptoBot."""
    if not settings.crypto_enabled:
        return
    payments = await pending_crypto_payments()
    by_invoice = {p.external_id: p for p in payments if p.external_id}
    ids = list(by_invoice)
    for i in range(0, len(ids), 100):
        try:
            items = await crypto.get_invoices(ids[i:i + 100])
        except Exception:
            log.exception("getInvoices failed")
            return
        for inv in items:
            p = by_invoice.get(str(inv["invoice_id"]))
            if not p:
                continue
            if inv["status"] == "paid":
                await process_payment(bot, p.id)
            elif inv["status"] == "expired":
                async with Session() as s:
                    await s.execute(update(Payment).where(Payment.id == p.id, Payment.status == "pending")
                                    .values(status="expired"))
                    await s.commit()


async def retry_failed_grants(bot: Bot) -> None:
    """Повторная выдача, если панель была недоступна в момент оплаты."""
    stuck_before = datetime.now(timezone.utc) - timedelta(minutes=10)
    async with Session() as s:
        # «processing» дольше 10 минут — процесс упал посреди выдачи
        await s.execute(update(Payment).where(Payment.status == "processing", Payment.updated_at < stuck_before)
                        .values(status="grant_error"))
        await s.commit()
        ids = (await s.execute(select(Payment.id).where(Payment.status == "grant_error"))).scalars().all()
    for pid in ids:
        await process_payment(bot, pid)


async def reconcile_stars_job(bot: Bot) -> None:
    """Страховка: оплаты Stars, которые бот не получил (был выключен, апдейт потерялся)."""
    try:
        found = await reconcile_stars(bot, apply=True, days=3)
    except Exception:
        log.exception("stars reconcile failed")
        return
    if found:
        await notify_admins(bot, "🔁 Сверка Stars: найдено и выдано пропущенных оплат — " + ", ".join(
            f"{i['tg_id']} ({i['amount']}⭐, {i.get('result')})" for i in found))


async def reminders(bot: Bot) -> None:
    """Напоминания за 24 ч, 12 ч, 2 ч и 30 мин до конца подписки и в момент окончания.
    Запускается раз в минуту; каждая стадия отправляется один раз на каждый срок подписки."""
    now = datetime.now(timezone.utc)
    async with Session() as s:
        users = (await s.execute(
            select(User).where(User.expire_at.is_not(None),
                               User.expire_at < now + texts.REMINDER_STAGES[0][1],
                               User.expire_at > now - timedelta(days=2),
                               User.notice != "exp",
                               User.is_blocked.is_(False))
        )).scalars().all()
    for user in users:
        rank = texts.REMINDER_RANK
        if rank[texts.reminder_stage(user.expire_at - now)] <= rank.get(user.notice or "", 0):
            continue  # эта стадия уже отправлена — в панель не ходим
        try:
            user = await refresh_from_panel(user)  # вдруг продлили вручную в панели
        except Exception:
            log.exception("refresh failed for %s", user.tg_id)
            continue
        kind = texts.reminder_stage(user.expire_at - now)
        if not kind or rank[kind] <= rank.get(user.notice or "", 0):
            continue
        await safe_send(bot, user.tg_id, texts.reminder(kind, user), reply_markup=kb.renew())
        async with Session() as s:
            await s.execute(update(User).where(User.tg_id == user.tg_id).values(notice=kind))
            await s.commit()


async def sync_from_panel(bot: Bot) -> None:
    """Раз в час сверяем сроки с панелью (если админ менял что-то вручную)."""
    import asyncio
    async with Session() as s:
        users = (await s.execute(select(User).where(User.expire_at.is_not(None)))).scalars().all()
    for user in users:
        try:
            await refresh_from_panel(user)
        except Exception:
            log.exception("sync failed for %s", user.tg_id)
        await asyncio.sleep(0.05)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone="UTC")
    opts = dict(max_instances=1, coalesce=True, args=[bot])
    sched.add_job(poll_crypto, "interval", seconds=20, **opts)
    sched.add_job(retry_failed_grants, "interval", minutes=2, **opts)
    sched.add_job(reminders, "interval", minutes=1, **opts)
    sched.add_job(sync_from_panel, "interval", hours=1, **opts)
    sched.add_job(reconcile_stars_job, "interval", minutes=10, **opts)
    return sched
