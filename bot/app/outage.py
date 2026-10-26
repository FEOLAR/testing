"""Компенсация за сбой: если VPN недоступен у всех (все включённые ноды неисправны или не отвечают
из России) дольше OUTAGE_MIN_MINUTES, после восстановления бот добавляет OUTAGE_COMPENSATION_DAYS
всем, у кого подписка была активна во время сбоя, и присылает им уведомление.

Падение одной ноды сбоем не считается: клиенты уходят на другие. Начало сбоя хранится в таблице
outages, поэтому перезапуск бота посреди сбоя ничего не теряет. Вручную — /compensate в админке.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from sqlalchemy import select, text

from . import texts
from .config import settings
from .db import Session, User, utcnow

log = logging.getLogger(__name__)
_running: set[asyncio.Task] = set()


async def track(bot: Bot, enabled_nodes: int, healthy_nodes: int) -> None:
    """Вызывается балансировщиком раз в минуту с принятыми состояниями нод."""
    if settings.outage_compensation_days <= 0 or enabled_nodes == 0:
        return
    down = healthy_nodes == 0
    async with Session() as s:
        row = (await s.execute(text("SELECT id, started_at FROM outages WHERE ended_at IS NULL "
                                    "ORDER BY id DESC LIMIT 1"))).first()
        if down and not row:
            await s.execute(text("INSERT INTO outages (started_at) VALUES (:t)"), {"t": utcnow()})
            await s.commit()
            log.warning("outage: all nodes down")
            return
        if down or not row:
            return
        ended = utcnow()
        await s.execute(text("UPDATE outages SET ended_at = :t WHERE id = :id"), {"t": ended, "id": row.id})
        await s.commit()
    minutes = (ended - row.started_at).total_seconds() / 60
    log.warning("outage: recovered after %.0f min", minutes)
    if minutes >= settings.outage_min_minutes:
        task = asyncio.create_task(compensate_outage(bot, row.id, row.started_at, minutes))
        _running.add(task)
        task.add_done_callback(_running.discard)


async def compensate_outage(bot: Bot, outage_id: int, since: datetime, minutes: float) -> None:
    from .services import notify_admins
    async with Session() as s:  # защита от двойного начисления
        claimed = (await s.execute(text("UPDATE outages SET compensated = TRUE WHERE id = :id AND NOT compensated "
                                        "RETURNING id"), {"id": outage_id})).first()
        await s.commit()
    if not claimed:
        return
    days = settings.outage_compensation_days
    ok, failed = await compensate_all(bot, days, since)
    await notify_admins(bot, f"🎁 Сбой длился {minutes:.0f} мин — начислил +{days} дн. {ok} подпискам"
                             + (f", ошибок: {failed}" if failed else "") + ".")


async def compensate_all(bot: Bot, days: int, active_since: datetime | None = None) -> tuple[int, int]:
    """+days всем, у кого подписка активна сейчас (или была активна после active_since)."""
    from .services import grant_days, safe_send
    edge = active_since or utcnow()
    async with Session() as s:
        ids = (await s.scalars(select(User.tg_id).where(User.expire_at > edge))).all()
    ok = failed = 0
    for tg_id in ids:
        try:
            await grant_days(tg_id, days)
            ok += 1
        except Exception:
            log.exception("compensation failed for %s", tg_id)
            failed += 1
            continue
        await safe_send(bot, tg_id, texts.outage_compensated(days))
        await asyncio.sleep(0.05)
    return ok, failed
