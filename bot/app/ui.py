"""Показ экранов бота: одно сообщение-«экран» с картинкой сверху и текстом под ней.

Приветствие — фото чёрной дыры с подписью. При переходе по кнопкам в том же сообщении меняются
картинка (баннер раздела из web/screens/) и подпись. Если текст длиннее лимита подписи (1024),
экран присылается обычным текстовым сообщением.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, InputMediaPhoto, Message

log = logging.getLogger(__name__)

WEB = Path(__file__).resolve().parent / "web"
WELCOME_PHOTO = WEB / "welcome.jpg"
CAPTION_LIMIT = 1024

# Баннеры разделов: имя -> файл. Заменить картинку = положить новый файл с тем же именем и пересобрать.
SCREENS = {
    "welcome": WELCOME_PHOTO,
    "tariffs": WEB / "screens" / "tariffs.jpg",
    "about": WEB / "screens" / "about.jpg",
    "howto": WEB / "screens" / "howto.jpg",
    "partner": WEB / "screens" / "partner.jpg",
    "referral": WEB / "screens" / "referral.jpg",
    "support": WEB / "screens" / "support.jpg",
}
_file_id: dict[str, str] = {}   # имя -> file_id после первой загрузки (дальше файл не перезаливается)
_unique: dict[str, str] = {}    # имя -> file_unique_id, чтобы понять, какая картинка сейчас в сообщении


def _media(name: str):
    path = SCREENS.get(name)
    if not path or not path.exists():
        return None
    return _file_id.get(name) or FSInputFile(path)


def _remember(name: str, msg: Message | None) -> None:
    if msg is not None and getattr(msg, "photo", None):
        _file_id[name] = msg.photo[-1].file_id
        _unique[name] = msg.photo[-1].file_unique_id


async def send_screen(message: Message, text: str, markup: InlineKeyboardMarkup | None, photo: str = "welcome") -> None:
    """Новое сообщение-экран (после /start или когда старое нельзя отредактировать)."""
    media = _media(photo)
    if media is None or len(text) > CAPTION_LIMIT:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        return
    try:
        sent = await message.answer_photo(media, caption=text, reply_markup=markup)
        _remember(photo, sent)
    except TelegramBadRequest:
        log.exception("screen photo %s failed, fallback to text", photo)
        _file_id.pop(photo, None)
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def send_welcome(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    await send_screen(message, text, markup, "welcome")


async def show(cb: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None,
               photo: str = "welcome", **kw) -> None:
    """Показывает экран в том же сообщении, откуда нажата кнопка, с баннером раздела photo."""
    msg = cb.message
    try:
        if not msg.photo:
            if _media(photo) is not None and len(text) <= CAPTION_LIMIT:
                await send_screen(msg, text, reply_markup, photo)  # было текстом — возвращаем картинку
                await _try_delete(msg)
            else:
                await msg.edit_text(text, reply_markup=reply_markup, **kw)
        elif len(text) > CAPTION_LIMIT or _media(photo) is None:
            await msg.answer(text, reply_markup=reply_markup, **kw)
            await _try_delete(msg)
        elif _unique.get(photo) == msg.photo[-1].file_unique_id:
            await msg.edit_caption(caption=text, reply_markup=reply_markup)  # картинка та же — меняем только текст
        else:
            edited = await msg.edit_media(InputMediaPhoto(media=_media(photo), caption=text), reply_markup=reply_markup)
            _remember(photo, edited if isinstance(edited, Message) else None)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


async def _try_delete(msg: Message) -> None:
    try:
        await msg.delete()
    except TelegramBadRequest:  # старше 48 часов — Telegram не даёт удалить, просто оставляем
        pass


async def show_welcome(cb: CallbackQuery, text: str, markup: InlineKeyboardMarkup) -> None:
    """Возврат в главное меню — снова фото чёрной дыры."""
    await show(cb, text, markup, photo="welcome")
