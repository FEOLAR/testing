"""API и страница Telegram Mini App. Работает внутри процесса бота (aiohttp, порт 8080).

Наружу отдаётся через Caddy как /miniapp/*. Каждый запрос подписан Telegram (initData),
поэтому пользователь не может выдать себя за другого.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import LabeledPrice
from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web
from sqlalchemy import func, or_, select

from .config import settings
from .db import Payment, Session, User
from .remnawave import panel, parse_dt
from .services import (activate_trial, admin_give, check_crypto_payment, collect_stats,
                       create_crypto_payment, get_or_create_user, refresh_from_panel)

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "web"
PREFIX = "/miniapp"
INIT_DATA_TTL = 24 * 3600


def err(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


# ---------- авторизация ----------

@web.middleware
async def auth_mw(request: web.Request, handler):
    if not request.path.startswith(f"{PREFIX}/api/"):
        return await handler(request)
    raw = request.headers.get("Authorization", "")
    if not raw.startswith("tma "):
        return err("Открой приложение из Telegram", 401)
    try:
        data = safe_parse_webapp_init_data(settings.bot_token, raw[4:])
    except ValueError:
        return err("Подпись Telegram не прошла проверку", 401)
    if time.time() - data.auth_date.timestamp() > INIT_DATA_TTL:
        return err("Сессия устарела, открой приложение заново", 401)
    if not data.user:
        return err("Нет пользователя", 401)
    request["tg"] = data.user
    request["start_param"] = data.start_param or ""
    if request.path.startswith(f"{PREFIX}/api/admin/") and data.user.id not in settings.admins:
        return err("Нет доступа", 403)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        log.exception("miniapp api error: %s", request.path)
        return err("Что-то пошло не так, попробуй ещё раз", 500)


async def current_user(request: web.Request) -> User:
    tg = request["tg"]
    ref = None
    sp = request["start_param"]
    if sp.startswith("ref_") and sp[4:].isdigit():
        ref = int(sp[4:])
    user, _ = await get_or_create_user(tg.id, tg.username, tg.first_name, referrer_id=ref)
    return user


# ---------- сборка ответа ----------

def panel_sub(pu: dict | None, user: User) -> dict:
    now = datetime.now(timezone.utc)
    if not pu:
        return {"status": "NONE", "expire_at": iso(user.expire_at), "sub_url": user.sub_url,
                "traffic_used": 0, "traffic_limit": 0, "device_limit": settings.device_limit,
                "online_at": None}
    expire = parse_dt(pu["expireAt"])
    status = pu.get("status", "ACTIVE")
    if status == "ACTIVE" and expire <= now:
        status = "EXPIRED"
    traffic = pu.get("userTraffic") or {}
    used = traffic.get("usedTrafficBytes", pu.get("usedTrafficBytes", 0)) or 0
    return {
        "status": status,
        "expire_at": iso(expire),
        "sub_url": pu.get("subscriptionUrl") or user.sub_url,
        "traffic_used": used,
        "traffic_limit": pu.get("trafficLimitBytes") or 0,
        "device_limit": pu.get("hwidDeviceLimit") if pu.get("hwidDeviceLimit") is not None else settings.device_limit,
        "online_at": traffic.get("onlineAt", pu.get("onlineAt")),
    }


async def referral_info(bot_username: str, tg_id: int) -> dict:
    async with Session() as s:
        invited = await s.scalar(select(func.count()).where(User.referrer_id == tg_id))
        paid = await s.scalar(select(func.count()).where(User.referrer_id == tg_id,
                                                         User.referral_rewarded.is_(True)))
    return {"link": f"https://t.me/{bot_username}?start=ref_{tg_id}",
            "invited": invited or 0, "paid": paid or 0, "bonus_days": settings.referral_bonus_days}


async def me(request: web.Request) -> web.Response:
    user = await current_user(request)
    tg = request["tg"]
    pu = None
    try:
        pu = await panel.get_user(user.panel_username)
        if pu:
            user = await refresh_from_panel(user)
    except Exception:
        log.exception("panel get_user failed")
    base = settings.plan_list[0]
    plans = []
    for p in settings.plan_list:
        per_month = round(p.rub / (p.days / 30))
        plans.append({"code": p.code, "title": p.title, "days": p.days, "rub": p.rub, "stars": p.stars,
                      "per_month": per_month,
                      "discount": max(0, round(100 - per_month * 100 / base.rub)) if p is not base else 0})
    bot_username = request.app["bot_username"]
    return web.json_response({
        "user": {"id": tg.id, "first_name": tg.first_name, "username": tg.username},
        "is_admin": tg.id in settings.admins,
        "brand": settings.brand_name,
        "support": settings.support_username,
        "bot_username": bot_username,
        "sub": panel_sub(pu, user),
        "trial": {"available": not user.trial_used and settings.trial_days > 0, "days": settings.trial_days},
        "plans": plans,
        "crypto_enabled": settings.crypto_enabled,
        "referral": await referral_info(bot_username, tg.id) if settings.referral_bonus_days > 0 else None,
    })


# ---------- действия пользователя ----------

async def trial(request: web.Request) -> web.Response:
    user = await current_user(request)
    if user.trial_used or settings.trial_days <= 0:
        return err("Пробный период уже использован")
    if await activate_trial(user.tg_id) is None:
        return err("Пробный период уже использован")
    return web.json_response({"ok": True})


async def pay(request: web.Request) -> web.Response:
    body = await request.json()
    plan = settings.plan(str(body.get("plan", "")))
    if not plan:
        return err("Тариф не найден")
    user = await current_user(request)
    bot: Bot = request.app["bot"]
    if body.get("method") == "stars":
        link = await bot.create_invoice_link(
            title=f"{settings.brand_name}: {plan.title}",
            description=f"VPN-подписка на {plan.days} дн., до {settings.device_limit} устройств",
            payload=f"vpn:{plan.code}",
            currency="XTR",
            prices=[LabeledPrice(label=plan.title, amount=plan.stars)],
        )
        return web.json_response({"invoice_link": link})
    if body.get("method") == "crypto":
        if not settings.crypto_enabled:
            return err("Оплата криптой отключена")
        payment = await create_crypto_payment(user.tg_id, plan)
        if payment is None:
            return err("CryptoBot сейчас недоступен, попробуй Stars или позже")
        return web.json_response({"payment_id": payment.id, "pay_url": payment.pay_url})
    return err("Неизвестный способ оплаты")


async def payment_status(request: web.Request) -> web.Response:
    pid = int(request.match_info["pid"])
    async with Session() as s:
        payment = await s.get(Payment, pid)
    if not payment or payment.tg_id != request["tg"].id:
        return err("Счёт не найден", 404)
    try:
        status = await check_crypto_payment(request.app["bot"], payment)
    except Exception:
        log.exception("crypto check failed")
        status = "pending"
    return web.json_response({"status": status})


async def devices(request: web.Request) -> web.Response:
    user = await current_user(request)
    items = await panel.get_devices(user.panel_username)
    return web.json_response({"devices": [{
        "hwid": d.get("hwid"), "platform": d.get("platform"), "os_version": d.get("osVersion"),
        "model": d.get("deviceModel"), "user_agent": d.get("userAgent"),
        "created_at": d.get("createdAt"), "updated_at": d.get("updatedAt"),
    } for d in items]})


async def device_delete(request: web.Request) -> web.Response:
    body = await request.json()
    user = await current_user(request)
    if body.get("all"):
        await panel.reset_devices(user.panel_username)
    elif body.get("hwid"):
        await panel.delete_device(user.panel_username, str(body["hwid"]))
    else:
        return err("Не указано устройство")
    return await devices(request)


# ---------- админка ----------

async def admin_stats(request: web.Request) -> web.Response:
    return web.json_response(await collect_stats())


async def admin_find(request: web.Request) -> web.Response:
    q = request.query.get("q", "").strip().lstrip("@")
    if not q:
        return err("Введи Telegram ID или @username")
    async with Session() as s:
        cond = User.tg_id == int(q) if q.isdigit() else func.lower(User.username) == q.lower()
        user = (await s.execute(select(User).where(cond))).scalars().first()
        if not user:
            return err("Пользователь не найден", 404)
        pays = (await s.execute(select(Payment).where(Payment.tg_id == user.tg_id, Payment.status == "paid")
                                .order_by(Payment.id.desc()).limit(10))).scalars().all()
    pu = None
    try:
        pu = await panel.get_user(user.panel_username)
    except Exception:
        log.exception("panel get_user failed")
    return web.json_response({
        "tg_id": user.tg_id, "username": user.username, "first_name": user.first_name,
        "trial_used": user.trial_used, "referrer_id": user.referrer_id, "blocked_bot": user.is_blocked,
        "created_at": iso(user.created_at), "sub": panel_sub(pu, user),
        "payments": [{"id": p.id, "method": p.method, "amount": p.amount, "days": p.days,
                      "paid_at": iso(p.paid_at)} for p in pays],
    })


async def admin_give_h(request: web.Request) -> web.Response:
    body = await request.json()
    try:
        tg_id, days = int(body["tg_id"]), int(body["days"])
    except (KeyError, ValueError, TypeError):
        return err("Нужны tg_id и days")
    if not 0 < days <= 3650:
        return err("Дней: от 1 до 3650")
    user = await admin_give(request.app["bot"], tg_id, days)
    return web.json_response({"ok": True, "expire_at": iso(user.expire_at)})


async def admin_ban(request: web.Request) -> web.Response:
    body = await request.json()
    try:
        tg_id = int(body["tg_id"])
    except (KeyError, ValueError, TypeError):
        return err("Нужен tg_id")
    await panel.set_enabled(f"tg_{tg_id}", bool(body.get("enable")))
    return web.json_response({"ok": True})


async def admin_recent(request: web.Request) -> web.Response:
    async with Session() as s:
        rows = (await s.execute(
            select(Payment, User.username).join(User, User.tg_id == Payment.tg_id, isouter=True)
            .where(Payment.status == "paid", or_(Payment.method == "stars", Payment.method == "crypto"))
            .order_by(Payment.paid_at.desc()).limit(20))).all()
    return web.json_response({"payments": [{
        "id": p.id, "tg_id": p.tg_id, "username": u, "method": p.method, "amount": p.amount,
        "days": p.days, "paid_at": iso(p.paid_at)} for p, u in rows]})


# ---------- страница ----------

async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})


async def tg_js(request: web.Request) -> web.FileResponse:
    # Копия telegram-web-app.js: telegram.org из РФ может открываться нестабильно
    return web.FileResponse(WEB_DIR / "tg.js", headers={"Cache-Control": "public, max-age=86400"})


DEEPLINK_SCHEMES = ("happ://", "hiddify://", "streisand://", "v2raytun://", "flclashx://", "clash://", "sing-box://")
GO_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Открываю приложение…</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d17;color:#e8eaf2;
font:16px system-ui,sans-serif;text-align:center;padding:24px}a{display:inline-block;margin-top:16px;
padding:14px 22px;border-radius:14px;background:#7c5cff;color:#fff;text-decoration:none;font-weight:600}</style>
</head><body><div><div>Открываю приложение…</div><a id="l" href="#">Открыть вручную</a>
<p style="color:#8a90a6;font-size:14px">Если ничего не произошло — установи приложение и нажми кнопку ещё раз.</p></div>
<script>var u=%s;document.getElementById('l').href=u;location.href=u;</script></body></html>"""


async def go(request: web.Request) -> web.Response:
    """Переход в VPN-приложение. Telegram не открывает happ:// напрямую, поэтому через браузер."""
    import json
    u = request.query.get("u", "")
    if not u.startswith(DEEPLINK_SCHEMES):
        return web.Response(status=400, text="bad link")
    return web.Response(text=GO_PAGE % json.dumps(u).replace("</", "<\\/"), content_type="text/html")


async def redirect_root(request: web.Request):
    raise web.HTTPFound(f"{PREFIX}/")


def build_app(bot: Bot, bot_username: str) -> web.Application:
    app = web.Application(middlewares=[auth_mw], client_max_size=64 * 1024)
    app["bot"], app["bot_username"] = bot, bot_username
    r = app.router
    r.add_get(PREFIX, redirect_root)
    r.add_get(f"{PREFIX}/", index)
    r.add_get(f"{PREFIX}/tg.js", tg_js)
    r.add_get(f"{PREFIX}/go", go)
    r.add_get(f"{PREFIX}/api/me", me)
    r.add_post(f"{PREFIX}/api/trial", trial)
    r.add_post(f"{PREFIX}/api/pay", pay)
    r.add_get(f"{PREFIX}/api/payment/{{pid:\\d+}}", payment_status)
    r.add_get(f"{PREFIX}/api/devices", devices)
    r.add_post(f"{PREFIX}/api/devices/delete", device_delete)
    r.add_get(f"{PREFIX}/api/admin/stats", admin_stats)
    r.add_get(f"{PREFIX}/api/admin/user", admin_find)
    r.add_get(f"{PREFIX}/api/admin/payments", admin_recent)
    r.add_post(f"{PREFIX}/api/admin/give", admin_give_h)
    r.add_post(f"{PREFIX}/api/admin/ban", admin_ban)
    return app


async def start_webapp(bot: Bot) -> web.AppRunner:
    me_ = await bot.me()
    runner = web.AppRunner(build_app(bot, me_.username), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", settings.webapp_port).start()
    log.info("mini app listening on :%s%s/", settings.webapp_port, PREFIX)
    return runner
