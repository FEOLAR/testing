"""Автораспределение пользователей по нодам и вывод упавших нод из подписки.

Как работает:
- В панели у хоста стоит тег AUTO (настраивается AUTO_HOST_TAG) и привязаны ноды
  (Хосты → хост → «Ноды»). Например, хост «🇫🇮 Финляндия» привязан к FI-1 и FI-2.
- Раз в минуту бот пишет в адрес такого хоста IP всех исправных привязанных нод через запятую.
  Remnawave при каждой выдаче подписки берёт из списка случайный адрес — так пользователи
  расходятся по нодам примерно поровну.
- Нода, которая не на связи с панелью (или отключена, или выбрала лимит трафика),
  убирается из адреса; когда снова в строю — возвращается. Админам приходит уведомление.
- Если исправных нод у хоста нет совсем, адрес не трогаем (пустой адрес хуже старого).
- Учёт загрузки (BALANCE_BY_LOAD=true): если на ноде заметно больше людей онлайн, чем ей положено
  по весу (NODE_WEIGHTS), её временно убирают из адреса — новые подключения и обновления подписки
  уходят на свободные ноды. Когда нагрузка выровняется, нода возвращается. Уведомлений нет — это штатно.
"""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot

from .config import settings
from .remnawave import panel

log = logging.getLogger(__name__)

# Сколько проверок подряд (раз в минуту) нода должна быть в одном состоянии,
# прежде чем меняем адреса: защищает от «мигания» при коротких сбоях.
STABLE_CHECKS = 2

_state: dict[str, bool] = {}       # uuid ноды -> принятое состояние (исправна или нет)
_streak: dict[str, int] = {}       # uuid ноды -> сколько проверок подряд состояние отличается от принятого
_overloaded: set[str] = set()      # uuid нод, временно убранных из адресов из-за перегрузки

# Перегрузка: онлайн ноды выше «положенного по весу» на OVERLOAD_RATIO и хотя бы на OVERLOAD_MIN человек.
# Возврат — когда превышение упало до RELEASE_RATIO (запас, чтобы нода не «мигала» каждую минуту).
OVERLOAD_RATIO = 1.25
RELEASE_RATIO = 1.05
OVERLOAD_MIN = 5


def node_problem(node: dict) -> str | None:
    """Причина, по которой ноду не надо давать клиентам, или None если исправна."""
    if node.get("isDisabled"):
        return "отключена в панели"
    if not node.get("isConnected"):
        return "нет связи с панелью"
    limit, used = node.get("trafficLimitBytes"), node.get("trafficUsedBytes")
    if node.get("isTrafficTrackingActive") and limit and used is not None and used >= limit:
        return "исчерпан лимит трафика ноды"
    return None


def _settle(nodes: list[dict]) -> list[tuple[dict, bool]]:
    """Обновляет принятые состояния нод с учётом STABLE_CHECKS. Возвращает [(нода, новое состояние)]
    для нод, чьё состояние только что сменилось."""
    changed = []
    for n in nodes:
        uuid, healthy = n["uuid"], node_problem(n) is None
        if uuid not in _state:  # первая проверка после запуска — принимаем как есть, без уведомлений
            _state[uuid] = healthy
            continue
        if healthy == _state[uuid]:
            _streak[uuid] = 0
            continue
        _streak[uuid] = _streak.get(uuid, 0) + 1
        if _streak[uuid] >= STABLE_CHECKS:
            _state[uuid], _streak[uuid] = healthy, 0
            changed.append((n, healthy))
    return changed


def weight(node: dict) -> float:
    return settings.weights.get(node.get("name", ""), 1.0)


def update_overload(nodes: list[dict]) -> None:
    """Пересчитывает набор перегруженных нод среди исправных (по всем сразу, а не по хосту:
    одна нода обслуживает все свои хосты)."""
    if not settings.balance_by_load:
        _overloaded.clear()
        return
    alive = [n for n in nodes if _state.get(n["uuid"], node_problem(n) is None)]
    total_w = sum(weight(n) for n in alive)
    online = sum(n.get("usersOnline") or 0 for n in alive)
    if len(alive) < 2 or not total_w:
        _overloaded.clear()
        return
    for n in alive:
        expected = online * weight(n) / total_w
        have = n.get("usersOnline") or 0
        if n["uuid"] in _overloaded:
            if have <= expected * RELEASE_RATIO or have - expected < OVERLOAD_MIN / 2:
                _overloaded.discard(n["uuid"])
                log.info("balancer: node %s back (online %s, fair %.0f)", n.get("name"), have, expected)
        elif have > expected * OVERLOAD_RATIO and have - expected >= OVERLOAD_MIN:
            _overloaded.add(n["uuid"])
            log.info("balancer: node %s overloaded (online %s, fair %.0f)", n.get("name"), have, expected)
    _overloaded.intersection_update(n["uuid"] for n in alive)


def load_status(node: dict) -> str:
    return "перегружена — новых не даю" if node["uuid"] in _overloaded else ""


def plan_addresses(hosts: list[dict], nodes: list[dict]) -> list[tuple[dict, str]]:
    """Для AUTO-хостов считает новый адрес. Возвращает [(хост, новый адрес)] только где он меняется."""
    by_uuid = {n["uuid"]: n for n in nodes}
    out = []
    for h in hosts:
        if settings.auto_host_tag not in (h.get("tags") or []):
            continue
        linked = [by_uuid[u] for u in h.get("nodes") or [] if u in by_uuid]
        alive = [n for n in linked if _state.get(n["uuid"], node_problem(n) is None)]
        if not alive:
            continue  # все ноды хоста лежат или не привязаны — оставляем как было
        free = [n for n in alive if n["uuid"] not in _overloaded]
        alive = [n["address"] for n in (free or alive)]  # все перегружены — даём все живые
        address = ",".join(dict.fromkeys(alive))  # без повторов, порядок как в привязке
        if address != h.get("address"):
            out.append((h, address))
    return out


async def balance_hosts(bot: Bot) -> None:
    from .services import notify_admins
    try:
        nodes, hosts = await panel.get_nodes(), await panel.get_hosts()
    except Exception:
        log.exception("balancer: panel unavailable")
        return
    for n, healthy in _settle(nodes):
        if healthy:
            await notify_admins(bot, f"🟢 Нода <b>{escape(n['name'])}</b> снова в строю — возвращаю её в подписку.")
        else:
            await notify_admins(bot, f"🔴 Нода <b>{escape(n['name'])}</b>: {node_problem(n)}. "
                                     f"Убираю её из AUTO-хостов (где есть другие живые ноды) — клиенты при обновлении подписки уйдут на них.")
    update_overload(nodes)
    for h, address in plan_addresses(hosts, nodes):
        try:
            await panel.update_host(h["uuid"], address=address)
            log.warning("balancer: host %s address %s -> %s", h["remark"], h["address"], address)
        except Exception:
            log.exception("balancer: update host %s failed", h.get("remark"))


async def status_text() -> str:
    """Текст для /nodes: состояние нод и адреса AUTO-хостов."""
    nodes, hosts = await panel.get_nodes(), await panel.get_hosts()
    lines = ["🖥 <b>Ноды</b>"]
    for n in sorted(nodes, key=lambda x: x.get("viewPosition", 0)):
        problem = node_problem(n)
        traffic = ""
        if n.get("trafficUsedBytes") is not None:
            traffic = f" · {n['trafficUsedBytes'] / 1024**4:.2f} ТБ"
            if n.get("trafficLimitBytes"):
                traffic += f" из {n['trafficLimitBytes'] / 1024**4:.1f}"
        w = weight(n)
        load = load_status(n)
        mark = "🔴" if problem else ("🟡" if load else "🟢")
        lines.append(f"{mark} {escape(n['name'])} <code>{escape(n['address'])}</code> · "
                     f"онлайн {n.get('usersOnline', 0)}{traffic}" + (f" · вес {w:g}" if w != 1 else "")
                     + (f" — {problem}" if problem else (f" — {load}" if load else "")))
    if settings.balance_by_load:
        lines.append("⚖️ Учёт загрузки включён: 🟡 — нода перегружена, новых клиентов временно шлю на другие")
    auto = [h for h in hosts if settings.auto_host_tag in (h.get("tags") or [])]
    lines.append(f"\n🔀 <b>Хосты с тегом {settings.auto_host_tag}</b>")
    if not auto:
        lines.append(f"нет — поставь хосту тег {settings.auto_host_tag} и привяжи к нему ноды")
    by_uuid = {n["uuid"]: n["name"] for n in nodes}
    for h in auto:
        linked = ", ".join(escape(by_uuid.get(u, "?")) for u in h.get("nodes") or []) or "ноды не привязаны!"
        lines.append(f"• {escape(h['remark'])}{' (выкл)' if h.get('isDisabled') else ''}: "
                     f"<code>{escape(h['address'])}:{h['port']}</code>\n   ноды: {linked}")
    return "\n".join(lines)
