"""
SQLAlchemy 2.0 ORM models for the Telegram Assistant Bot.

Tables
------
- **users** – registered Telegram users
- **monthly_income** – per-user monthly income records
- **budget_jars** – per-user monthly budget jar allocations
- **expenses** – individual expense transactions
- **watchlist** – investment watchlist entries (stocks, crypto, etc.)
- **startup_cache** – cached startup / tech news articles
- **settings** – per-user configuration preferences
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""
    pass


class User(Base):
    """Registered Telegram user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    full_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<User(id={self.id}, telegram_user_id={self.telegram_user_id}, "
            f"username={self.username!r})>"
        )


class MonthlyIncome(Base):
    """Monthly income record for a user."""

    __tablename__ = "monthly_income"
    __table_args__ = (
        UniqueConstraint("user_id", "month", "year", name="uq_income_user_month_year"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<MonthlyIncome(id={self.id}, user_id={self.user_id}, "
            f"{self.month}/{self.year}, amount={self.amount})>"
        )


class BudgetJar(Base):
    """Budget jar allocation for a user in a specific month."""

    __tablename__ = "budget_jars"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "month", "year", "name",
            name="uq_jar_user_month_year_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    budget_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<BudgetJar(id={self.id}, user_id={self.user_id}, "
            f"name={self.name!r}, budget={self.budget_amount})>"
        )


class Expense(Base):
    """Individual expense transaction."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    jar_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<Expense(id={self.id}, user_id={self.user_id}, "
            f"amount={self.amount}, jar={self.jar_name!r}, date={self.transaction_date})>"
        )


class Watchlist(Base):
    """Investment watchlist entry for a user."""

    __tablename__ = "watchlist"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    market: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<Watchlist(id={self.id}, user_id={self.user_id}, "
            f"symbol={self.symbol!r}, market={self.market!r})>"
        )


class PriceAlert(Base):
    """Simple stock price alert rule."""

    __tablename__ = "price_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    condition_type: Mapped[str] = mapped_column(String, nullable=False)
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PriceAlert(id={self.id}, user_id={self.user_id}, "
            f"symbol={self.symbol!r}, condition={self.condition_type!r}, "
            f"target={self.target_price})>"
        )


class Portfolio(Base):
    """Simple stock portfolio position."""

    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<Portfolio(id={self.id}, user_id={self.user_id}, "
            f"symbol={self.symbol!r}, qty={self.quantity}, buy={self.buy_price})>"
        )


class StartupCache(Base):
    """Cached startup / tech news article."""

    __tablename__ = "startup_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[Optional[str]] = mapped_column(String, index=True)
    title: Mapped[Optional[str]] = mapped_column(String)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(String)
    source: Mapped[Optional[str]] = mapped_column(String)
    country: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<StartupCache(id={self.id}, topic={self.topic!r}, "
            f"title={self.title!r})>"
        )


class UserSettings(Base):
    """Automation and reminder settings per Telegram user."""

    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Ho_Chi_Minh", nullable=False)
    daily_reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_reminder_time: Mapped[str] = mapped_column(String, default="21:00", nullable=False)
    monthly_report_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    monthly_report_day: Mapped[int] = mapped_column(Integer, default=28, nullable=False)
    startup_digest_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    startup_digest_topic: Mapped[str] = mapped_column(String, default="vn", nullable=False)
    price_alert_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<UserSettings(user_id={self.user_id}, tz={self.timezone!r}, "
            f"daily={self.daily_reminder_enabled})>"
        )


class AutomationLog(Base):
    """Sent automation record used to avoid duplicate reminders."""

    __tablename__ = "automation_log"
    __table_args__ = (
        UniqueConstraint("user_id", "job_type", "period_key", name="uq_automation_user_job_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(String, nullable=False)
    period_key: Mapped[str] = mapped_column(String, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<AutomationLog(user_id={self.user_id}, job={self.job_type!r}, "
            f"period={self.period_key!r})>"
        )


class Settings(Base):
    """Per-user configuration preferences."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="VND")
    timezone: Mapped[str] = mapped_column(String, default="Asia/Ho_Chi_Minh")
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_report_day: Mapped[int] = mapped_column(Integer, default=28)
    language: Mapped[str] = mapped_column(String, default="vi")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<Settings(id={self.id}, user_id={self.user_id}, "
            f"currency={self.currency!r}, lang={self.language!r})>"
        )
