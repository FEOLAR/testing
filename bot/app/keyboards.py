from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as M, WebAppInfo

from .config import settings
from .emoji import FALLBACK, button_icon


def btn(icon: str, text: str, **kw) -> B:
    """Все кнопки бота в одном стиле: иконка из фирменного пака + текст, без цветной заливки.
    Если иконки недоступны — обычный эмодзи в начале текста."""
    cid = button_icon(icon)
    if cid:
        return B(text=text, icon_custom_emoji_id=cid, **kw)
    return B(text=f"{FALLBACK[icon]} {text}", **kw)


def _back(to: str = "menu", text: str = "Назад") -> B:
    return btn("back", text, callback_data=to)


def main_menu(show_trial: bool) -> M:
    rows = []
    if show_trial and settings.trial_days > 0:
        rows.append([btn("gift", f"Попробовать {settings.trial_days} дня бесплатно", callback_data="trial")])
    if settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", web_app=WebAppInfo(url=settings.miniapp_url))])
    rows += [
        [btn("user", "Моя подписка", callback_data="profile")],
        [btn("card", "Купить / продлить", callback_data="buy"), btn("book", "Инструкция", callback_data="howto")],
        [btn("bot", "Что умеет бот?", callback_data="about")],
    ]
    if settings.referral_bonus_days > 0:
        rows.append([btn("friends", "Пригласить друга", callback_data="ref")])
    row = []
    if settings.miniapp_url:
        row.append(btn("info", "О сервисе", url=settings.miniapp_url.rstrip("/") + "/info"))
    if settings.support_username:
        row.append(btn("support", "Поддержка", url=f"https://t.me/{settings.support_username}"))
    if row:
        rows.append(row)
    return M(inline_keyboard=rows)


def howto() -> M:
    return M(inline_keyboard=[
        [btn("apple", "Happ не находится в App Store", callback_data="appstore_help")],
        [_back()],
    ])


def back(to: str = "menu") -> M:
    return M(inline_keyboard=[[_back(to)]])


def plans() -> M:
    rows = [[btn("calendar", f"{p.title} — {p.rub} ₽", callback_data=f"plan:{p.code}")] for p in settings.plan_list]
    rows.append([_back()])
    return M(inline_keyboard=rows)


def methods(plan_code: str) -> M:
    plan = settings.plan(plan_code)
    rows = [[btn("star", f"Telegram Stars — {plan.stars} ⭐", callback_data=f"pay:stars:{plan_code}")]]
    if settings.crypto_enabled:
        rows.append([btn("coin", "Криптовалюта (CryptoBot)", callback_data=f"pay:crypto:{plan_code}")])
    rows.append([_back("buy")])
    return M(inline_keyboard=rows)


def crypto_pay(url: str, payment_id: int) -> M:
    return M(inline_keyboard=[
        [btn("card", "Оплатить", url=url)],
        [btn("refresh", "Я оплатил — проверить", callback_data=f"check:{payment_id}")],
        [_back("menu", "В меню")],
    ])


def profile(active: bool) -> M:
    rows = []
    if active and settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", web_app=WebAppInfo(url=settings.miniapp_url))])
    if active:
        rows.append([btn("book", "Инструкция", callback_data="howto")])
        rows.append([btn("refresh", "Сбросить устройства", callback_data="reset_hwid")])
    rows.append([btn("card", "Продлить", callback_data="buy")])
    rows.append([_back()])
    return M(inline_keyboard=rows)


def renew() -> M:
    return M(inline_keyboard=[[btn("card", "Продлить", callback_data="buy")]])
