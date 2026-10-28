"""Бот-визитка без слова VPN в имени — для рекламы и ссылок.

Если в .env задан GATEWAY_BOT_TOKEN, основной процесс параллельно слушает и этого бота. На /start и любое
сообщение он присылает картинку с коротким текстом и двумя кнопками: в основного бота и в канал.
Параметр /start пробрасывается в основного бота: ?start=src_tech → основной бот получит src_tech
(метка видна в /sources), ref_123 — реферальная ссылка работает как обычно. Без параметра — метка
GATEWAY_SOURCE (по умолчанию «vizitka»). Оплату здесь не принимаем.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from aiogram import Bot, Dispatcher, Router
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message,
                           PreCheckoutQuery)

from .config import settings

log = logging.getLogger(__name__)
PHOTO = Path(__file__).parent / "web" / "welcome.jpg"
USERNAME = ""   # @имя визитки, заполняется при запуске
PARAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

TEXT = (
    "<b>WhiteHole</b> — интернет без ограничений\n\n"
    "▫️ YouTube без рекламы и в 8K\n"
    "▫️ ChatGPT, Gemini и другие нейросети\n"
    "▫️ Банки и маркетплейсы работают как обычно\n"
    "▫️ От 3 до 10 устройств, безлимитный трафик\n\n"
    "🎁 <b>3 дня бесплатно</b> — жми кнопку ниже и нажми «Старт»."
)


def start_param(text: str | None) -> str:
    """Параметр для основного бота: свой из ссылки (если «чистый») или метка визитки."""
    if text and text.startswith("/start "):
        arg = text.split(maxsplit=1)[1].strip()
        if PARAM_RE.match(arg):
            return arg
    tag = re.sub(r"[^a-z0-9_-]", "", settings.gateway_source.lower())[:32] or "vizitka"
    return f"src_{tag}"


def keyboard(main_username: str, param: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🚀 Открыть WhiteHole — 3 дня бесплатно",
                                  url=f"https://t.me/{main_username}?start={param}")]]
    if settings.channel_url:
        rows.append([InlineKeyboardButton(text="📢 Наш канал", url=settings.channel_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_gateway_dispatcher(main_username: str) -> Dispatcher:
    router = Router()

    async def send(m: Message, param: str):
        kb = keyboard(main_username, param)
        try:
            if PHOTO.exists():
                return await m.answer_photo(FSInputFile(PHOTO), caption=TEXT, reply_markup=kb, parse_mode="HTML")
        except Exception:
            log.warning("gateway photo failed", exc_info=True)
        await m.answer(TEXT, reply_markup=kb, parse_mode="HTML")

    @router.message()
    async def any_message(m: Message):
        if m.chat.type == "private":
            await send(m, start_param(m.text))

    @router.callback_query()
    async def any_callback(cb: CallbackQuery):
        await cb.answer()
        if cb.message:
            await send(cb.message, start_param(None))

    @router.pre_checkout_query()
    async def decline_payment(q: PreCheckoutQuery):
        await q.answer(ok=False, error_message=f"Оплата — в основном боте: @{main_username}")

    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def setup_profile(bot: Bot) -> None:
    """Описание до «Старт» — без слова VPN."""
    try:
        await bot.set_my_description(
            "WhiteHole — YouTube без рекламы, нейросети, банки и маркетплейсы работают как обычно. "
            "3 дня бесплатно — нажми «Старт».")
        await bot.set_my_short_description("YouTube без рекламы, нейросети и 3 дня бесплатно")
    except Exception:
        log.warning("gateway: cannot set description", exc_info=True)
