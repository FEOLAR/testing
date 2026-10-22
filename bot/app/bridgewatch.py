"""Проверка нод «глазами России»: бот читает статистику HAProxy на мостах.

Зачем: панель видит ноду живой (связь панель ↔ нода идёт не из России), а клиенты из РФ к ней
подключиться не могут — так бывает, когда IP ноды блокируют. Мосты стоят в России и каждые 10 секунд
делают с каждой нодой настоящее TLS-рукопожатие, как клиент. Если нода не отвечает ни с одного моста —
значит из России она не работает.

Мосты отдают результат на http://МОСТ:8404/stats;csv (доступ только с сервера бота, настраивает
infra/bridge-nodes.sh). Список мостов — BRIDGES в .env.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from html import escape

import aiohttp

from .config import settings

log = logging.getLogger(__name__)

TIMEOUT = 6
FAIL_ALERT = 5          # столько минут подряд мост не отдаёт статистику — шлём предупреждение
BACKEND = "nodes443"    # смотрим проверки порта 443 (телефоны); 8443 блокируют вместе с ним

# мост -> {"ok": bool, "ts": float, "status": {ip: "UP"/"DOWN"/...}, "fails": int, "alerted": bool}
_bridges: dict[str, dict] = {}


def parse_csv(text: str) -> dict[str, str]:
    """{ip ноды: статус} из CSV статистики HAProxy."""
    text = text.lstrip("# ")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("pxname") == BACKEND and row.get("svname") not in (None, "", "BACKEND", "FRONTEND"):
            out[row["svname"]] = (row.get("status") or "").strip()
    return out


async def _fetch(session: aiohttp.ClientSession, bridge: str) -> dict[str, str] | None:
    url = f"http://{bridge}:{settings.bridge_stats_port}/stats;csv"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
            if r.status != 200:
                return None
            data = parse_csv(await r.text())
            return data or None
    except Exception:
        return None


async def poll(bot=None) -> None:
    """Раз в минуту (из balancer.balance_hosts): опрашивает все мосты."""
    if not settings.bridge_list:
        return
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*(_fetch(session, b) for b in settings.bridge_list))
    for bridge, data in zip(settings.bridge_list, results):
        st = _bridges.setdefault(bridge, {"ok": False, "ts": 0.0, "status": {}, "fails": 0, "alerted": False})
        if data is None:
            st["ok"] = False
            st["fails"] += 1
            if st["fails"] == FAIL_ALERT and not st["alerted"] and bot is not None:
                st["alerted"] = True
                await _notify(bot, f"🟠 Мост <code>{escape(bridge)}</code> не отдаёт проверку нод уже {FAIL_ALERT} мин.\n"
                                   "Либо мост лежит (тогда не работают хосты «Мост/Резерв»), либо на нём старая "
                                   "настройка — перезапусти на нём <code>bridge-nodes.sh</code> со списком нод.")
            continue
        if st["alerted"] and bot is not None:
            await _notify(bot, f"🟢 Мост <code>{escape(bridge)}</code> снова отдаёт проверку нод.")
        st.update(ok=True, ts=time.time(), status=data, fails=0, alerted=False)


async def _notify(bot, text: str) -> None:
    from .services import notify_admins
    await notify_admins(bot, text)


def _is_down(status: str) -> bool | None:
    s = status.upper()
    if s.startswith("DOWN"):     # "DOWN" и "DOWN 1/2" (поднимается, но ещё не поднялась)
        return True
    if s.startswith("UP") or s.startswith("NOLB"):   # "UP 1/3" — начала падать, но пока жива
        return False
    return None                  # MAINT, "no check" — не знаем


def blocked_from_russia(ip: str) -> bool:
    """Нода не отвечает ни с одного моста, который её проверяет и сейчас на связи."""
    verdicts = []
    for st in _bridges.values():
        if not st["ok"] or ip not in st["status"]:
            continue
        v = _is_down(st["status"][ip])
        if v is not None:
            verdicts.append(v)
    return bool(verdicts) and all(verdicts)


def status_lines() -> list[str]:
    """Строки для /nodes."""
    if not settings.bridge_list:
        return []
    lines = ["\n🌉 <b>Проверка из России (мосты)</b>"]
    for bridge in settings.bridge_list:
        st = _bridges.get(bridge)
        if not st:
            lines.append(f"⚪ <code>{escape(bridge)}</code> — ещё не проверял")
        elif not st["ok"]:
            lines.append(f"🟠 <code>{escape(bridge)}</code> — не отдаёт проверку ({st['fails']} мин)")
        else:
            down = [ip for ip, s in st["status"].items() if _is_down(s)]
            note = f"не видит: {', '.join(down)}" if down else f"все {len(st['status'])} нод отвечают"
            lines.append(f"{'🟡' if down else '🟢'} <code>{escape(bridge)}</code> — {escape(note)}")
    return lines
