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


def bot_description() -> str:
    """Текст «Что умеет этот бот?» — его видят в пустом чате до нажатия «Старт» (лимит Telegram 512 символов)."""
    trial = settings.trial_days
    lines = [
        f"{settings.brand_name} — быстрый и удобный VPN для телефона и компьютера.",
        "",
        "• Канал 1 Гбит/с, YouTube в 8K без зависаний",
        "• ChatGPT, Gemini, Claude и другие ИИ-сервисы",
        "• Российские сайты и приложения дружат с нашим VPN",
        f"• Безлимитный трафик, до {settings.device_limit} устройств",
        "• Подключение за минуту и живая поддержка в Telegram",
        "",
        (f"Попробуйте бесплатно — {trial} {plural(trial, 'день', 'дня', 'дней')} без привязки карты ↓"
         if trial > 0 else "Нажмите «Старт», чтобы начать ↓"),
    ]
    return "\n".join(lines)[:512]


def bot_short_description() -> str:
    """Короткое описание в профиле бота (лимит 120 символов)."""
    return ("VPN с YouTube в 8K и всеми ИИ-сервисами. RU-сайты и приложения дружат с нашим VPN."
            + (f" {settings.trial_days} дня бесплатно." if settings.trial_days > 0 else ""))[:120]


def menu_hint() -> str:
    return f"{e('down')} Кнопка «Меню» внизу всегда вернёт тебя на главный экран, а «Открыть» слева — откроет приложение."


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def title(icon: str, text: str) -> str:
    """Заголовок экрана: иконка + жирный подчёркнутый текст (единый стиль всего бота)."""
    return f"{e(icon)} <b><u>{text}</u></b>"


def welcome(name: str | None) -> str:
    return (
        f"{e('logo')} <b><i>Добро пожаловать в {escape(settings.brand_name)}, {escape(name or 'друг')}!</i></b> {e('logo')}\n\n"
        f"{e('zap')} <b>Быстро</b> — канал 1 Гбит/с\n"
        f"{e('play')} <b>YouTube в 8K</b> — без зависаний и буферизации\n"
        f"{e('ai')} <b>Все ИИ-сервисы</b> — ChatGPT, Gemini, Claude и другие\n"
        f"{e('globe')} <b>RU сайты и приложения</b> дружат с нашим VPN – Банки/Карты/Игры\n"
        f"{e('shield')} <b>Надёжно</b> — защищённое соединение\n"
        f"{e('infinity')} <b>Безлимитный трафик</b> — смотри и качай сколько угодно\n"
        f"{e('refresh')} <b>Умное подключение</b> — сервер нагружен? переключим на свободный\n"
        f"{e('phone')} <b>До {settings.device_limit} устройств</b> одновременно\n"
        f"{e('support')} <b>Живая поддержка</b> прямо в Telegram\n"
        + (f"\n{e('gift')} <i>Первые <b>{settings.trial_days} {plural(settings.trial_days, 'день', 'дня', 'дней')} бесплатно</b> "
           "без привязки карты</i>" if settings.trial_days > 0 else "")
    )


def about() -> str:
    return (
        f"{e('bot')} <b>Что умеет бот</b>\n\n"
        f"{e('gift')} Даст попробовать VPN бесплатно\n"
        f"{e('card')} Примет оплату и продлит подписку\n"
        f"{e('book')} Покажет, как подключиться на твоём устройстве\n"
        f"{e('clock')} Напомнит о скором окончании подписки\n"
        f"{e('user')} Выдаст ссылку для приложения\n"
        f"{e('refresh')} Сбросит устройства, если хочешь подключить новые\n"
        f"{e('friends')} Начислит бонусные дни за приглашённых друзей\n"
        f"{e('support')} Свяжет с поддержкой, если что-то не получается"
    )


def service() -> str:
    cheapest = min(round(p.rub / (p.days / 30)) for p in settings.plan_list)
    return (
        f"{title('logo', escape(settings.brand_name))}\n\n"
        "<i>Быстрый и удобный VPN для телефона и компьютера.</i>\n\n"
        f"{e('zap')} <b>Скорость</b> — канал 1 Гбит/с, YouTube в 8K без зависаний\n"
        f"{e('ai')} <b>ИИ-сервисы</b> — ChatGPT, Gemini, Claude и другие\n"
        f"{e('globe')} <b>Без лишних настроек</b> — российские сайты и приложения дружат с нашим VPN\n"
        f"{e('shield')} <b>Надёжно</b> — защищённое соединение, сервер выбирается автоматически\n"
        f"{e('phone')} <b>До {settings.device_limit} устройств</b> — iPhone, Android, Windows, macOS\n"
        f"{e('card')} <b>От {cheapest} ₽ в месяц</b> — оплата "
        + ("картой, СБП, " if settings.card_enabled else "") + "Telegram Stars или криптовалютой\n"
        f"{e('support')} <b>Поддержка</b> — отвечаем прямо в Telegram\n\n"
        "Тарифы, инструкции и ответы на частые вопросы — на нашем сайте."
    )


def support() -> str:
    return (
        f"{title('support', 'Поддержка')}\n\n"
        "Не получается подключиться или есть вопрос по оплате? Напиши нам — поможем разобраться.\n\n"
        "Чтобы ответили быстрее, сразу опиши:\n"
        f"{e('phone')} какое у тебя устройство (iPhone, Android, компьютер)\n"
        f"{e('info')} что именно не работает — можно приложить скриншот"
    )


def profile(user, active: bool) -> str:
    devices = getattr(user, "device_limit", None) or settings.device_limit  # реальный лимит из панели
    lines = [title("user", "Моя подписка") + "\n"]
    if active:
        lines.append(f"Статус: {e('ok')} Активна")
        lines.append(f"до <b><i>{fmt_date(user.expire_at)}</i></b>")
        lines.append(f"Осталось дней: <b><i>{days_left(user.expire_at)}</i></b>")
        lines.append(f"Устройства: до <b><i>{devices}</i></b>\n")
        lines.append(f"{e('link')} Ссылка-подписка")
        lines.append(f'<pre><code class="language-копировать">{escape(user.sub_url or "")}</code></pre>')
    elif user.expire_at:
        lines.append(f"Статус: {e('no')} Закончилась")
        lines.append(f"<b><i>{fmt_date(user.expire_at)}</i></b>\n")
        lines.append("<i>Продли подписку — ссылка и настройки останутся прежними.</i>")
    else:
        lines.append("<i>Подписки пока нет. Попробуй бесплатно или выбери тариф.</i>")
    return "\n".join(lines)


def revoke_ask() -> str:
    devices = ("\n• все подключённые устройства сбросятся — на своих подключишь заново"
               if settings.revoke_reset_devices else "")
    return (
        f"{title('lock', 'Новая ссылка-подписка')}\n\n"
        "Если ссылка попала к чужим людям — замени её. Что произойдёт:\n"
        "<blockquote>• старая ссылка и всё, что по ней настроено, перестанут работать"
        f"{devices}\n"
        "• срок подписки не изменится</blockquote>\n"
        "<i>После замены удали старую подписку в Happ и добавь новую ссылку на своих устройствах.</i>"
    )


def revoke_done(user) -> str:
    return (
        f"{title('ok', 'Ссылка заменена')}\n\n"
        "Старая ссылка больше не работает.\n\n"
        f"{e('link')} Новая ссылка-подписка\n"
        f'<pre><code class="language-копировать">{escape(user.sub_url or "")}</code></pre>\n\n'
        "<blockquote><b>Что сделать на своих устройствах:</b>\n"
        "1. В Happ удали старую подписку\n"
        "2. Добавь новую — кнопкой «Открыть приложение» или вставь ссылку выше</blockquote>\n"
        "<i>Никому не пересылай ссылку — по ней подключаются к твоей подписке.</i>"
    )


def tariffs(promo=None) -> str:
    from .promo import price
    head = [title("card", "Тарифы") + "\n", f"<i>Безлимитный трафик, подключение до {settings.device_limit} устройств</i>\n"]
    if promo:
        head.append(f"{e('ticket')} Промокод <b>{escape(promo.code)}</b>: скидка <b>{promo.percent}%</b> на любой тариф\n")
    base = settings.plan_list[0]
    rows = []
    for p in settings.plan_list:
        per_month = round(p.rub / (p.days / 30))
        discount = round(100 - per_month * 100 / base.rub) if p is not base else 0
        tail = f" <i>(-{discount}%)</i>" if discount > 0 else ""
        rub, stars = price(p, promo)
        old = f"<s>{p.rub} ₽</s> " if promo else ""
        rows.append(f"• {p.title} — {old}{rub} ₽ / {stars} {e('star')}{tail}")
    return "\n".join(head) + "<blockquote>" + "\n".join(rows) + "</blockquote>"


def promo_ask() -> str:
    return (f"{title('ticket', 'Промокод')}\n\n"
            "Отправь промокод сообщением — скидка применится ко всем тарифам.")


def legal_note() -> str:
    if not settings.miniapp_url:
        return ""
    return (f"\n\n<i>Оплачивая, ты принимаешь <a href='{settings.site_url('terms')}'>Пользовательское соглашение</a> "
            f"и <a href='{settings.site_url('privacy')}'>Политику конфиденциальности</a>.</i>")


def choose_method(plan: Plan, promo=None) -> str:
    from .promo import price
    rub, _ = price(plan, promo)
    tail = f"\nК оплате: <s>{plan.rub} ₽</s> <b>{rub} ₽</b> — промокод {escape(promo.code)}, −{promo.percent}%" if promo else ""
    return f"{title('card', 'Оплата')}\n\nТариф: <b>{plan.title}</b>{tail}\n\n<i>Как удобнее оплатить?</i>" + legal_note()


def card_invoice(plan: Plan, rub: int | None = None) -> str:
    return (
        f"{title('card', 'Оплата картой или СБП')}\n\n"
        f"Тариф: <b>{plan.title}</b>\nК оплате: <b><i>{rub or plan.rub} ₽</i></b>\n\n"
        "<blockquote><b>1.</b> Нажми «Оплатить» — откроется защищённая страница оплаты.\n"
        "<b>2.</b> Оплати картой любого банка или через СБП.\n"
        "<b>3.</b> Вернись в бот — подписка включится сама в течение минуты.</blockquote>\n\n"
        "<i>Счёт действует 2 часа. Если что-то пошло не так — нажми «Я оплатил — проверить» или напиши в поддержку.</i>"
        + legal_note()
    )


def crypto_invoice(plan: Plan, rub: int | None = None) -> str:
    return (
        f"{e('coin')} Счёт на <b>{rub or plan.rub} ₽</b> в криптовалюте ({settings.cryptopay_assets.replace(',', ', ')}).\n\n"
        "1. Нажми «Оплатить» и оплати в @CryptoBot.\n"
        "2. Вернись сюда — подписка включится сама в течение минуты.\n\n"
        "Счёт действует 1 час."
    )


def paid(user, days: int) -> str:
    return (
        f"{title('ok', 'Оплата прошла!')}\n\n"
        f"Добавлено <b><i>{days} {plural(days, 'день', 'дня', 'дней')}</i></b>\n"
        f"Подписка активна до <b><i>{fmt_date(user.expire_at)}</i></b>\n\n"
        f"{e('link')} Ссылка-подписка\n"
        f'<pre><code class="language-копировать">{escape(user.sub_url or "")}</code></pre>\n\n'
        "<i>Как подключиться — кнопка «Инструкция» в меню.</i>"
    )


def trial_ok(user) -> str:
    return (
        f"{title('gift', 'Пробный период активирован!')}\n\n"
        f"<b><i>{settings.trial_days} {plural(settings.trial_days, 'день', 'дня', 'дней')}</i></b> бесплатно — без привязки карты.\n\n"
        f"{e('link')} Ссылка-подписка\n"
        f'<pre><code class="language-копировать">{escape(user.sub_url or "")}</code></pre>\n\n'
        "<i>Скопируй ссылку и добавь её в приложение Happ. Как это сделать — кнопка «Инструкция».</i>"
    )


_IOS_URL = "https://apps.apple.com/app/happ-proxy-utility/id6504287215"

def howto() -> str:
    return (
        f"{title('book', 'Как подключиться — 3 шага')}\n\n"
        "<b>1. Скачай приложение Happ</b>\n"
        "<blockquote>"
        f"• iPhone, iPad, Mac — <a href='{escape(settings.happ_ios_ru_url or _IOS_URL, quote=True)}'>App Store</a>. "
        "Не находится? Нажми кнопку ниже.\n"
        "• Android — <a href='https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk'>скачай Happ.apk</a>, "
        "открой файл и нажми «Установить».\n"
        "• Windows — <a href='https://github.com/Happ-proxy/happ-desktop/releases'>Happ для Windows</a>"
        "</blockquote>\n\n"
        "<b>2. Скопируй ссылку</b> — в разделе «Моя подписка» нажми на неё.\n\n"
        "<b>3. Добавь её в Happ</b> — нажми «+» → «Вставить из буфера», затем большую кнопку включения.\n\n"
        "<i>На телефоне выбирай сервер со значком «📱»</i>\n\n"
        "<b>VPN выключается сам?</b>\n"
        "<blockquote>"
        "• iPhone: Настройки → Основные → VPN → ⓘ у Happ → «Подключать по запросу».\n\n"
        f"• Android: Настройки → VPN → {e('settings')} у Happ → «Постоянный VPN»."
        "</blockquote>\n\n"
        "Что-то не работает — обнови подписку в Happ (потяни список серверов вниз) или напиши в поддержку."
    )


def appstore_help() -> str:
    return (
        f"{title('apple', 'Happ недоступен в App Store?')}\n\n"
        "В российском App Store «Happ» удалили — его можно скачать, сменив регион Apple ID.\n\n"
        "<blockquote><b>1.</b> Настройки → твоё имя → <b>Медиаматериалы и покупки</b> → «Просмотреть» → "
        "<b>Страна или регион</b> → «Изменить страну или регион».\n\n"
        "<b>2.</b> Выбери другую страну — например, <b>Казахстан</b> или <b>США</b> — и прими условия.\n\n"
        "<b>3.</b> Способ оплаты — <b>«Нет»</b>.\n"
        "Адрес и телефон — любые в этой стране (подойдёт адрес любого отеля из поиска).\n\n"
        f"<b>4.</b> Открой <a href='{_IOS_URL}'>Happ в App Store</a> и установи.</blockquote>\n\n"
        "Регион потом можно вернуть на Россию — «Happ» останется на телефоне, "
        "но обновления будут приходить, только пока выбран другой регион.\n\n"
        f"{e('alert')} <i>Сменить регион не получится, если есть активные подписки Apple или остаток денег "
        "на балансе Apple ID — сначала отмени подписки или потрать остаток.</i>\n\n"
        "Не получается — напиши в поддержку, поможем."
    )


def disconnect_help() -> str:
    return (
        f"{title('plug', 'VPN выключается сам?')}\n\n"
        "Обычно его закрывает телефон, чтобы сэкономить батарею или память. Включи автоподключение:\n\n"
        "• <b>iPhone</b>: Настройки → Основные → VPN и управление устройством → VPN → ⓘ у Happ → "
        "«Подключать по запросу». На телефоне выбирай сервер со значком 📱.\n"
        f"• <b>Android</b>: Настройки → Сеть и интернет → VPN → {e('settings')} у Happ → «Постоянный VPN»; "
        "Приложения → Happ → Батарея → «Без ограничений».\n\n"
        "Не помогло — напиши в поддержку."
    )


def referral(link: str, invited: int, paid_count: int) -> str:
    d = settings.referral_bonus_days
    return (
        f"{title('friends', 'Пригласи друга')}\n\n"
        f"За каждого друга, который оплатит подписку, ты получишь <b>+{d} {plural(d, 'день', 'дня', 'дней')}</b>\n\n"
        f"{e('link')} Твоя ссылка:\n<blockquote><code>{escape(link)}</code></blockquote>\n\n"
        f"Приглашено: {invited}\nОплатили: {paid_count}"
    )


def referral_bonus(days: int) -> str:
    return f"{e('gift')} Твой друг оформил подписку — тебе начислено <b>+{days} дн.</b>!"


def _days(d: int) -> str:
    return f"{d} {plural(d, 'день', 'дня', 'дней')}"


# ---------- бонус за подписку на канал ----------

def channel_button() -> str:
    return f"+{_days(settings.channel_bonus_days)} за подписку на канал"


def channel_offer() -> str:
    d = settings.channel_bonus_days
    return (
        f"{title('gift', f'+{_days(d)} бесплатно')}\n\n"
        f"Подпишись на наш Telegram-канал и получи <b><i>{_days(d)}</i></b> подписки в подарок.\n\n"
        "<blockquote>"
        f"{e('zap')} Новости сервиса и новые серверы\n"
        f"{e('ticket')} Промокоды и скидки — только для подписчиков\n"
        f"{e('info')} Если что-то сломается — первыми узнаете от нас"
        "</blockquote>\n\n"
        "<b>Как получить:</b>\n"
        "1. Нажми «Подписаться на канал»\n"
        "2. Вернись сюда и нажми «Я подписался»\n\n"
        "<i>Бонус можно получить один раз.</i>"
    )


def channel_gate(name: str | None) -> str:
    d = settings.channel_bonus_days
    return (
        f"{e('logo')} <b><i>Добро пожаловать в {escape(settings.brand_name)}, {escape(name or 'друг')}!</i></b> {e('logo')}\n\n"
        "Чтобы начать, подпишись на наш Telegram-канал"
        + (f" — и получи <b><i>{_days(d)}</i></b> подписки в подарок." if d > 0 else ".") + "\n\n"
        "<blockquote>"
        f"{e('zap')} Новости сервиса и новые серверы\n"
        f"{e('ticket')} Промокоды и скидки — только для подписчиков\n"
        f"{e('info')} Если что-то сломается — первыми узнаете от нас"
        "</blockquote>\n\n"
        "<b>Как начать:</b>\n"
        "1. Нажми «Подписаться на канал»\n"
        "2. Вернись сюда и нажми «Я подписался»"
    )


def channel_passed() -> str:  # всплывающее окно после КПП
    d = settings.channel_bonus_days
    return (f"Подписка подтверждена! Тебе начислено +{_days(d)} — подробности в «Моя подписка»."
            if d > 0 else "Подписка подтверждена — добро пожаловать!")


def channel_not_member() -> str:  # всплывающее окно, до 200 символов
    return "Пока не вижу тебя в канале. Подпишись и нажми «Я подписался» ещё раз."


def channel_ok(user) -> str:
    d = settings.channel_bonus_days
    return (
        f"{title('gift', 'Бонус начислен!')}\n\n"
        f"Спасибо за подписку! Тебе добавлено <b><i>+{_days(d)}</i></b>.\n"
        f"Подписка активна до <b><i>{fmt_date(user.expire_at)}</i></b>\n\n"
        f"{e('link')} Ссылка-подписка\n"
        f'<pre><code class="language-копировать">{escape(user.sub_url or "")}</code></pre>\n\n'
        "<i>Если Happ ещё не настроен — нажми «Инструкция».</i>"
    )


# ---------- отзывы ----------

def review_ask() -> str:
    return (
        f"{title('star', 'Оставить отзыв')}\n\n"
        f"Нам важно твоё мнение! Напиши <b>одним сообщением</b>, что нравится в {escape(settings.brand_name)} "
        "и что стоит улучшить.\n\n"
        "<blockquote>"
        f"{e('zap')} Как скорость и стабильность\n"
        f"{e('phone')} Удобно ли подключаться\n"
        f"{e('info')} Чего не хватает"
        "</blockquote>\n\n"
        "<i>Можно приложить скриншот, видео или голосовое — просто отправь его сюда.</i>"
    )


def review_thanks() -> str:
    return (
        f"{title('star', 'Спасибо за отзыв!')}\n\n"
        "Мы читаем каждый отзыв лично. Если в нём вопрос или проблема — поддержка напишет тебе.\n\n"
        f"<i>Захочешь дополнить — кнопка «Оставить отзыв» есть в меню.</i>"
    )


def review_reminder() -> str:
    return (
        f"{title('star', f'Как тебе {escape(settings.brand_name)}?')}\n\n"
        "Расскажи, всё ли устраивает — скорость, стабильность, подключение. "
        "Отзыв займёт минуту и очень поможет нам стать лучше.\n\n"
        "<i>Нажми кнопку ниже и напиши пару слов.</i>"
    )


def review_admin_header(user, active: bool) -> str:
    who = escape(user.first_name or "без имени")
    if user.username:
        who += f" (@{escape(user.username)})"
    sub = f"активна до {fmt_date(user.expire_at)}" if active else ("закончилась" if user.expire_at else "не было")
    return f"{e('star')} <b>Новый отзыв</b> от {who}\nID <code>{user.tg_id}</code> · подписка: {sub}"


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
        return (f"{e('clock')} Подписка закончится через сутки — {when}.\n"
                "Продли заранее, чтобы VPN не выключился. Ссылка и настройки останутся прежними.")
    if kind == "12h":
        return f"{e('clock')} До конца подписки 12 часов ({when}). Продли сейчас — это займёт минуту."
    if kind == "2h":
        return f"{e('alert')} Подписка закончится через 2 часа ({when}). Потом VPN перестанет работать."
    if kind == "30m":
        return f"{e('alert')} Через 30 минут VPN выключится ({when}). Продли подписку, чтобы он продолжил работать."
    return f"{e('no')} Подписка закончилась, VPN выключен. Продли её — настройки в приложении сохранятся."
