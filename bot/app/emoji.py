"""Фирменные эмодзи бота: свой пак из PNG в web/emoji/ (белые иконки, перекрашиваются под тему).

При запуске бот сам создаёт пак и догружает в него новые иконки. Порядок ICONS менять нельзя —
только дописывать в конец: ID эмодзи сопоставляются с иконками по позиции в паке.
Если пак недоступен (или Telegram не разрешает боту премиум-эмодзи) — в текстах обычные эмодзи.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile, InputSticker

from .config import settings

log = logging.getLogger(__name__)

DIR = Path(__file__).resolve().parent / "web" / "emoji"
ICONS: list[tuple[str, str]] = [  # (имя файла без .png, обычный эмодзи на замену)
    ("logo", "🕳"), ("zap", "⚡️"), ("shield", "🛡"), ("globe", "🌐"), ("phone", "📱"),
    ("gift", "🎁"), ("down", "👇"), ("card", "💳"), ("coin", "🪙"), ("star", "⭐️"),
    ("user", "👤"), ("book", "📖"), ("plug", "🔌"), ("info", "ℹ️"), ("support", "💬"),
    ("friends", "👥"), ("key", "🔑"), ("ok", "✅"), ("no", "❌"), ("clock", "⏳"),
    ("rocket", "🚀"), ("lock", "🔒"), ("wifi", "📶"), ("refresh", "🔄"), ("crown", "👑"),
    ("settings", "⚙️"), ("bank", "🏦"), ("back", "⬅️"), ("app", "📱"), ("calendar", "📅"),
    ("trash", "🗑"),
]
FALLBACK = dict(ICONS)
_ids: dict[str, str] = {}


def e(name: str) -> str:
    """Эмодзи для текста (HTML): фирменный, если пак загружен, иначе обычный."""
    fb = FALLBACK[name]
    cid = _ids.get(name)
    return f'<tg-emoji emoji-id="{cid}">{fb}</tg-emoji>' if cid else fb


def _sticker(name: str, fb: str) -> InputSticker:
    return InputSticker(sticker=FSInputFile(DIR / f"{name}.png"), format="static", emoji_list=[fb])


async def _call(coro_fn):
    for _ in range(5):
        try:
            return await coro_fn()
        except TelegramRetryAfter as err:
            await asyncio.sleep(err.retry_after + 1)
    return await coro_fn()


async def setup(bot: Bot) -> None:
    """Создаёт/дополняет пак и запоминает ID. Ошибки не роняют бота — останутся обычные эмодзи."""
    try:
        me = await bot.me()
        name = f"whicons_by_{me.username}"
        try:
            pack = await bot.get_sticker_set(name)
        except Exception:
            pack = None
        owners = sorted(settings.admins)
        if pack is None:
            first, fb = ICONS[0]
            for owner in owners:  # владелец пака — админ, который уже нажимал /start у бота
                try:
                    await _call(lambda: bot.create_new_sticker_set(
                        user_id=owner, name=name, title=f"{settings.brand_name} icons",
                        stickers=[_sticker(first, fb)], sticker_type="custom_emoji", needs_repainting=True))
                    break
                except Exception:
                    log.warning("emoji: cannot create pack for owner %s", owner, exc_info=True)
            pack = await bot.get_sticker_set(name)
        have = len(pack.stickers)
        if have < len(ICONS):
            for owner in owners:
                try:
                    for icon, fb in ICONS[have:]:
                        await _call(lambda: bot.add_sticker_to_set(user_id=owner, name=name, sticker=_sticker(icon, fb)))
                        have += 1
                    break
                except Exception:
                    log.warning("emoji: cannot add icons as owner %s", owner, exc_info=True)
            pack = await bot.get_sticker_set(name)
        for (icon, _), st in zip(ICONS, pack.stickers):
            if st.custom_emoji_id:
                _ids[icon] = st.custom_emoji_id
        log.info("emoji: pack %s ready, %d icons", name, len(_ids))
    except Exception:
        log.exception("emoji: setup failed, using plain emoji")
