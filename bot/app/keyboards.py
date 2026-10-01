from aiogram.types import InlineKeyboardButton as B, InlineKeyboardMarkup as M, WebAppInfo

from .config import settings


def main_menu(show_trial: bool) -> M:
    rows = [
        [B(text="💳 Купить / продлить", callback_data="buy")],
        [B(text="👤 Моя подписка", callback_data="profile"), B(text="📲 Инструкция", callback_data="howto")],
        [B(text="🔌 VPN сам отключается", callback_data="disconnect_help")],
    ]
    if settings.miniapp_url:
        rows.insert(0, [B(text="📱 Открыть приложение", web_app=WebAppInfo(url=settings.miniapp_url))])
    if show_trial and settings.trial_days > 0:
        rows.insert(0, [B(text=f"🎁 Попробовать {settings.trial_days} дня бесплатно", callback_data="trial")])
    row = []
    if settings.referral_bonus_days > 0:
        row.append(B(text="👥 Пригласить друга", callback_data="ref"))
    if settings.support_username:
        row.append(B(text="💬 Поддержка", url=f"https://t.me/{settings.support_username}"))
    if row:
        rows.append(row)
    return M(inline_keyboard=rows)


def back(to: str = "menu") -> M:
    return M(inline_keyboard=[[B(text="⬅️ Назад", callback_data=to)]])


def plans() -> M:
    rows = [[B(text=f"{p.title} — {p.rub} ₽", callback_data=f"plan:{p.code}")] for p in settings.plan_list]
    rows.append([B(text="⬅️ Назад", callback_data="menu")])
    return M(inline_keyboard=rows)


def methods(plan_code: str) -> M:
    plan = settings.plan(plan_code)
    rows = [[B(text=f"⭐ Telegram Stars — {plan.stars} ⭐", callback_data=f"pay:stars:{plan_code}")]]
    if settings.crypto_enabled:
        rows.append([B(text="🪙 Криптовалюта (CryptoBot)", callback_data=f"pay:crypto:{plan_code}")])
    rows.append([B(text="⬅️ Назад", callback_data="buy")])
    return M(inline_keyboard=rows)


def crypto_pay(url: str, payment_id: int) -> M:
    return M(inline_keyboard=[
        [B(text="💸 Оплатить", url=url)],
        [B(text="🔄 Я оплатил — проверить", callback_data=f"check:{payment_id}")],
        [B(text="⬅️ В меню", callback_data="menu")],
    ])


def profile(active: bool) -> M:
    rows = []
    if active and settings.miniapp_url:
        rows.append([B(text="📱 Открыть приложение", web_app=WebAppInfo(url=settings.miniapp_url))])
    if active:
        rows.append([B(text="📲 Инструкция", callback_data="howto")])
        rows.append([B(text="🔌 VPN сам отключается", callback_data="disconnect_help")])
        rows.append([B(text="🔄 Сбросить устройства", callback_data="reset_hwid")])
    rows.append([B(text="💳 Продлить", callback_data="buy")])
    rows.append([B(text="⬅️ Назад", callback_data="menu")])
    return M(inline_keyboard=rows)


def renew() -> M:
    return M(inline_keyboard=[[B(text="💳 Продлить", callback_data="buy")]])
