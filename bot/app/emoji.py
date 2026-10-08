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
    ("trash", "🗑"), ("game", "🎮"), ("bot", "🤖"), ("apple", "🍏"),
]
FALLBACK = dict(ICONS)
_ids: dict[str, str] = {}
_source: dict[str, str] = {}   # иконка -> откуда взята: "pack" (EMOJI_PACK) или "own" (свой пак бота)
_pack_items: list[tuple[str, str]] = []  # (эмодзи-заменитель, custom_emoji_id) из EMOJI_PACK по порядку

# Какие обычные эмодзи считать «той же иконкой» при автоподборе из EMOJI_PACK
ALIASES: dict[str, tuple[str, ...]] = {
    "logo": ("🕳", "🌌", "⚫", "🌑", "🪐"), "zap": ("⚡",), "shield": ("🛡",), "globe": ("🌐", "🌍", "🌎", "🌏"),
    "phone": ("📱", "📲"), "app": ("📱", "📲"), "gift": ("🎁",), "down": ("👇", "⬇"), "card": ("💳",),
    "coin": ("🪙", "💰", "💵"), "star": ("⭐", "🌟"), "user": ("👤", "🙂"), "book": ("📖", "📚", "📘", "📗"),
    "plug": ("🔌",), "info": ("ℹ", "❓", "❔"), "support": ("💬", "🆘", "👨‍💻"), "friends": ("👥", "🤝"),
    "key": ("🔑", "🗝"), "ok": ("✅", "✔"), "no": ("❌", "✖"), "clock": ("⏳", "⏰", "🕐", "⌛"),
    "rocket": ("🚀",), "lock": ("🔒", "🔐"), "wifi": ("📶", "🛜"), "refresh": ("🔄", "🔃", "♻"),
    "crown": ("👑",), "settings": ("⚙",), "bank": ("🏦",), "back": ("⬅", "◀", "🔙", "↩"),
    "calendar": ("📅", "📆", "🗓"), "trash": ("🗑",), "game": ("🎮", "🕹"), "bot": ("🤖",), "apple": ("🍏", "🍎"),
}


def _norm(ch: str) -> str:
    return (ch or "").replace("\ufe0f", "").strip()


def e(name: str) -> str:
    """Эмодзи для текста (HTML): фирменный, если пак загружен, иначе обычный."""
    fb = FALLBACK[name]
    cid = _ids.get(name)
    return f'<tg-emoji emoji-id="{cid}">{fb}</tg-emoji>' if cid else fb


_TAG = __import__("re").compile(r":([a-z]+):")


def render(text: str) -> str:
    """Заменяет метки :zap:, :logo: и т.п. на эмодзи из пака (неизвестные метки оставляет как есть)."""
    return _TAG.sub(lambda m: e(m.group(1)) if m.group(1) in FALLBACK else m.group(0), text)


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
                _source[icon] = "own"
        log.info("emoji: pack %s ready, %d icons", name, len(_ids))
    except Exception:
        log.exception("emoji: setup failed, using plain emoji")
    await load_brand_pack(bot)


def _manual_map() -> dict[str, int]:
    out = {}
    for chunk in settings.emoji_map.replace(" ", "").split(","):
        if "=" in chunk:
            name, num = chunk.split("=", 1)
            if name in FALLBACK and num.isdigit():
                out[name] = int(num)
    return out


async def load_brand_pack(bot: Bot) -> None:
    """Подменяет иконки на эмодзи из фирменного пака EMOJI_PACK (например, сделанного через @TgEmodziBot).
    Иконка подбирается по обычному эмодзи, к которому привязан значок в паке (⚡ → zap и т.д.);
    точное соответствие можно задать в .env: EMOJI_MAP=zap=3,logo=1 (номера — из /emoji ИМЯ_ПАКА).
    Что не нашлось — остаётся из своего пака бота (видно в /icons)."""
    if not settings.emoji_pack:
        return
    name = settings.emoji_pack.strip().rstrip("/").split("/")[-1]
    try:
        pack = await bot.get_sticker_set(name)
    except Exception:
        log.exception("emoji: brand pack %s unavailable", name)
        return
    _pack_items[:] = [(st.emoji or "", st.custom_emoji_id) for st in pack.stickers if st.custom_emoji_id]
    manual, used = _manual_map(), set()
    for icon, num in manual.items():
        if 1 <= num <= len(_pack_items):
            _ids[icon], _source[icon] = _pack_items[num - 1][1], "pack"
            used.add(num - 1)
    for icon, fb in ICONS:
        if icon in manual:
            continue
        wanted = {_norm(fb), *(_norm(a) for a in ALIASES.get(icon, ()) if a)}
        for i, (em, cid) in enumerate(_pack_items):
            if _norm(em) in wanted:
                _ids[icon], _source[icon] = cid, "pack"
                break
    found = sum(1 for v in _source.values() if v == "pack")
    log.info("emoji: brand pack %s — %d icons, matched %d of %d", name, len(_pack_items), found, len(ICONS))


def report() -> str:
    """Для /icons: какая иконка откуда."""
    rows = []
    for icon, fb in ICONS:
        src = {"pack": "из пака", "own": "своя (нет в паке)"}.get(_source.get(icon), "обычный эмодзи")
        rows.append(f"{e(icon)} <code>{icon}</code> — {src}")
    return "\n".join(rows)


# ---------- иконки на кнопках ----------
# Telegram разрешает боту ставить на кнопки иконки из своего пака (icon_custom_emoji_id), пока у владельца
# бота есть Telegram Premium. Если Telegram откажет (Premium закончился и т.п.) — middleware ниже повторит
# запрос без иконок и выключит их до перезапуска бота: меню не сломается, вернутся обычные эмодзи в тексте.
_buttons_ok = True


def button_icon(name: str) -> str | None:
    """ID фирменной иконки для кнопки или None (тогда в тексте кнопки остаётся обычный эмодзи)."""
    return _ids.get(name) if (_buttons_ok and settings.button_icons) else None


def _strip_icons(markup):
    rows = getattr(markup, "inline_keyboard", None)
    if not rows or not any(getattr(b, "icon_custom_emoji_id", None) for row in rows for b in row):
        return None
    fixed = []
    for row in rows:
        new_row = []
        for b in row:
            if getattr(b, "icon_custom_emoji_id", None):
                icon = next((n for n, cid in _ids.items() if cid == b.icon_custom_emoji_id), None)
                text = f"{FALLBACK[icon]} {b.text}" if icon else b.text
                b = b.model_copy(update={"icon_custom_emoji_id": None, "text": text})
            new_row.append(b)
        fixed.append(new_row)
    return markup.model_copy(update={"inline_keyboard": fixed})


class ButtonIconsGuard:
    """Request-middleware: при отказе Telegram из-за иконок на кнопках повторяет запрос без них."""

    async def __call__(self, make_request, bot, method):
        global _buttons_ok
        try:
            return await make_request(bot, method)
        except Exception as err:
            from aiogram.exceptions import TelegramBadRequest
            markup = getattr(method, "reply_markup", None)
            plain = _strip_icons(markup) if isinstance(err, TelegramBadRequest) else None
            if plain is None or "not modified" in str(err):
                raise
            try:
                result = await make_request(bot, method.model_copy(update={"reply_markup": plain}))
            except Exception:
                raise err  # без иконок тоже ошибка — значит, дело не в них
            if _buttons_ok:  # без иконок прошло — выключаем их до перезапуска
                log.warning("emoji: Telegram rejected button icons (%s) — turning them off", err)
                _buttons_ok = False
            return result
