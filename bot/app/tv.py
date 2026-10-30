"""Телевизор: вход по коду через Telegram (лаунчер WhiteHole для Android TV) и страница установки.

Как это работает:
1. Лаунчер на ТВ: POST /miniapp/tv/pair/start → 6-значный код, секретный токен устройства, ссылка на бота.
   Код и токен живут 10 минут в Redis (без Redis — в памяти процесса).
2. Человек сканирует QR (t.me/<бот>?start=tv_<код>) или вводит код в боте (/tv, «Подключить телевизор»)
   и нажимает «Подключить ТВ» → привязка сохраняется в таблице tv_devices (хранится только sha256 токена).
3. Лаунчер опрашивает GET /miniapp/tv/pair/status?token=… и получает ссылку-подписку, дальше —
   GET /miniapp/tv/me с заголовком X-TV-Token (срок, дни, устройства). Отвязать: POST /miniapp/tv/unpair.

Страница /miniapp/tv — «Скачать WhiteHole для ТВ» (APK из app/web/tv/whitehole-tv.apk или с GitHub).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from sqlalchemy import func, select, update

from .config import settings
from .db import Session, TvDevice, User, utcnow

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
TV_DIR = WEB_DIR / "tv"
PREFIX = "/miniapp/tv"
PAIR_TTL = 600            # код живёт 10 минут
RATE_LIMIT = 10           # не больше 10 новых кодов…
RATE_WINDOW = 600         # …за 10 минут с одного IP
CODE_RE = re.compile(r"^\d{6}$")
APK_GITHUB = "https://github.com/FEOLAR/testing/releases/download/tv-launcher-latest/whitehole-tv.apk"
HAPP_APK = "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(10 ** 6):06d}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def clean_name(raw) -> str:
    """Название телевизора от лаунчера (модель) — только печатные символы, до 48."""
    name = re.sub(r"[\x00-\x1f\x7f<>]", "", str(raw or "")).strip()
    return name[:48] or "Телевизор"


def parse_code(text: str | None) -> str | None:
    """«123 456», «tv_123456», «123456» → «123456»."""
    digits = re.sub(r"\D", "", text or "")
    return digits if CODE_RE.match(digits) else None


# ---------- хранилище кодов (Redis или память) ----------

class _MemoryKV:
    """Мини-замена Redis для тестов и запуска без REDIS_URL (один процесс)."""

    def __init__(self) -> None:
        self.data: dict[str, tuple[str, float]] = {}

    def _alive(self, key: str) -> str | None:
        item = self.data.get(key)
        if item is None:
            return None
        if item[1] < time.time():
            self.data.pop(key, None)
            return None
        return item[0]

    async def get(self, key: str) -> str | None:
        return self._alive(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False,
                  keepttl: bool = False) -> bool:
        current = self._alive(key)
        if nx and current is not None:
            return False
        if keepttl and current is not None:
            exp = self.data[key][1]
        else:
            exp = time.time() + (ex or 10 ** 9)
        self.data[key] = (value, exp)
        return True

    async def incr(self, key: str, ex: int) -> int:
        current = self._alive(key)
        if current is None:
            self.data[key] = ("1", time.time() + ex)
            return 1
        value = int(current) + 1
        self.data[key] = (str(value), self.data[key][1])
        return value

    async def ttl(self, key: str) -> int:
        if self._alive(key) is None:
            return -2
        return max(0, int(self.data[key][1] - time.time()))

    async def delete(self, *keys: str) -> None:
        for k in keys:
            self.data.pop(k, None)


class _RedisKV:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis
        self.r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self.r.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False,
                  keepttl: bool = False) -> bool:
        if keepttl:
            return bool(await self.r.set(key, value, keepttl=True, nx=nx))
        return bool(await self.r.set(key, value, ex=ex, nx=nx))

    async def incr(self, key: str, ex: int) -> int:
        value = await self.r.incr(key)
        if value == 1:
            await self.r.expire(key, ex)
        return int(value)

    async def ttl(self, key: str) -> int:
        return int(await self.r.ttl(key))

    async def delete(self, *keys: str) -> None:
        if keys:
            await self.r.delete(*keys)


_kv = None


def kv():
    global _kv
    if _kv is None:
        if settings.redis_url:
            try:
                _kv = _RedisKV(settings.redis_url)
            except Exception:
                log.exception("redis for tv pairing unavailable — using memory")
                _kv = _MemoryKV()
        else:
            _kv = _MemoryKV()
    return _kv


def _k_pair(code: str) -> str:
    return f"tv:pair:{code}"


def _k_tok(th: str) -> str:
    return f"tv:tok:{th}"


async def rate_ok(ip: str) -> bool:
    return await kv().incr(f"tv:rl:{ip}", RATE_WINDOW) <= RATE_LIMIT


async def start_pairing(name: str) -> dict:
    """Новый код + токен. Код уникален среди действующих (SET NX)."""
    token = new_token()
    th = token_hash(token)
    store = kv()
    for _ in range(20):
        code = new_code()
        data = {"th": th, "st": "pending", "name": clean_name(name), "created": int(time.time())}
        if await store.set(_k_pair(code), json.dumps(data), ex=PAIR_TTL, nx=True):
            await store.set(_k_tok(th), code, ex=PAIR_TTL)
            return {"code": code, "token": token, "expires_in": PAIR_TTL}
    raise RuntimeError("no free pairing code")


async def get_pairing(code: str) -> dict | None:
    raw = await kv().get(_k_pair(code))
    return json.loads(raw) if raw else None


class PairError(Exception):
    """Понятная человеку причина, почему не получилось подключить ТВ."""


async def active_devices(tg_id: int) -> list[TvDevice]:
    async with Session() as s:
        return list((await s.execute(
            select(TvDevice).where(TvDevice.tg_id == tg_id, TvDevice.revoked_at.is_(None))
            .order_by(TvDevice.id))).scalars().all())


async def count_devices(tg_id: int) -> int:
    async with Session() as s:
        return int(await s.scalar(select(func.count()).select_from(TvDevice).where(
            TvDevice.tg_id == tg_id, TvDevice.revoked_at.is_(None))) or 0)


async def confirm_pairing(code: str, tg_id: int, sub_url: str) -> TvDevice:
    """Пользователь нажал «Подключить ТВ». Первый подтвердивший выигрывает (повторно — ошибка)."""
    store = kv()
    pair = await get_pairing(code)
    if pair is None:
        raise PairError("Код не найден или устарел. Обнови код на телевизоре и попробуй снова.")
    if pair.get("st") != "pending":
        raise PairError("Этот код уже использован. Если телевизор не подключился — обнови код на нём.")
    if not await store.set(f"tv:lock:{code}", str(tg_id), ex=PAIR_TTL, nx=True):
        raise PairError("Этот код уже использован. Если телевизор не подключился — обнови код на нём.")
    try:
        async with Session() as s:
            device = TvDevice(tg_id=tg_id, token_hash=pair["th"], name=clean_name(pair.get("name")),
                              last_seen_at=utcnow())
            s.add(device)
            await s.commit()
            await s.refresh(device)
            # не больше TV_DEVICE_LIMIT телевизоров на человека — самые старые отвязываем
            rows = (await s.execute(select(TvDevice).where(TvDevice.tg_id == tg_id, TvDevice.revoked_at.is_(None))
                                    .order_by(TvDevice.id.desc()))).scalars().all()
            for old in rows[max(1, settings.tv_device_limit):]:
                old.revoked_at = utcnow()
            await s.commit()
    except Exception:
        await store.delete(f"tv:lock:{code}")
        raise
    pair.update(st="confirmed", tg=tg_id, sub=sub_url)
    await store.set(_k_pair(code), json.dumps(pair), keepttl=True)
    return device


async def device_by_token(token: str, touch: bool = True) -> TvDevice | None:
    if not token or len(token) > 200:
        return None
    th = token_hash(token)
    async with Session() as s:
        device = (await s.execute(select(TvDevice).where(TvDevice.token_hash == th,
                                                         TvDevice.revoked_at.is_(None)))).scalars().first()
        if device and touch:
            device.last_seen_at = utcnow()
            await s.commit()
        return device


async def revoke_device(device_id: int, tg_id: int | None = None) -> bool:
    """Отвязать телевизор. tg_id — только свой (для пользователя); None — любой (админ)."""
    cond = [TvDevice.id == device_id, TvDevice.revoked_at.is_(None)]
    if tg_id is not None:
        cond.append(TvDevice.tg_id == tg_id)
    async with Session() as s:
        res = await s.execute(update(TvDevice).where(*cond).values(revoked_at=utcnow()).returning(TvDevice.id))
        await s.commit()
        return res.scalar_one_or_none() is not None


async def all_devices(tg_id: int) -> list[TvDevice]:
    async with Session() as s:
        return list((await s.execute(select(TvDevice).where(TvDevice.tg_id == tg_id)
                                     .order_by(TvDevice.id.desc()).limit(30))).scalars().all())


# ---------- данные подписки для ТВ ----------

def _days_left(expire: datetime | None) -> int:
    if not expire:
        return 0
    return max(0, (expire - datetime.now(timezone.utc)).days)


async def subscription_info(tg_id: int) -> dict:
    """То же, что бот показывает в «Моя подписка»: ссылка, срок, лимит устройств (из панели)."""
    from .remnawave import panel, parse_dt
    async with Session() as s:
        user = await s.get(User, tg_id)
    if user is None:
        return {"status": "NONE", "sub_url": None, "expire_at": None, "days_left": 0, "family": False,
                "plan": "regular", "devices_used": 0, "device_limit": settings.device_limit, "devices": []}
    sub_url, expire, status = user.sub_url, user.expire_at, None
    limit = settings.family_device_limit if user.family else settings.device_limit
    used = None
    devices: list[dict] = []
    try:
        pu = await panel.get_user(user.panel_username)
        if pu:
            sub_url = pu.get("subscriptionUrl") or sub_url
            expire = parse_dt(pu["expireAt"])
            status = pu.get("status", "ACTIVE")
            if pu.get("hwidDeviceLimit") is not None:
                limit = pu["hwidDeviceLimit"]
            try:
                items = await panel.get_devices(user.panel_username)
                used = len(items)
                # v54: список устройств для экрана «Подписка» на ТВ (без HWID — он не нужен телевизору)
                devices = [{
                    "platform": d.get("platform"), "os_version": d.get("osVersion"),
                    "model": d.get("deviceModel"),
                    "created_at": d.get("createdAt"), "updated_at": d.get("updatedAt"),
                } for d in items]
            except Exception:
                used = None
    except Exception:
        log.warning("tv: panel unavailable for %s", tg_id, exc_info=True)
    now = datetime.now(timezone.utc)
    if status is None:
        status = "NONE" if not expire else ("ACTIVE" if expire > now else "EXPIRED")
    elif status == "ACTIVE" and expire and expire <= now:
        status = "EXPIRED"
    return {
        "status": status,
        "sub_url": sub_url,
        "expire_at": expire.astimezone(timezone.utc).isoformat() if expire else None,
        "days_left": _days_left(expire) if status == "ACTIVE" else 0,
        "family": bool(user.family),
        "plan": "family" if user.family else "regular",
        "devices_used": used if used is not None else 0,
        "device_limit": limit,
        "devices": devices,
    }


# ---------- HTTP ----------

def _err(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


def client_ip(request: web.Request) -> str:
    return request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip() or "?"


NO_STORE = {"Cache-Control": "no-store"}


async def pair_start(request: web.Request) -> web.Response:
    if not await rate_ok(client_ip(request)):
        return _err("Слишком много попыток, подожди несколько минут", 429)
    name = ""
    if request.can_read_body:
        try:
            body = await request.json()
            name = body.get("name", "") if isinstance(body, dict) else ""
        except Exception:
            name = ""
    pair = await start_pairing(name or request.query.get("name", ""))
    bot = request.app["bot_username"]
    pair["bot_link"] = f"https://t.me/{bot}?start=tv_{pair['code']}"
    return web.json_response(pair, headers=NO_STORE)


async def pair_status(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    if not token or len(token) > 200:
        return _err("Нет токена")
    th = token_hash(token)
    code = await kv().get(_k_tok(th))
    pair = await get_pairing(code) if code else None
    if pair and pair.get("th") == th:
        if pair.get("st") == "confirmed":
            return web.json_response({"status": "confirmed", "sub_url": pair.get("sub"),
                                      "device_name": pair.get("name")}, headers=NO_STORE)
        return web.json_response({"status": "pending", "expires_in": max(0, await kv().ttl(_k_pair(code)))},
                                 headers=NO_STORE)
    # код истёк, но телевизор мог успеть привязаться — отвечаем по базе
    device = await device_by_token(token, touch=False)
    if device:
        info = await subscription_info(device.tg_id)
        return web.json_response({"status": "confirmed", "sub_url": info["sub_url"], "device_name": device.name},
                                 headers=NO_STORE)
    return web.json_response({"status": "expired"}, headers=NO_STORE)


async def tv_me(request: web.Request) -> web.Response:
    device = await device_by_token(request.headers.get("X-TV-Token", ""))
    if device is None:
        return _err("unpaired", 401)
    info = await subscription_info(device.tg_id)
    info["device_name"] = device.name
    return web.json_response(info, headers=NO_STORE)


async def tv_unpair(request: web.Request) -> web.Response:
    device = await device_by_token(request.headers.get("X-TV-Token", ""), touch=False)
    if device is None:
        return web.json_response({"ok": True})
    await revoke_device(device.id, device.tg_id)
    return web.json_response({"ok": True})


async def tv_page(request: web.Request) -> web.Response:
    return web.FileResponse(WEB_DIR / "tv.html", headers={"Cache-Control": "no-cache",
                                                           "Content-Type": "text/html; charset=utf-8"})


async def tv_apk(request: web.Request):
    path = TV_DIR / "whitehole-tv.apk"
    if path.is_file() and path.stat().st_size > 0:
        return web.FileResponse(path, headers={
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Disposition": 'attachment; filename="whitehole-tv.apk"',
            "Cache-Control": "no-cache",
        })
    raise web.HTTPFound(APK_GITHUB)


async def happ_apk(request: web.Request):
    raise web.HTTPFound(HAPP_APK)


def register(app: web.Application) -> None:
    r = app.router
    r.add_get(PREFIX, tv_page)
    r.add_get(f"{PREFIX}/", tv_page)
    r.add_get(f"{PREFIX}/whitehole-tv.apk", tv_apk)
    r.add_get(f"{PREFIX}/happ.apk", happ_apk)
    r.add_post(f"{PREFIX}/pair/start", pair_start)
    r.add_get(f"{PREFIX}/pair/status", pair_status)
    r.add_get(f"{PREFIX}/me", tv_me)
    r.add_post(f"{PREFIX}/unpair", tv_unpair)
