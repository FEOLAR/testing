"""Старый бот после переезда на новый.

Если в .env задан LEGACY_BOT_TOKEN, бот параллельно слушает старый токен и на любое
сообщение отвечает «мы переехали» с кнопкой на нового бота. Реферальные ссылки
(/start ref_…) пробрасываются в нового бота с тем же параметром. Оплату в старом боте
не принимаем — подсказываем, где платить теперь.
"""
from __future__ import annotations

from aiogram import Dispatcher, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery


def build_legacy_dispatcher(new_username: str) -> Dispatcher:
    router = Router()
    base = f"https://t.me/{new_username}"
    text = (f"🚀 Мы переехали в нового бота: @{new_username}\n\n"
            "Подписка, срок и ссылка для приложения сохранились — откройте нового бота и нажмите «Старт».")

    def kb(start_param: str = "") -> InlineKeyboardMarkup:
        url = f"{base}?start={start_param}" if start_param else base
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Открыть нового бота", url=url)]])

    @router.message()
    async def any_message(m: Message):
        param = ""
        if m.text and m.text.startswith("/start "):
            param = m.text.split(maxsplit=1)[1][:64]
        await m.answer(text, reply_markup=kb(param))

    @router.callback_query()
    async def any_callback(cb: CallbackQuery):
        await cb.answer()
        if cb.message:
            await cb.message.answer(text, reply_markup=kb())

    @router.pre_checkout_query()
    async def decline_payment(q: PreCheckoutQuery):
        await q.answer(ok=False, error_message=f"Оплата теперь в новом боте: @{new_username}")

    dp = Dispatcher()
    dp.include_router(router)
    return dp
