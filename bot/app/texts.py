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
        f"{e('logo')} <b>Привет, {escape(name or 'друг')}! Это {escape(settings.brand_name)}</b>\n\n"
        "Быстрый и удобный VPN для телефона и компьютера.\n\n"
        f"{e('zap')} <b>Быстро</b> — серверы в Европе\n"
        f"{e('lock')} <b>Безопасно</b> — соединение шифруется, даже в общественном Wi‑Fi\n"
        f"{e('globe')} <b>Удобно</b> — российские сайты, банки и игры работают как обычно, выключать VPN не нужно\n"
        f"{e('phone')} <b>До {settings.device_limit} устройств</b> на одну подписку\n"
        + (f"\n{e('gift')} <b>{settings.trial_days} дня бесплатно</b> — без привязки карты."
           if settings.trial_days > 0 else "")
    )


def about() -> str:
    return (
        f"{e('bot')} <b>Что умеет бот</b>\n\n"
        f"{e('gift')} Дать попробовать VPN бесплатно\n"
        f"{e('card')} Принять оплату и продлить подписку\n"
        f"{e('book')} Показать, как подключиться на iPhone, Android и компьютере\n"
        f"{e('user')} Показать, сколько дней осталось, и выдать ссылку для приложения\n"
        f"{e('refresh')} Сбросить устройства, если хочешь подключить новые\n"
        f"{e('clock')} Напомнить, что подписка скоро закончится\n"
        f"{e('friends')} Начислить бонусные дни за приглашённых друзей\n"
        f"{e('support')} Связать с поддержкой, если что-то не получается"
    )


def service() -> str:
    cheapest = min(round(p.rub / (p.days / 30)) for p in settings.plan_list)
    return (
        f"{e('logo')} <b>{escape(settings.brand_name)}</b>\n"
        "Быстрый и удобный VPN для телефона и компьютера.\n\n"
        f"{e('zap')} <b>Скорость</b> — серверы в Европе, приложение само выбирает свободный\n"
        f"{e('lock')} <b>Безопасность</b> — соединение шифруется, даже в общественном Wi‑Fi\n"
        f"{e('globe')} <b>Без лишних настроек</b> — российские сайты, банки и игры работают как обычно\n"
        f"{e('phone')} <b>До {settings.device_limit} устройств</b> — iPhone, Android, Windows, macOS\n"
        f"{e('card')} <b>От {cheapest} ₽ в месяц</b> — оплата Telegram Stars или криптовалютой\n"
        f"{e('support')} <b>Поддержка</b> — отвечаем прямо в Telegram\n\n"
        "Тарифы, инструкции и ответы на частые вопросы — на нашем сайте."
    )


def support() -> str:
    return (
        f"{e('support')} <b>Поддержка</b>\n\n"
        "Не получается подключиться или есть вопрос по оплате? Напиши нам — поможем разобраться.\n\n"
        "Чтобы ответили быстрее, сразу опиши:\n"
        f"{e('phone')} какое у тебя устройство (iPhone, Android, компьютер)\n"
        f"{e('info')} что именно не работает — можно приложить скриншот"
    )


def profile(user, active: bool) -> str:
    lines = [f"{e('user')} <b>Моя подписка</b>\n"]
    if active:
        lines.append(f"{e('ok')} Работает до <b>{fmt_date(user.expire_at)}</b>")
        lines.append(f"{e('calendar')} Осталось дней: <b>{days_left(user.expire_at)}</b>")
        lines.append(f"{e('phone')} Устройств: до {settings.device_limit}\n")
        lines.append(f"{e('key')} Твоя ссылка для приложения — нажми, чтобы скопировать:")
        lines.append(f"<code>{escape(user.sub_url or '')}</code>")
    elif user.expire_at:
        lines.append(f"{e('no')} Закончилась {fmt_date(user.expire_at)}")
        lines.append("Продли подписку — ссылка и настройки останутся прежними.")
    else:
        lines.append("Подписки пока нет. Попробуй бесплатно или выбери тариф.")
    return "\n".join(lines)


def tariffs() -> str:
    rows = [f"{e('card')} <b>Тарифы</b>\n", f"Без ограничений по трафику, до {settings.device_limit} устройств.\n"]
    base = settings.plan_list[0]
    for p in settings.plan_list:
        per_month = round(p.rub / (p.days / 30))
        discount = round(100 - per_month * 100 / base.rub) if p is not base else 0
        tail = f"  (выгода {discount}%)" if discount > 0 else ""
        rows.append(f"• {p.title} — {p.rub} ₽ / {p.stars} ⭐{tail}")
    rows.append("\nВыбери срок:")
    return "\n".join(rows)


def choose_method(plan: Plan) -> str:
    return f"Тариф: <b>{plan.title}</b>\n\nКак удобнее оплатить?"


def crypto_invoice(plan: Plan) -> str:
    return (
        f"{e('coin')} Счёт на <b>{plan.rub} ₽</b> в криптовалюте ({settings.cryptopay_assets.replace(',', ', ')}).\n\n"
        "1. Нажми «Оплатить» и оплати в @CryptoBot.\n"
        "2. Вернись сюда — подписка включится сама в течение минуты.\n\n"
        "Счёт действует 1 час."
    )


def paid(user, days: int) -> str:
    return (
        f"{e('ok')} <b>Оплата прошла!</b> Добавлено {days} дн.\n"
        f"Подписка работает до <b>{fmt_date(user.expire_at)}</b>.\n\n"
        f"{e('key')} Твоя ссылка для приложения:\n<code>{escape(user.sub_url or '')}</code>\n\n"
        "Как подключиться — кнопка «Инструкция» в меню."
    )


def trial_ok(user) -> str:
    return (
        f"{e('gift')} <b>Готово! {settings.trial_days} дня бесплатно.</b>\n\n"
        f"{e('key')} Твоя ссылка для приложения:\n<code>{escape(user.sub_url or '')}</code>\n\n"
        "Нажми на ссылку, чтобы скопировать, и добавь её в приложение Happ. Как это сделать — кнопка «Инструкция»."
    )


_IOS_URL = "https://apps.apple.com/app/happ-proxy-utility/id6504287215"

def howto() -> str:
    return (
        f"{e('book')} <b>Как подключиться — 3 шага</b>\n\n"
        "<b>1. Скачай приложение Happ</b>\n"
        f"• iPhone, iPad, Mac — <a href='{escape(settings.happ_ios_ru_url or _IOS_URL, quote=True)}'>App Store</a>. "
        "Не находится? Нажми кнопку ниже.\n"
        "• Android — <a href='https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk'>скачай Happ.apk</a>, "
        "открой файл и нажми «Установить».\n"
        "• Windows — <a href='https://github.com/Happ-proxy/happ-desktop/releases'>Happ для Windows</a>\n\n"
        "<b>2. Скопируй ссылку</b> — в разделе «Моя подписка» нажми на неё.\n\n"
        "<b>3. Добавь её в Happ</b> — нажми «+» → «Вставить из буфера», затем большую кнопку включения.\n\n"
        "На телефоне выбирай сервер со значком 📱.\n\n"
        "<b>VPN выключается сам?</b>\n"
        "• iPhone: Настройки → Основные → VPN → ⓘ у Happ → «Подключать по запросу».\n"
        "• Android: Настройки → VPN → ⚙️ у Happ → «Постоянный VPN».\n\n"
        "Что-то не работает — обнови подписку в Happ (потяни список серверов вниз) или напиши в поддержку."
    )


def appstore_help() -> str:
    return (
        f"{e('apple')} <b>Happ не находится в App Store?</b>\n\n"
        "Значит, в App Store твоей страны его сейчас нет. Его можно скачать, сменив страну в Apple ID:\n\n"
        "1. Настройки → твоё имя → <b>Медиаматериалы и покупки</b> → «Просмотреть» → "
        "<b>Страна или регион</b> → «Изменить».\n"
        "2. Выбери, например, <b>Казахстан</b> или <b>США</b> и прими условия.\n"
        "3. Способ оплаты — <b>«Нет»</b>. Адрес и телефон — любые в этой стране.\n"
        f"4. Открой <a href='{_IOS_URL}'>Happ в App Store</a> и установи.\n\n"
        "Потом страну можно вернуть обратно — приложение останется на телефоне.\n\n"
        "Не получается сменить (мешают подписки Apple или деньги на балансе)? Напиши в поддержку — поможем."
    )


def disconnect_help() -> str:
    return (
        f"{e('plug')} <b>VPN выключается сам?</b>\n\n"
        "Обычно его закрывает телефон, чтобы сэкономить батарею или память. Включи автоподключение:\n\n"
        "• <b>iPhone</b>: Настройки → Основные → VPN и управление устройством → VPN → ⓘ у Happ → "
        "«Подключать по запросу». На телефоне выбирай сервер со значком 📱.\n"
        "• <b>Android</b>: Настройки → Сеть и интернет → VPN → ⚙️ у Happ → «Постоянный VPN»; "
        "Приложения → Happ → Батарея → «Без ограничений».\n\n"
        "Не помогло — напиши в поддержку."
    )


def referral(link: str, invited: int, paid_count: int) -> str:
    return (
        f"{e('friends')} <b>Пригласи друга</b>\n\n"
        f"За каждого друга, который оплатит подписку, ты получишь <b>+{settings.referral_bonus_days} дн.</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: {invited} · оплатили: {paid_count}"
    )


def referral_bonus(days: int) -> str:
    return f"{e('gift')} Твой друг оформил подписку — тебе начислено <b>+{days} дн.</b>!"


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
                "Продли заранее, чтобы VPN не выключился. Ссылка и настройки останутся прежними.")
    if kind == "12h":
        return f"⏰ До конца подписки 12 часов ({when}). Продли сейчас — это займёт минуту."
    if kind == "2h":
        return f"⚠️ Подписка закончится через 2 часа ({when}). Потом VPN перестанет работать."
    if kind == "30m":
        return f"🔴 Через 30 минут VPN выключится ({when}). Продли подписку, чтобы он продолжил работать."
    return "❌ Подписка закончилась, VPN выключен. Продли её — настройки в приложении сохранятся."
