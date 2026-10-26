"""Минимальный клиент Remnawave API.

Пользователь в панели всегда называется tg_<telegram_id>, поэтому все операции идут
по username — это работает одинаково в панели 2.x (uuid) и 3.x (числовой id).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from .config import settings

log = logging.getLogger(__name__)


class PanelError(Exception):
    pass


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def short_uuid_from_url(url: str | None) -> str | None:
    """shortUuid — последний кусок ссылки-подписки (…/api/sub/<shortUuid>)."""
    if not url:
        return None
    tail = url.split("?", 1)[0].split("#", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", tail) else None


class Remnawave:
    def __init__(self) -> None:
        self.http = httpx.AsyncClient(
            base_url=settings.panel_url.rstrip("/"),
            timeout=20,
            headers={
                "Authorization": f"Bearer {settings.panel_token}",
                # Панель принимает запросы только «через HTTPS-прокси».
                # При обращении по внутренней сети Docker передаём эти заголовки сами.
                "X-Forwarded-For": "127.0.0.1",
                "X-Forwarded-Proto": "https",
            },
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, url: str, **kw) -> dict | None:
        r = await self.http.request(method, url, **kw)
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise PanelError(f"{method} {url} -> {r.status_code}: {r.text[:500]}")
        return r.json().get("response")

    # --- users ---
    async def get_user(self, username: str) -> dict | None:
        return await self._req("GET", f"/api/users/by-username/{username}")

    async def create_user(self, username: str, tg_id: int, expire_at: datetime,
                          short_uuid: str | None = None, device_limit: int | None = None) -> dict:
        """short_uuid — вернуть пользователю прежнюю ссылку-подписку (если его удаляли из панели)."""
        body: dict = {
            "username": username,
            "expireAt": _iso(expire_at),
            "telegramId": tg_id,
            "hwidDeviceLimit": device_limit or settings.device_limit,
            "trafficLimitBytes": settings.traffic_limit_gb * 1024**3,
            "trafficLimitStrategy": "MONTH" if settings.traffic_limit_gb else "NO_RESET",
            "description": "created by bot",
        }
        if settings.squads:
            body["activeInternalSquads"] = settings.squads
        else:
            body["activeInternalSquads"] = await self.all_squad_uuids()
        if short_uuid:
            body["shortUuid"] = short_uuid
        try:
            user = await self._req("POST", "/api/users", json=body)
        except PanelError:
            if not short_uuid:
                raise
            # прежняя ссылка занята или не принята панелью — создаём с новой, чтобы не сорвать выдачу
            log.warning("create_user %s: shortUuid %s rejected, creating with a new link", username, short_uuid)
            body.pop("shortUuid")
            user = await self._req("POST", "/api/users", json=body)
        if not user:
            raise PanelError("create_user: empty response")
        return user

    async def update_user(self, username: str, **fields) -> dict:
        user = await self._req("PATCH", "/api/users", json={"username": username, **fields})
        if not user:
            raise PanelError("update_user: user not found")
        return user

    async def add_days(self, username: str, tg_id: int, days: int, short_uuid: str | None = None,
                       set_limit: int | None = None) -> dict:
        """Создаёт пользователя или продлевает от max(сейчас, текущий срок).
        short_uuid — если пользователя в панели нет (удалили), создаём его с прежней ссылкой."""
        now = datetime.now(timezone.utc)
        user = await self.get_user(username)
        if user is None:
            return await self.create_user(username, tg_id, now + timedelta(days=days), short_uuid=short_uuid,
                                          device_limit=set_limit)
        current = parse_dt(user["expireAt"])
        new_expire = max(now, current) + timedelta(days=days)
        # status не передаём: панель сама переводит EXPIRED -> ACTIVE при новом expireAt,
        # а вручную отключённого (DISABLED) пользователя не включаем.
        # Лимит устройств поднимаем до стандартного, но не урезаем, если админ выдал больше.
        fields = {"expireAt": _iso(new_expire)}
        current_limit = user.get("hwidDeviceLimit")
        if set_limit is not None:  # смена тарифа: семейный ↔ обычный
            if current_limit != set_limit:
                fields["hwidDeviceLimit"] = set_limit
        elif current_limit is None or current_limit < settings.device_limit:
            fields["hwidDeviceLimit"] = settings.device_limit
        return await self.update_user(username, **fields)

    async def remove_days(self, username: str, days: int) -> dict | None:
        """Уменьшает срок на days (не раньше текущего момента). None — пользователя нет."""
        user = await self.get_user(username)
        if user is None:
            return None
        now = datetime.now(timezone.utc)
        new_expire = max(now, parse_dt(user["expireAt"]) - timedelta(days=days))
        return await self.update_user(username, expireAt=_iso(new_expire))

    async def reset_devices(self, username: str) -> bool:
        user = await self.get_user(username)
        if not user:
            return False
        if "id" in user and isinstance(user["id"], int):  # 3.x
            body = {"userId": user["id"]}
        else:  # 2.x
            body = {"userUuid": user["uuid"]}
        await self._req("POST", "/api/hwid/devices/delete-all", json=body)
        return True

    @staticmethod
    def _user_key(user: dict) -> dict:
        if "id" in user and isinstance(user["id"], int):  # 3.x
            return {"userId": user["id"]}
        return {"userUuid": user["uuid"]}  # 2.x

    async def get_devices(self, username: str) -> list[dict]:
        user = await self.get_user(username)
        if not user:
            return []
        key = next(iter(self._user_key(user).values()))
        data = await self._req("GET", f"/api/hwid/devices/{key}") or {}
        return data.get("devices", [])

    async def delete_device(self, username: str, hwid: str) -> bool:
        user = await self.get_user(username)
        if not user:
            return False
        await self._req("POST", "/api/hwid/devices/delete", json={**self._user_key(user), "hwid": hwid})
        return True

    async def revoke_subscription(self, username: str) -> dict | None:
        """Новая ссылка-подписка: панель меняет shortUuid и ключи пользователя (VLESS UUID и пароли),
        поэтому старая ссылка и уже скачанные по ней конфиги перестают работать. None — пользователя нет."""
        user = await self.get_user(username)
        if not user:
            return None
        key = user["id"] if isinstance(user.get("id"), int) else user["uuid"]  # 3.x — id, 2.x — uuid
        return await self._req("POST", f"/api/users/{key}/actions/revoke", json={})

    async def set_enabled(self, username: str, enabled: bool) -> dict:
        return await self.update_user(username, status="ACTIVE" if enabled else "DISABLED")

    # --- ноды и хосты ---
    async def get_nodes(self) -> list[dict]:
        return await self._req("GET", "/api/nodes") or []

    async def get_hosts(self) -> list[dict]:
        return await self._req("GET", "/api/hosts") or []

    async def update_host(self, uuid: str, **fields) -> dict:
        host = await self._req("PATCH", "/api/hosts", json={"uuid": uuid, **fields})
        if not host:
            raise PanelError("update_host: host not found")
        return host

    # --- статистика трафика (даты YYYY-MM-DD, включительно, UTC) ---
    async def nodes_usage(self, start: str, end: str) -> list[dict]:
        """Трафик по нодам за период: [{uuid, name, countryCode, total}], total — байты."""
        data = await self._req("GET", "/api/bandwidth-stats/nodes",
                               params={"start": start, "end": end, "topNodesLimit": 100}) or {}
        return data.get("topNodes", [])

    async def top_users(self, node_uuids: list[str], start: str, end: str, limit: int) -> list[dict]:
        """Самые «тяжёлые» пользователи на нодах за период: [{username, total}], total — байты."""
        data = await self._req("POST", "/api/bandwidth-stats/nodes/users",
                               params={"start": start, "end": end, "topUsersLimit": limit},
                               json={"nodesUuids": node_uuids}) or {}
        return data.get("topUsers", [])

    # --- squads ---
    async def all_squad_uuids(self) -> list[str]:
        data = await self._req("GET", "/api/internal-squads") or {}
        return [s["uuid"] for s in data.get("internalSquads", [])]


panel = Remnawave()
