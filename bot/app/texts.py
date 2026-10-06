from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from zoneinfo import ZoneInfo

from .config import Plan, settings
from .emoji import e

TZ = ZoneInfo("Europe/Moscow")


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def days_left(dt: datetime | None) -> int:
    if not dt:
        return 0
    return max(0, (dt - datetime.now(timezone.utc)).days)


def welcome(name: str | None) -> str:
    return (
        f"{e('logo')} <b>Добро пожаловать в {escape(settings.brand_name)}, {escape(name or 'путник')}!</b>\n\n"
        "Здесь блокировки исчезают, как свет за горизонтом событий.\n\n"
        f"{e('zap')} <b>Быстро</b> — серверы в Европе, канал 1 Гбит/с\n"
        f"{e('shield')} <b>Не блокируется</b> — VLESS Reality, трафик выглядит как обычный сайт\n"
        f"{e('globe')} <b>Свои сайты напрямую</b> — банки, Госуслуги и игры работают без выключения VPN\n"
        f"{e('phone')} <b>До {settings.device_limit} устройств</b> — iPhone, Android, Windows, macOS\n\n"
        + (f"{e('gift')} Первые <b>{settings.trial_days} дня бесплатно</b> — без карты и обязательств.\n\n"
           if settings.trial_days > 0 else "")
        + f"Выбери действие {e('down')}"
    )


def profile(user, active: bool) -> str:
    lines = [f"{e('user')} <b>Моя подписка</b>\n"]
    if active:
        lines.append(f"Статус: {e('ok')} активна до <b>{fmt_date(user.expire_at)}</b>")
        lines.append(f"Осталось дней: <b>{days_left(user.expire_at)}</b>")
        lines.append(f"Устройств: до {settings.device_limit}\n")
        lines.append(f"{e('key')} Ссылка-подписка (нажми, чтобы скопировать):")
        lines.append(f"<code>{escape(user.sub_url or '')}</code>")
    elif user.expire_at:
        lines.append(f"Статус: {e('no')} истекла {fmt_date(user.expire_at)}")
        lines.append("Продли подписку — ссылка останется прежней.")
    else:
        lines.append("Подписки пока нет.")
    return "\n".join(lines)


def tariffs() -> str:
    rows = [f"{e('card')} <b>Тарифы</b>\n", f"Все тарифы: безлимитный трафик, до {settings.device_limit} устройств.\n"]
    base = settings.plan_list[0]
    for p in settings.plan_list:
        per_month = round(p.rub / (p.days / 30))
        discount = round(100 - per_month * 100 / base.rub) if p is not base else 0
        tail = f"  (−{discount}%)" if discount > 0 else ""
        rows.append(f"• {p.title} — {p.rub} ₽ / {p.stars} ⭐{tail}")
    rows.append(f"\nВыбери срок {e('down')}")
    return "\n".join(rows)


def choose_method(plan: Plan) -> str:
    return f"Тариф: <b>{plan.title}</b>\n\nКак удобнее оплатить?"


def crypto_invoice(plan: Plan) -> str:
    return (
        f"{e('coin')} Счёт на <b>{plan.rub} ₽</b> в криптовалюте ({settings.cryptopay_assets.replace(',', ', ')}).\n\n"
        "1. Нажми «Оплатить» и заверши оплату в @CryptoBot\n"
        "2. Вернись сюда — подписка активируется автоматически в течение минуты\n\n"
        "Счёт действует 1 час."
    )


def paid(user, days: int) -> str:
    return (
        f"🎉 Оплата прошла! Добавлено <b>{days} дн.</b>\n"
        f"Подписка активна до <b>{fmt_date(user.expire_at)}</b>.\n\n"
        f"🔗 Твоя ссылка-подписка:\n<code>{escape(user.sub_url or '')}</code>\n\n"
        "Как подключиться — кнопка «📲 Инструкция» в меню."
    )


def trial_ok(user) -> str:
    return (
        f"{e('gift')} Пробный период на <b>{settings.trial_days} дн.</b> активирован!\n\n"
        f"🔗 Ссылка-подписка:\n<code>{escape(user.sub_url or '')}</code>\n\n"
        "Скопируй её и добавь в приложение — инструкция по кнопке ниже."
    )


HOWTO = (
    "📲 <b>Как подключиться</b>\n\n"
    "<b>1. Установи приложение</b>\n"
    "• iPhone / iPad / Mac: <a href='https://apps.apple.com/app/happ-proxy-utility/id6504287215'>Happ</a> "
    "или <a href='https://apps.apple.com/app/streisand/id6450534064'>Streisand</a>\n"
    "• Android: <a href='https://play.google.com/store/apps/details?id=com.happproxy'>Happ</a> "
    "или <a href='https://github.com/hiddify/hiddify-app/releases'>Hiddify</a>\n"
    "• Windows / Linux: <a href='https://github.com/hiddify/hiddify-app/releases'>Hiddify</a>\n\n"
    "<b>2. Скопируй ссылку</b> из раздела «👤 Моя подписка» (нажми на неё).\n\n"
    "<b>3. Добавь подписку:</b> в приложении нажми «+» → «Импорт из буфера обмена».\n\n"
    "<b>4. Подключись</b> — выбери любой сервер и нажми кнопку включения.\n\n"
    "Не работает? Обнови подписку в приложении или напиши в поддержку."
)


DISCONNECT_HELP = (
    "🔌 <b>VPN сам отключается?</b>\n\n"
    "Обычно это не сервер, а телефон: система закрывает VPN, чтобы освободить память "
    "(например, при запуске тяжёлых игр вроде Clash of Clans) или сэкономить батарею. "
    "Решение — включить автопереподключение.\n\n"
    "🍏 <b>iPhone / iPad</b>\n"
    "1. Настройки → Основные → VPN и управление устройством → VPN → ⓘ у Happ → "
    "включи <b>«Подключать по запросу»</b> (или то же в настройках Happ).\n"
    "2. Выключи «Режим энергосбережения».\n"
    "3. Оставь в Happ одну подписку — лишние удали.\n"
    "4. На телефоне выбирай сервер с пометкой <b>📱</b> — он расходует меньше памяти, и iPhone его не отключает. Обнови Happ до последней версии.\n\n"
    "🤖 <b>Android</b>\n"
    "1. Настройки → Сеть и интернет → VPN → ⚙️ у Happ → включи <b>«Постоянный VPN»</b>. "
    "«Блокировать соединения без VPN» <u>не</u> включай.\n"
    "2. Настройки → Приложения → Happ → Батарея → <b>«Без ограничений»</b>.\n"
    "3. Дополнительно по марке телефона:\n"
    "• <b>Xiaomi / Redmi / POCO</b>: у Happ включи «Автозапуск», «Контроль активности» → "
    "«Нет ограничений»; в недавних приложениях закрепи Happ замком.\n"
    "• <b>Samsung</b>: Обслуживание устройства → Батарея → Ограничения фоновой работы → "
    "добавь Happ в «Никогда не переходящие в спящий режим».\n"
    "• <b>Huawei / Honor</b>: Батарея → Запуск приложений → Happ → «Управлять вручную», включи все переключатели.\n\n"
    "После этого VPN будет сам включаться обратно. Не помогло — напиши в поддержку."
)

def referral(link: str, invited: int, paid_count: int) -> str:
    return (
        "👥 <b>Пригласи друга</b>\n\n"
        f"За каждого друга, который оплатит подписку, ты получишь <b>+{settings.referral_bonus_days} дн.</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: {invited} · оплатили: {paid_count}"
    )


def referral_bonus(days: int) -> str:
    return f"🎁 Твой друг оформил подписку — тебе начислено <b>+{days} дн.</b>!"


# Напоминания перед окончанием подписки: (код, за сколько до конца)
REMINDER_STAGES = [("24h", timedelta(hours=24)), ("12h", timedelta(hours=12)),
                   ("2h", timedelta(hours=2)), ("30m", timedelta(minutes=30))]
# Порядок стадий; старые коды "3d"/"1d" из прошлых версий приравнены к новым
REMINDER_RANK = {"": 0, "3d": 0, "1d": 1, "24h": 1, "12h": 2, "2h": 3, "30m": 4, "exp": 5}


def reminder_stage(left: timedelta) -> str:
    """Самая поздняя стадия, которая уже наступила ("" — рано напоминать)."""
    if left <= timedelta(0):
        return "exp"
    stage = ""
    for code, before in REMINDER_STAGES:
        if left <= before:
            stage = code
    return stage


def reminder(kind: str, user) -> str:
    when = fmt_date(user.expire_at)
    if kind == "24h":
        return (f"⏰ Подписка закончится через сутки — {when}.\n"
                "Продли заранее, чтобы VPN не отключился. Ссылка и настройки останутся прежними.")
    if kind == "12h":
        return f"⏰ До конца подписки 12 часов ({when}). Продли сейчас — это займёт минуту."
    if kind == "2h":
        return f"⚠️ Подписка закончится через 2 часа ({when}). После этого VPN перестанет работать."
    if kind == "30m":
        return f"🔴 Через 30 минут VPN отключится ({when}). Продли подписку, чтобы не потерять доступ."
    return "❌ Подписка закончилась, VPN отключён. Продли её — все настройки в приложении сохранятся."
