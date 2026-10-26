from dataclasses import dataclass
from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class Plan:
    code: str
    days: int
    rub: int
    stars: int

    @property
    def title(self) -> str:
        names = {30: "1 месяц", 90: "3 месяца", 180: "6 месяцев", 365: "12 месяцев"}
        return names.get(self.days, f"{self.days} дн.")


TEST_PLAN = Plan(code="test", days=1, rub=0, stars=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    # Токен старого бота после переезда: он будет отвечать «мы переехали» (см. legacy.py). Пусто — выключено.
    legacy_bot_token: str = ""
    admin_ids: str = ""
    support_username: str = ""
    brand_name: str = "VPN"
    miniapp_url: str = ""
    webapp_port: int = 8080
    # Надпись на кнопке мини-аппа слева от поля ввода
    menu_button_text: str = "Открыть"

    panel_url: str = "http://remnawave:3000"
    panel_token: str
    panel_squad_uuids: str = ""
    device_limit: int = 3
    traffic_limit_gb: int = 0
    # Хосты с этим тегом бот сам наполняет адресами исправных нод (см. balancer.py). Пусто — выключено.
    auto_host_tag: str = "AUTO"
    # Взвешенный балансировщик: учитывать загрузку нод (онлайн на ноде / её вес). false — поровну, как раньше.
    balance_by_load: bool = True
    # Вес нод для балансировщика: "FR-1:2,GE-1:1" — FR-1 мощнее вдвое. Имя как в панели; не указана — вес 1.
    node_weights: str = ""
    # Сервер(ы)-выход для YouTube (host:port через запятую): бот раз в минуту проверяет, что отвечает,
    # и шлёт админам 🔴/🟢 (см. exitwatch.py). Пусто — проверка выключена.
    yt_exits: str = "217.149.26.98:8388"
    # Мосты в России: бот читает с них проверку нод (HAProxy, порт 8404) и убирает из подписки ноды,
    # которые не работают из России (см. bridgewatch.py). Пусто — проверка выключена.
    bridges: str = "77.91.95.53,193.247.73.20"
    bridge_stats_port: int = 8404
    # Прятать из подписки хосты стран (без тега AUTO), если их нода лежит или не работает из России.
    # Вернутся сами, когда нода оживёт. false — страны всегда видны.
    hide_dead_hosts: bool = True

    # Бонус за подписку на Telegram-канал: @имя или ссылка t.me/... Пусто — кнопки нет.
    # Бот должен быть администратором канала, иначе Telegram не даст проверить подписку.
    channel_username: str = ""
    channel_bonus_days: int = 3
    # КПП: новый человек (ещё не было подписки) при /start сначала видит экран «подпишись на канал»,
    # меню — только после проверки подписки. false — вместо КПП обычная кнопка бонуса в меню.
    channel_gate: bool = True
    # Отзывы: кому пересылать (Telegram ID через запятую; пусто — всем ADMIN_IDS).
    # Получатель должен хотя бы раз нажать /start в боте, иначе бот не сможет ему написать.
    review_to: str = ""
    # Напоминание оставить отзыв: раз в REVIEW_REMIND_DAYS дней, первое — через REVIEW_FIRST_DAYS
    # после регистрации; только тем, у кого была подписка. 0 — напоминания выключены.
    review_remind_days: int = 7
    review_first_days: int = 3
    # Фирменные иконки на кнопках меню (нужен Telegram Premium у владельца бота). false — обычные эмодзи.
    button_icons: bool = True
    # Фирменный пак эмодзи для кнопок и текстов (имя или ссылка t.me/addemoji/...). Пусто — свой пак бота.
    emoji_pack: str = "WhiteHoleVPN_by_TgEmodziBot"
    # Ручное соответствие иконок номерам в паке: "logo=1,zap=5" (номера показывает /emoji ИМЯ_ПАКА)
    emoji_map: str = ""

    # Ссылка на Happ в российском App Store, когда он там есть (например, «Happ - Proxy Utility+»).
    # Пусто — в инструкции для iPhone только обычный Happ + смена региона.
    happ_ios_ru_url: str = ""

    # Реквизиты для юридических документов на сайте (Пользовательское соглашение, Политика конфиденциальности)
    seller_name: str = ""       # ФИО самозанятого
    seller_inn: str = ""        # ИНН
    contact_email: str = ""     # e-mail для обращений
    refund_full_days: int = 3   # полный возврат в течение N дней после первой оплаты

    plans: str = "30:199:150,90:549:400,180:999:750,365:1790:1350"
    trial_days: int = 3
    # «Заменить ссылку»: не чаще раза в N минут на пользователя; сбрасывать ли заодно устройства
    revoke_cooldown_min: int = 10
    revoke_reset_devices: bool = True
    # Рефералка: за пробник друга по ссылке — +N дней другу и +N пригласившему (не больше LIMIT в месяц)
    referral_trial_days: int = 7
    referral_trial_limit: int = 10
    # Личный промокод в напоминании за сутки до конца: скидка % на тарифы от MIN_DAYS дней, действует N дней
    renew_promo_percent: int = 15
    renew_promo_min_days: int = 90
    renew_promo_valid_days: int = 3
    # Компенсация: VPN недоступен у всех (все ноды недоступны) дольше N минут → +DAYS всем активным
    outage_compensation_days: int = 2
    outage_min_minutes: int = 60
    referral_bonus_days: int = 7

    # Platega — оплата картами и СБП. Пусто — способ не показывается.
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_url: str = "https://app.platega.io"
    # Способ оплаты: 0 — клиент выбирает сам на странице Platega; 2 — СБП; 10 или 11 — банковские карты
    platega_method: int = 0
    platega_title: str = "Картой или СБП"   # надпись на кнопке оплаты

    cryptopay_token: str = ""
    cryptopay_testnet: bool = False
    cryptopay_assets: str = "USDT,TON"

    database_url: str
    redis_url: str = ""

    @property
    def bridge_list(self) -> list[str]:
        return [x.strip() for x in self.bridges.split(",") if x.strip()]

    @cached_property
    def admins(self) -> set[int]:
        return {int(x) for x in self.admin_ids.replace(" ", "").split(",") if x}

    @cached_property
    def squads(self) -> list[str]:
        return [x.strip() for x in self.panel_squad_uuids.split(",") if x.strip()]

    @cached_property
    def plan_list(self) -> list[Plan]:
        out = []
        for chunk in self.plans.split(","):
            days, rub, stars = (int(v) for v in chunk.strip().split(":"))
            out.append(Plan(code=f"d{days}", days=days, rub=rub, stars=stars))
        return out

    def plan(self, code: str) -> Plan | None:
        if code == TEST_PLAN.code:  # скрытый тариф для проверки оплаты админом: 1 ⭐ = 1 день
            return TEST_PLAN
        return next((p for p in self.plan_list if p.code == code), None)

    @cached_property
    def channel_name(self) -> str:
        """Имя канала без @ и ссылки: «whiteholevpn»."""
        v = self.channel_username.strip()
        for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
            if v.lower().startswith(prefix):
                v = v[len(prefix):]
        return v.strip("/").split("/")[0]

    @property
    def channel_url(self) -> str:
        return f"https://t.me/{self.channel_name}" if self.channel_name else ""

    @cached_property
    def review_recipients(self) -> list[int]:
        ids = [int(x) for x in self.review_to.replace(" ", "").split(",") if x.lstrip("-").isdigit()]
        return ids or sorted(self.admins)

    @cached_property
    def yt_exit_list(self) -> list[str]:
        return [x.strip() for x in self.yt_exits.split(",") if x.strip() and ":" in x]

    @cached_property
    def weights(self) -> dict[str, float]:
        out = {}
        for chunk in self.node_weights.split(","):
            if ":" in chunk:
                name, w = chunk.rsplit(":", 1)
                out[name.strip()] = max(0.1, float(w))
        return out

    def site_url(self, page: str) -> str:
        """Публичная страница сайта (info, terms, privacy) рядом с мини-аппом; пусто — если мини-апп не настроен."""
        return f"{self.miniapp_url.rstrip('/')}/{page}" if self.miniapp_url else ""

    @property
    def card_enabled(self) -> bool:
        return bool(self.platega_merchant_id and self.platega_secret)

    @property
    def crypto_enabled(self) -> bool:
        return bool(self.cryptopay_token)


settings = Settings()
