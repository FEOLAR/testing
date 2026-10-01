from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as kb, texts
from ..config import settings
from ..db import Payment, Session
from ..services import check_crypto_payment, create_crypto_payment, record_stars_payment

router = Router()
log = logging.getLogger(__name__)


@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery):
    await cb.message.edit_text(texts.tariffs(), reply_markup=kb.plans())
    await cb.answer()


@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(cb: CallbackQuery):
    plan = settings.plan(cb.data.split(":", 1)[1])
    if not plan:
        return await cb.answer("Тариф не найден", show_alert=True)
    await cb.message.edit_text(texts.choose_method(plan), reply_markup=kb.methods(plan.code))
    await cb.answer()


# ---------- Telegram Stars ----------

@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars(cb: CallbackQuery):
    plan = settings.plan(cb.data.split(":")[2])
    if not plan:
        return await cb.answer("Тариф не найден", show_alert=True)
    await cb.message.answer_invoice(
        title=f"{settings.brand_name}: {plan.title}",
        description=f"VPN-подписка на {plan.days} дн., до {settings.device_limit} устройств",
        payload=f"vpn:{plan.code}",
        currency="XTR",
        prices=[LabeledPrice(label=plan.title, amount=plan.stars)],
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    ok = q.currency == "XTR" and q.invoice_payload.startswith("vpn:") \
        and settings.plan(q.invoice_payload.split(":")[1]) is not None
    await q.answer(ok=ok, error_message=None if ok else "Тариф устарел, открой меню заново.")


@router.message(F.successful_payment)
async def stars_paid(message: Message):
    sp = message.successful_payment
    log.info("stars paid: user %s payload %s charge %s", message.from_user.id, sp.invoice_payload,
             sp.telegram_payment_charge_id)
    result = await record_stars_payment(message.bot, message.from_user.id, sp.invoice_payload,
                                        sp.total_amount, sp.telegram_payment_charge_id)
    if result == "unknown_plan":
        await message.answer("Оплата получена, подписку активирует администратор в ближайшее время.")


# ---------- CryptoBot ----------

@router.callback_query(F.data.startswith("pay:crypto:"))
async def pay_crypto(cb: CallbackQuery):
    plan = settings.plan(cb.data.split(":")[2])
    if not plan or not settings.crypto_enabled:
        return await cb.answer("Недоступно", show_alert=True)
    payment = await create_crypto_payment(cb.from_user.id, plan)
    if payment is None:
        return await cb.answer("CryptoBot сейчас недоступен, попробуй Stars или позже.", show_alert=True)
    await cb.message.edit_text(texts.crypto_invoice(plan), reply_markup=kb.crypto_pay(payment.pay_url, payment.id))
    await cb.answer()


@router.callback_query(F.data.startswith("check:"))
async def check_crypto(cb: CallbackQuery):
    payment_id = int(cb.data.split(":")[1])
    async with Session() as s:
        payment = await s.get(Payment, payment_id)
    if not payment or payment.tg_id != cb.from_user.id:
        return await cb.answer("Счёт не найден", show_alert=True)
    if payment.status == "paid":
        return await cb.answer("✅ Уже оплачено — подписка активна", show_alert=True)
    if payment.status in ("processing", "grant_error"):  # деньги пришли, панель ещё не выдала дни
        return await cb.answer("✅ Оплата получена, подписка активируется в течение пары минут.", show_alert=True)
    if payment.status != "pending":
        return await cb.answer("Счёт истёк. Создай новый.", show_alert=True)
    try:
        status = await check_crypto_payment(cb.bot, payment)
    except Exception:
        log.exception("cryptopay getInvoices failed")
        return await cb.answer("Не удалось проверить, попробуй через минуту", show_alert=True)
    if status == "paid":
        await cb.answer("✅ Оплата найдена!")
    elif status == "expired":
        await cb.answer("Счёт истёк. Создай новый.", show_alert=True)
    else:
        await cb.answer("Оплата пока не поступила. Если уже оплатил — подожди минуту.", show_alert=True)
