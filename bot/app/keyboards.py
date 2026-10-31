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


def main_menu(show_trial: bool, show_channel: bool = False) -> M:
    from .texts import channel_button
    rows = []
    if show_trial and settings.trial_days > 0:
        rows.append([btn("gift", f"Попробовать {settings.trial_days} дня бесплатно", "success", callback_data="trial")])
    if show_channel and settings.channel_name and settings.channel_bonus_days > 0:
        rows.append([btn("gift", channel_button(), "success", callback_data="channel")])
    if settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))])
    rows += [
        [btn("bot", "Что умеет бот?", callback_data="about")],
        [btn("user", "Моя подписка", callback_data="profile")],
        [btn("star", "Оставить отзыв", callback_data="review")],
        [btn("card", "Тарифы", callback_data="buy"), btn("book", "Инструкция", callback_data="howto")],
    ]
    if settings.referral_bonus_days > 0:
        rows.append([btn("friends", "Пригласить друга", callback_data="ref")])
    row = [btn("info", "О сервисе", callback_data="service")]
    if settings.support_username:
        row.append(btn("support", "Поддержка", callback_data="support"))
    rows.append(row)
    return M(inline_keyboard=rows)


MENU_TEXT = "📋 Меню"   # текст кнопки без фирменной иконки (с иконкой — просто «Меню»)


def reply_menu() -> ReplyKeyboardMarkup:
    """Постоянная кнопка «Меню» под полем ввода (с иконкой из пака, если доступна)."""
    cid = button_icon("menu")
    button = KeyboardButton(text="Меню", icon_custom_emoji_id=cid) if cid else KeyboardButton(text=MENU_TEXT)
    return ReplyKeyboardMarkup(keyboard=[[button]], resize_keyboard=True, is_persistent=True)


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
        [btn("apple", "Happ недоступен в App Store", callback_data="appstore_help")],
        [btn("play", "Подключить телевизор", callback_data="tv_code")],
        [_back()],
    ])


# ---------- телевизор ----------

def tv_confirm(code: str) -> M:
    return M(inline_keyboard=[
        [btn("ok", "Подключить ТВ", "success", callback_data=f"tv_ok:{code}")],
        [btn("no", "Отмена", callback_data="tv_no")],
    ])


def tv_no_sub(show_trial: bool) -> M:
    rows = []
    if show_trial and settings.trial_days > 0:
        rows.append([btn("gift", f"Попробовать {settings.trial_days} дня бесплатно", "success", callback_data="trial")])
    rows.append([btn("card", "Тарифы", "primary" if show_trial else "success", callback_data="buy")])
    rows.append([_back("menu", "В меню")])
    return M(inline_keyboard=rows)


def tv_done() -> M:
    return M(inline_keyboard=[[btn("user", "Моя подписка", callback_data="profile")], [_back("menu", "В меню")]])


def tv_list(devices: list) -> M:
    rows = [[btn("trash", f"Отвязать «{(d.name or 'Телевизор')[:24]}»", callback_data=f"tv_del:{d.id}")]
            for d in devices[:8]]
    rows.append([_back("profile", "К подписке")])
    return M(inline_keyboard=rows)


def back(to: str = "menu") -> M:
    return M(inline_keyboard=[[_back(to)]])


def plans(promo=None, family: bool = False) -> M:
    from .promo import price
    rows = [[btn("calendar", f"{p.title} — {price(p, promo)[0]} ₽", callback_data=f"plan:{p.code}")]
            for p in (settings.family_plan_list if family else settings.plan_list)]
    if settings.family_plan_list:
        rows.append([btn("phone", f"Обычный — до {settings.device_limit} устройств", callback_data="buy_regular")]
                    if family else
                    [btn("friends", f"Семейный — до {settings.family_device_limit} устройств", "primary",
                         callback_data="buy_family")])
    if promo:
        rows.append([btn("no", f"Убрать промокод {promo.code}", callback_data="promo_off")])
    else:
        rows.append([btn("ticket", "Ввести промокод", callback_data="promo")])
    rows.append([_back()])
    return M(inline_keyboard=rows)


def methods(plan, promo=None) -> M:
    from .promo import price
    rub, stars = price(plan, promo)
    rows = []
    if settings.card_enabled:
        rows.append([btn("card", f"{settings.platega_title} — {rub} ₽", "success", callback_data=f"pay:card:{plan.code}")])
    rows.append([btn("star", f"Telegram Stars — {stars}", callback_data=f"pay:stars:{plan.code}")])
    if settings.crypto_enabled:
        rows.append([btn("coin", f"Криптовалюта — {rub} ₽", callback_data=f"pay:crypto:{plan.code}")])
    rows.append([_back("buy_family" if getattr(plan, "family", False) else "buy_regular")])
    return M(inline_keyboard=rows)


def invoice_pay(url: str, payment_id: int) -> M:
    """Кнопки под выставленным счётом (карта или крипта): оплатить, проверить, в меню."""
    return M(inline_keyboard=[
        [btn("card", "Оплатить", "success", url=url)],
        [btn("refresh", "Я оплатил — проверить", callback_data=f"check:{payment_id}")],
        [_back("menu", "В меню")],
    ])


def profile(active: bool, tv_count: int = 0) -> M:
    rows = []
    if active and settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))])
    if active:
        rows.append([btn("book", "Инструкция", callback_data="howto")])
        rows.append([btn("refresh", "Сбросить устройства", callback_data="reset_hwid")])
        rows.append([btn("lock", "Заменить ссылку", callback_data="revoke")])
    if tv_count:
        rows.append([btn("play", f"Телевизоры ({tv_count}) — отвязать", callback_data="tv_list")])
    rows.append([btn("card", "Продлить", "success" if not active else None, callback_data="buy")])
    rows.append([_back()])
    return M(inline_keyboard=rows)


def revoke_confirm() -> M:
    return M(inline_keyboard=[
        [btn("lock", "Да, заменить ссылку", "danger", callback_data="revoke_do")],
        [_back("profile", "Отмена")],
    ])


def revoke_done() -> M:
    rows = []
    if settings.miniapp_url:
        rows.append([btn("app", "Открыть приложение", "primary", web_app=WebAppInfo(url=settings.miniapp_url))])
    rows.append([btn("book", "Инструкция", callback_data="howto")])
    rows.append([_back("profile", "К подписке")])
    return M(inline_keyboard=rows)


def renew() -> M:
    return M(inline_keyboard=[[btn("card", "Продлить", "success", callback_data="buy")]])


def channel(gate: bool = False) -> M:
    """Экран канала. gate=True — КПП при первом /start: без «Назад», проверка ведёт сразу в меню."""
    rows = [
        [btn("link", "Подписаться на канал", "primary", url=settings.channel_url)],
        [btn("ok", "Я подписался — проверить", "success", callback_data="gate_check" if gate else "channel_check")],
    ]
    if not gate:
        rows.append([_back()])
    return M(inline_keyboard=rows)


def review_reminder() -> M:
    return M(inline_keyboard=[[btn("star", "Оставить отзыв", "primary", callback_data="review")]])
