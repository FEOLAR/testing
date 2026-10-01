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
    first_name: Mapped[str | None] = mapped_column(String(128))
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    referral_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)  # заблокировал бота

    # Кэш данных из панели (источник правды — панель)
    sub_url: Mapped[str | None] = mapped_column(String(512))
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Какие напоминания уже отправлены для текущего expire_at: "", "3d", "1d", "exp"
    notice: Mapped[str] = mapped_column(String(8), default="")

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
    external_id: Mapped[str | None] = mapped_column(String(128))  # invoice_id / charge_id
    pay_url: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


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
]


async def init_db() -> None:
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for sql in MIGRATIONS:
            await conn.execute(text(sql))
