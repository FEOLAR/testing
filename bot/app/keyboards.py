from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as M, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from .config import settings
from .emoji import FALLBACK, button_icon


def btn(icon: str, text: str, style: str | None = None, **kw) -> B:
    """Кнопка с иконкой из фирменного пака (если недоступна — обычный эмодзи в тексте).
    style — цветная заливка: 'primary' (синяя), 'success' (зелёная), 'danger' (красная) или None."""
    extra = {"style": style} if style else {}
    cid = button_icon(icon)
    if cid:
        return B(text=text, icon_custom_emoji_id=cid, **extra, **kw)
    return B(text=f"{FALLBACK[icon]} {text}", **extra, **kw)


def support_url() -> str:
    """SUPPORT_USERNAME: юзернейм (без @) или числовой ID аккаунта поддержки."""
    sup = settings.support_username.strip().lstrip("@")
    return f"tg://user?id={sup}" if sup.isdigit() else f"https://t.me/{sup}"


def _back(to: str = "menu", text: str = "Назад") -> B:
    return btn("back", text, callback_data=to)


def main_menu(show_trial: bool) -> M:
    rows = []
    if show_trial and settings.trial_days > 0:
        rows.append([btn("gift", f"Попробовать {settings.trial_days} дня бесплатно", "success", callback_data="trial")])
    if settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))])
    rows += [
        [btn("bot", "Что умеет бот?", callback_data="about")],
        [btn("user", "Моя подписка", callback_data="profile")],
        [btn("card", "Купить / продлить", callback_data="buy"), btn("book", "Инструкция", callback_data="howto")],
    ]
    if settings.referral_bonus_days > 0:
        rows.append([btn("friends", "Пригласить друга", callback_data="ref")])
    row = [btn("info", "О сервисе", callback_data="service")]
    if settings.support_username:
        row.append(btn("support", "Поддержка", callback_data="support"))
    rows.append(row)
    return M(inline_keyboard=rows)


MENU_TEXT = "📋 Меню"


def reply_menu() -> ReplyKeyboardMarkup:
    """Постоянная кнопка «Меню» под полем ввода."""
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=MENU_TEXT)]], resize_keyboard=True, is_persistent=True)


def open_app() -> M:
    return M(inline_keyboard=[[btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))]])


def service() -> M:
    rows = []
    if settings.miniapp_url:
        rows.append([btn("globe", "Перейти на сайт", "primary", url=settings.site_url("info"))])
        rows.append([btn("book", "Соглашение", url=settings.site_url("terms")),
                     btn("lock", "Конфиденциальность", url=settings.site_url("privacy"))])
    rows.append([_back()])
    return M(inline_keyboard=rows)


def support() -> M:
    return M(inline_keyboard=[
        [btn("support", "Написать в поддержку", "primary", url=support_url())],
        [_back()],
    ])


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
        [btn("card", "Оплатить", "success", url=url)],
        [btn("refresh", "Я оплатил — проверить", callback_data=f"check:{payment_id}")],
        [_back("menu", "В меню")],
    ])


def profile(active: bool) -> M:
    rows = []
    if active and settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))])
    if active:
        rows.append([btn("book", "Инструкция", callback_data="howto")])
        rows.append([btn("refresh", "Сбросить устройства", callback_data="reset_hwid")])
    rows.append([btn("card", "Продлить", "success" if not active else None, callback_data="buy")])
    rows.append([_back()])
    return M(inline_keyboard=rows)


def renew() -> M:
    return M(inline_keyboard=[[btn("card", "Продлить", "success", callback_data="buy")]])
