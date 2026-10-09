"""Промокоды: скидка в процентах на любой тариф.

- Админ создаёт код (/promo_add или вкладка «Админ» в мини-аппе), задаёт скидку и лимит активаций (0 — без лимита),
  может включать/выключать код и менять лимит.
- Пользователь вводит код в боте или мини-аппе — он запоминается (users.promo_id) и цены показываются со скидкой.
- Активация засчитывается, только когда оплата со скидкой прошла (payments.promo_id). Один код — один раз на человека.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, select, update

from .config import Plan
from .db import Payment, PromoCode, Session, User

USED = ("paid", "processing", "grant_error")   # оплата прошла (или выдача в процессе) — активация считается
CODE_RE = re.compile(r"^[A-Z0-9_-]{3,32}$")
MAX_PERCENT = 99


def normalize(code: str | None) -> str:
    return (code or "").strip().upper()


def discounted(value: int, percent: int) -> int:
    return max(1, round(value * (100 - percent) / 100))


def price(plan: Plan, promo: PromoCode | None) -> tuple[int, int]:
    """(рубли, звёзды) с учётом скидки."""
    if not promo:
        return plan.rub, plan.stars
    return discounted(plan.rub, promo.percent), discounted(plan.stars, promo.percent)


async def uses_count(s, promo_id: int) -> int:
    return await s.scalar(select(func.count(func.distinct(Payment.tg_id)))
                          .where(Payment.promo_id == promo_id, Payment.status.in_(USED))) or 0


async def used_by(s, promo_id: int, tg_id: int) -> bool:
    return bool(await s.scalar(select(Payment.id).where(
        Payment.promo_id == promo_id, Payment.tg_id == tg_id, Payment.status.in_(USED)).limit(1)))


async def check(promo: PromoCode | None, tg_id: int) -> str | None:
    """None — код можно применить, иначе текст причины."""
    if promo is None:
        return "Такого промокода нет"
    if not promo.is_active:
        return "Этот промокод сейчас не действует"
    async with Session() as s:
        if await used_by(s, promo.id, tg_id):
            return "Ты уже использовал этот промокод"
        if promo.max_uses and await uses_count(s, promo.id) >= promo.max_uses:
            return "Промокод закончился — все активации уже использованы"
    return None


async def get(promo_id: int | None) -> PromoCode | None:
    if not promo_id:
        return None
    async with Session() as s:
        return await s.get(PromoCode, promo_id)


async def find(code: str) -> PromoCode | None:
    async with Session() as s:
        return (await s.execute(select(PromoCode).where(PromoCode.code == normalize(code)))).scalars().first()


async def apply(tg_id: int, code: str) -> tuple[PromoCode | None, str | None]:
    """Применяет код к пользователю. Возвращает (промокод, None) или (None, причина отказа)."""
    promo = await find(code) if CODE_RE.match(normalize(code)) else None
    error = await check(promo, tg_id)
    if error:
        return None, error
    async with Session() as s:
        await s.execute(update(User).where(User.tg_id == tg_id).values(promo_id=promo.id))
        await s.commit()
    return promo, None


async def clear(tg_id: int) -> None:
    async with Session() as s:
        await s.execute(update(User).where(User.tg_id == tg_id).values(promo_id=None))
        await s.commit()


async def current(tg_id: int) -> PromoCode | None:
    """Применённый пользователем код, если он всё ещё действует (иначе сбрасывается)."""
    async with Session() as s:
        user = await s.get(User, tg_id)
        promo_id = user.promo_id if user else None
    promo = await get(promo_id)
    if promo_id and await check(promo, tg_id):
        await clear(tg_id)
        return None
    return promo


# ---------- админка ----------

async def create(code: str, percent: int, max_uses: int = 0) -> tuple[PromoCode | None, str | None]:
    code = normalize(code)
    if not CODE_RE.match(code):
        return None, "Код: 3–32 символа, латинские буквы, цифры, «-» и «_»"
    if not 1 <= percent <= MAX_PERCENT:
        return None, f"Скидка: от 1 до {MAX_PERCENT}%"
    if max_uses < 0:
        return None, "Лимит не может быть отрицательным (0 — без лимита)"
    if await find(code):
        return None, "Такой промокод уже есть"
    async with Session() as s:
        promo = PromoCode(code=code, percent=percent, max_uses=max_uses, is_active=True)
        s.add(promo)
        await s.commit()
        return promo, None


async def update_promo(promo_id: int, *, active: bool | None = None, max_uses: int | None = None) -> PromoCode | None:
    async with Session() as s:
        promo = await s.get(PromoCode, promo_id)
        if not promo:
            return None
        if active is not None:
            promo.is_active = active
        if max_uses is not None:
            promo.max_uses = max(0, max_uses)
        await s.commit()
        return promo


async def list_all() -> list[dict]:
    async with Session() as s:
        promos = (await s.execute(select(PromoCode).order_by(PromoCode.id.desc()))).scalars().all()
        out = []
        for p in promos:
            out.append(as_dict(p, await uses_count(s, p.id)))
        return out


def as_dict(p: PromoCode, used: int) -> dict:
    return {"id": p.id, "code": p.code, "percent": p.percent, "max_uses": p.max_uses, "used": used,
            "active": p.is_active, "created_at": p.created_at.isoformat() if p.created_at else None}


async def uses(promo_id: int) -> list[dict]:
    """Кто использовал код: пользователь, тариф, сумма, когда."""
    async with Session() as s:
        rows = (await s.execute(
            select(Payment, User.username, User.first_name)
            .join(User, User.tg_id == Payment.tg_id, isouter=True)
            .where(Payment.promo_id == promo_id, Payment.status.in_(USED))
            .order_by(Payment.paid_at.desc().nulls_last(), Payment.id.desc()))).all()
    return [{"tg_id": p.tg_id, "username": un, "first_name": fn, "days": p.days, "amount": p.amount,
             "method": p.method, "paid_at": p.paid_at.isoformat() if isinstance(p.paid_at, datetime) else None}
            for p, un, fn in rows]


# ---------- счёт Telegram Stars ----------

def stars_payload(plan: Plan, promo: PromoCode | None) -> str:
    return f"vpn:{plan.code}" + (f":p{promo.id}" if promo else "")


def parse_payload(payload: str) -> tuple[str, int | None]:
    """'vpn:d30' / 'vpn:d30:p5' -> ('d30', 5). Для чужого payload — ('', None)."""
    if not payload.startswith("vpn:"):
        return "", None
    parts = payload.split(":")
    code = parts[1] if len(parts) > 1 else ""
    promo_id = int(parts[2][1:]) if len(parts) > 2 and parts[2][:1] == "p" and parts[2][1:].isdigit() else None
    return code, promo_id
