"""Сторож YouTube-выхода: раз в минуту проверяет, что сервер-выход для YouTube отвечает.

Весь YouTube клиентов идёт с нод через этот сервер (outbound YT_RU в Config Profile). Если он упадёт,
YouTube у клиентов перестанет открываться — поэтому админам сразу приходит 🔴, а при восстановлении 🟢.

Проверка — TCP-подключение к порту Shadowsocks (YT_EXITS, по умолчанию 217.149.26.98:8388).
На выходе firewall пускает к порту только ноды, поэтому туда нужно добавить и IP сервера с ботом:
    ufw allow from 146.0.76.110 to any port 8388 proto tcp
"""
from __future__ import annotations

import asyncio
import logging
import time
from html import escape

from aiogram import Bot

from .config import settings

log = logging.getLogger(__name__)

FAIL_CHECKS = 3      # столько неудачных проверок подряд (≈3 минуты) — и шлём тревогу
TIMEOUT = 5

_down: dict[str, float] = {}     # адрес -> время, когда признали упавшим
_fails: dict[str, int] = {}      # адрес -> неудач подряд
_last: dict[str, tuple[bool, float]] = {}   # адрес -> (жив, время проверки) для /nodes


async def probe(addr: str) -> bool:
    host, _, port = addr.rpartition(":")
    try:
        _r, w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), TIMEOUT)
        w.close()
        try:
            await w.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def check_exits(bot: Bot) -> None:
    from .services import notify_admins
    for addr in settings.yt_exit_list:
        ok = await probe(addr)
        _last[addr] = (ok, time.time())
        if ok:
            _fails[addr] = 0
            if addr in _down:
                mins = int((time.time() - _down.pop(addr)) / 60)
                await notify_admins(bot, f"🟢 YouTube-сервер <code>{escape(addr)}</code> снова отвечает "
                                         f"(не работал ~{mins} мин).")
            continue
        _fails[addr] = _fails.get(addr, 0) + 1
        log.warning("exitwatch: %s not responding (%s in a row)", addr, _fails[addr])
        if _fails[addr] == FAIL_CHECKS and addr not in _down:
            _down[addr] = time.time()
            await notify_admins(
                bot,
                f"🔴 <b>YouTube-сервер <code>{escape(addr)}</code> не отвечает</b> уже {FAIL_CHECKS} мин.\n"
                "У клиентов может не открываться YouTube.\n\n"
                "Что сделать:\n"
                "1. Зайди на него и проверь: <code>systemctl status xray</code> "
                "(перезапуск: <code>systemctl restart xray</code>).\n"
                "2. Если сервер недоступен совсем — в панели в Config Profile убери первое правило "
                "(<code>geosite:youtube … → YT_RU</code>) и сохрани: YouTube пойдёт напрямую с нод (с рекламой, но работает).",
            )


def status_lines() -> list[str]:
    """Строки для /nodes."""
    if not settings.yt_exit_list:
        return []
    lines = ["\n📺 <b>YouTube-сервер</b>"]
    for addr in settings.yt_exit_list:
        ok, ts = _last.get(addr, (None, 0))
        if ok is None:
            mark, note = "⚪", "ещё не проверял"
        elif ok:
            mark, note = "🟢", "отвечает"
        else:
            mark, note = "🔴", f"не отвечает ({_fails.get(addr, 0)} проверок подряд)"
        lines.append(f"{mark} <code>{escape(addr)}</code> — {note}")
    return lines
