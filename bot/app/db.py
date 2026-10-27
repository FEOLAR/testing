from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .config import settings

engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(256))
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # заблокировал бота

    # Кэш данных из панели (источник правды — панель)
    sub_url: Mapped[str | None] = mapped_column(String(512))
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Какие напоминания уже отправлены для текущего expire_at: "", "3d", "1d", "exp"
    notice: Mapped[str] = mapped_column(String(8), default="")
    # Промокод, который пользователь ввёл и ещё не использовал в оплате
    promo_id: Mapped[int | None] = mapped_column(Integer)
    # Бонус за подписку на канал уже получен
    channel_bonus: Mapped[bool] = mapped_column(Boolean, default=False)
    # Отзыв: когда оставил последний (None — ещё не оставлял) и когда последний раз напоминали
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Когда пользователь последний раз сам заменил ссылку-подписку (защита от частых нажатий)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Бонус за пробник по реф-ссылке уже начислен (другу и пригласившему)
    ref_trial_rewarded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Последняя покупка — семейный тариф (лимит FAMILY_DEVICE_LIMIT)
    family: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Откуда пришёл: метка из ссылки ?start=src_<метка>, "ref" (реф-ссылка) или "promo:<КОД>"
    source: Mapped[str | None] = mapped_column(String(40), index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def panel_username(self) -> str:
        return f"tg_{self.tg_id}"


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("method", "external_id", name="uq_payment_external"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_code: Mapped[str] = mapped_column(String(16))
    days: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(16))  # stars | crypto | admin
    amount: Mapped[str] = mapped_column(String(32))  # "150 XTR" / "199 RUB"
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|paid|expired|refunded
    external_id: Mapped[str | None] = mapped_column(String(512))  # invoice_id / charge_id
    pay_url: Mapped[str | None] = mapped_column(String(512))
    promo_id: Mapped[int | None] = mapped_column(Integer, index=True)  # промокод, со скидкой по которому оплачено
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)   # всегда в ВЕРХНЕМ регистре
    percent: Mapped[int] = mapped_column(Integer)                # скидка, %
    max_uses: Mapped[int] = mapped_column(Integer, default=0)    # лимит активаций, 0 — без лимита
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Скидка действует только на тарифы от min_days дней (0 — на любой)
    min_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Срок действия кода (None — бессрочный)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Личный код: применить может только этот пользователь (None — общий код)
    owner_tg_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Таблицы, созданные старыми версиями бота, могли остаться без новых колонок и индексов.
# create_all их не добавляет, поэтому доводим схему сами (идемпотентно).
MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_rewarded BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS sub_url VARCHAR(512)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS expire_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS notice VARCHAR(8) NOT NULL DEFAULT ''",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS external_id VARCHAR(128)",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS pay_url VARCHAR(512)",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_external_idx ON payments (method, external_id)",
    # ID платежей Stars бывают длиннее 128 символов
    "ALTER TABLE payments ALTER COLUMN external_id TYPE VARCHAR(512)",
    "ALTER TABLE users ALTER COLUMN first_name TYPE VARCHAR(256)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_id INTEGER",
    "ALTER TABLE payments ADD COLUMN IF NOT EXISTS promo_id INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_payments_promo_id ON payments (promo_id)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS channel_bonus BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS review_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS review_reminded_at TIMESTAMPTZ",
    # хосты, которые бот спрятал из подписки из-за упавшей ноды (чтобы вернуть только их)
    "CREATE TABLE IF NOT EXISTS hidden_hosts (uuid VARCHAR(64) PRIMARY KEY, hidden_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS ref_trial_rewarded BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS family BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS min_days INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
    "ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS owner_tg_id BIGINT",
    "CREATE INDEX IF NOT EXISTS ix_promo_codes_owner_tg_id ON promo_codes (owner_tg_id)",
    "CREATE TABLE IF NOT EXISTS outages (id SERIAL PRIMARY KEY, started_at TIMESTAMPTZ NOT NULL, "
    "ended_at TIMESTAMPTZ, compensated BOOLEAN NOT NULL DEFAULT FALSE)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS source VARCHAR(40)",
    "CREATE INDEX IF NOT EXISTS ix_users_source ON users (source)",
]


async def init_db() -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in MIGRATIONS:
            await conn.execute(text(sql))
