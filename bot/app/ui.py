"""Показ экранов бота: приветствие с картинкой и переходы между экранами.

Приветствие — фото с подписью. Переходы из него меняют подпись под той же картинкой;
если текст длиннее лимита подписи (1024), фото заменяется обычным текстовым сообщением.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)

WELCOME_PHOTO = Path(__file__).resolve().parent / "web" / "welcome.jpg"
CAPTION_LIMIT = 1024
_photo_id: str | None = None  # file_id после первой загрузки — дальше фото не перезаливается


async def send_welcome(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    global _photo_id
    if not WELCOME_PHOTO.exists():
        await message.answer(text, reply_markup=markup)
        return
    try:
        sent = await message.answer_photo(_photo_id or FSInputFile(WELCOME_PHOTO), caption=text, reply_markup=markup)
        _photo_id = sent.photo[-1].file_id
    except TelegramBadRequest:
        log.exception("welcome photo failed, fallback to text")
        _photo_id = None
        await message.answer(text, reply_markup=markup)


async def show(cb: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None, **kw) -> None:
    """Показывает экран в том же сообщении, откуда нажата кнопка."""
    msg = cb.message
    try:
        if not msg.photo:
            await msg.edit_text(text, reply_markup=reply_markup, **kw)
        elif len(text) <= CAPTION_LIMIT:
            await msg.edit_caption(caption=text, reply_markup=reply_markup)
        else:
            await msg.answer(text, reply_markup=reply_markup, **kw)
            await _try_delete(msg)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _try_delete(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramBadRequest:  # старше 48 часов — Telegram не даёт удалить, просто оставляем
        pass


async def show_welcome(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Возврат в главное меню: под картинкой, если её нет — присылает приветствие заново."""
    if cb.message.photo:
        await show(cb, text, markup)
    else:
        await send_welcome(cb.message, text, markup)
        await _try_delete(cb.message)
