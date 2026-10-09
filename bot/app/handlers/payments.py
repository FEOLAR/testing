from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from .. import keyboards as kb, promo as promos, texts, ui
from ..config import settings
from ..db import Payment, Session
from ..services import check_crypto_payment, create_crypto_payment, record_stars_payment

router = Router()
log = logging.getLogger(__name__)


@router.callback_query(F.data == "buy")
async def buy(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    promo = await promos.current(cb.from_user.id)
    await ui.show(cb, texts.tariffs(promo), reply_markup=kb.plans(promo), photo="tariffs")
    await cb.answer()


@router.callback_query(F.data.startswith("plan:"))
async def choose_plan(cb: CallbackQuery):
    plan = settings.plan(cb.data.split(":", 1)[1])
    if not plan:
        return await cb.answer("Тариф не найден", show_alert=True)
    promo = await promos.current(cb.from_user.id)
    await ui.show(cb, texts.choose_method(plan, promo), reply_markup=kb.methods(plan, promo), photo="tariffs")
    await cb.answer()


# ---------- промокод ----------

class PromoInput(StatesGroup):
    code = State()


@router.callback_query(F.data == "promo")
async def promo_ask(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoInput.code)
    await ui.show(cb, texts.promo_ask(), reply_markup=kb.back("buy"), photo="tariffs")
    await cb.answer()


@router.callback_query(F.data == "promo_off")
async def promo_off(cb: CallbackQuery):
    await promos.clear(cb.from_user.id)
    await ui.show(cb, texts.tariffs(None), reply_markup=kb.plans(None), photo="tariffs")
    await cb.answer("Промокод убран")


@router.message(PromoInput.code, F.text, ~F.text.startswith("/"), ~F.text.in_({kb.MENU_TEXT, "Меню", "меню"}))
async def promo_entered(message: Message, state: FSMContext):
    promo, error = await promos.apply(message.from_user.id, message.text)
    if error:
        return await message.answer(f"❌ {error}. Проверь код и отправь ещё раз или нажми «Назад».",
                                    reply_markup=kb.back("buy"))
    await state.clear()
    await ui.send_screen(message, texts.tariffs(promo), kb.plans(promo), "tariffs")


# ---------- Telegram Stars ----------

@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars(cb: CallbackQuery):
    plan = settings.plan(cb.data.split(":")[2])
    if not plan:
        return await cb.answer("Тариф не найден", show_alert=True)
    promo = await promos.current(cb.from_user.id)
    _, stars = promos.price(plan, promo)
    await cb.message.answer_invoice(
        title=f"{settings.brand_name}: {plan.title}",
        description=f"VPN-подписка на {plan.days} дн., до {settings.device_limit} устройств"
                    + (f". Промокод {promo.code}: −{promo.percent}%" if promo else ""),
        payload=promos.stars_payload(plan, promo),
        currency="XTR",
        prices=[LabeledPrice(label=plan.title, amount=stars)],
    )
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    code, promo_id = promos.parse_payload(q.invoice_payload)
    plan = settings.plan(code) if code else None
    promo = await promos.get(promo_id)
    error = "Тариф или цена изменились — открой меню и создай новый счёт."
    if promo_id and (promo is None or await promos.check(promo, q.from_user.id)):
        plan, error = None, "Промокод больше не действует — открой тарифы и создай новый счёт."
    # сумма должна совпадать с текущей ценой тарифа (со скидкой): старый счёт после смены цен не примем
    ok = q.currency == "XTR" and plan is not None and q.total_amount == promos.price(plan, promo)[1]
    await q.answer(ok=ok, error_message=None if ok else error)


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
    promo = await promos.current(cb.from_user.id)
    payment = await create_crypto_payment(cb.from_user.id, plan, promo)
    if payment is None:
        return await cb.answer("CryptoBot сейчас недоступен, попробуй Stars или позже.", show_alert=True)
    await ui.show(cb, texts.crypto_invoice(plan, promos.price(plan, promo)[0]),
                  reply_markup=kb.crypto_pay(payment.pay_url, payment.id), photo="tariffs")
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
