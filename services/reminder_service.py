"""
Reminder and automation settings service.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

import config
from database.db import get_session
from database.models import AutomationLog, UserSettings
from services.accounting_service import MissingIncomeError, get_monthly_summary
from services.investment_service import check_price_alerts
from services.startup_news import build_startup_digest
from utils.formatter import format_currency


TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ReminderError(Exception):
    """Base reminder settings error."""


class InvalidTimeError(ReminderError):
    """Raised when HH:MM is invalid."""


class InvalidDayError(ReminderError):
    """Raised when monthly report day is invalid."""


@dataclass(frozen=True)
class AutomationMessage:
    user_id: int
    text: str
    job_type: str
    period_key: str


def validate_time(value: str) -> str:
    value = value.strip()
    if not TIME_RE.match(value):
        raise InvalidTimeError("Time must be HH:MM, for example 21:30.")
    return value


def validate_monthly_day(value: int) -> int:
    if value < 1 or value > 28:
        raise InvalidDayError("Monthly report day must be between 1 and 28.")
    return value


async def get_or_create_user_settings(user_id: int) -> UserSettings:
    async with get_session() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = UserSettings(
                user_id=user_id,
                timezone=config.DEFAULT_TIMEZONE,
            )
            session.add(settings)
        return settings


async def list_user_settings() -> list[UserSettings]:
    async with get_session() as session:
        result = await session.execute(select(UserSettings).order_by(UserSettings.user_id))
        return list(result.scalars().all())


async def update_daily_reminder(user_id: int, enabled: bool | None = None, time_value: str | None = None) -> UserSettings:
    async with get_session() as session:
        settings = await _get_or_create_in_session(session, user_id)
        if enabled is not None:
            settings.daily_reminder_enabled = enabled
        if time_value is not None:
            settings.daily_reminder_time = validate_time(time_value)
        return settings


async def update_monthly_report(user_id: int, enabled: bool | None = None, day: int | None = None) -> UserSettings:
    async with get_session() as session:
        settings = await _get_or_create_in_session(session, user_id)
        if enabled is not None:
            settings.monthly_report_enabled = enabled
        if day is not None:
            settings.monthly_report_day = validate_monthly_day(day)
        return settings


async def update_startup_digest(user_id: int, enabled: bool | None = None, topic: str | None = None) -> UserSettings:
    async with get_session() as session:
        settings = await _get_or_create_in_session(session, user_id)
        if enabled is not None:
            settings.startup_digest_enabled = enabled
        if topic is not None:
            settings.startup_digest_topic = topic.strip().lower() or "vn"
        return settings


async def update_price_alert_setting(user_id: int, enabled: bool) -> UserSettings:
    async with get_session() as session:
        settings = await _get_or_create_in_session(session, user_id)
        settings.price_alert_enabled = enabled
        return settings


def format_settings(settings: UserSettings) -> str:
    return "\n".join([
        "Settings",
        f"Timezone: {settings.timezone}",
        f"Daily reminder: {'on' if settings.daily_reminder_enabled else 'off'} at {settings.daily_reminder_time}",
        f"Monthly report: {'on' if settings.monthly_report_enabled else 'off'} day {settings.monthly_report_day}",
        f"Startup digest: {'on' if settings.startup_digest_enabled else 'off'} topic {settings.startup_digest_topic}",
        f"Price alert automation: {'on' if settings.price_alert_enabled else 'off'}",
    ])


async def already_sent(user_id: int, job_type: str, period_key: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            select(AutomationLog.id).where(
                AutomationLog.user_id == user_id,
                AutomationLog.job_type == job_type,
                AutomationLog.period_key == period_key,
            )
        )
        return result.scalar_one_or_none() is not None


async def mark_sent(user_id: int, job_type: str, period_key: str) -> None:
    if await already_sent(user_id, job_type, period_key):
        return
    async with get_session() as session:
        session.add(
            AutomationLog(
                user_id=user_id,
                job_type=job_type,
                period_key=period_key,
            )
        )


async def due_daily_reminder(settings: UserSettings, now_utc: datetime) -> AutomationMessage | None:
    if not settings.daily_reminder_enabled:
        return None
    local_now = _local_now(settings, now_utc)
    if local_now.strftime("%H:%M") != settings.daily_reminder_time:
        return None
    period_key = local_now.date().isoformat()
    if await already_sent(settings.user_id, "daily_reminder", period_key):
        return None
    return AutomationMessage(
        user_id=settings.user_id,
        text="Bạn đã ghi chi tiêu hôm nay chưa?",
        job_type="daily_reminder",
        period_key=period_key,
    )


async def due_monthly_report(settings: UserSettings, now_utc: datetime) -> AutomationMessage | None:
    if not settings.monthly_report_enabled:
        return None
    local_now = _local_now(settings, now_utc)
    if local_now.day != settings.monthly_report_day:
        return None
    period_key = local_now.strftime("%Y-%m")
    if await already_sent(settings.user_id, "monthly_report", period_key):
        return None
    try:
        summary = await get_monthly_summary(settings.user_id)
        text = "\n".join([
            f"Monthly report {summary.month:02d}/{summary.year}",
            f"Income: {format_currency(summary.income)}",
            f"Total budget: {format_currency(summary.total_budget)}",
            f"Total spent: {format_currency(summary.total_expense)}",
            f"Saving actual: {format_currency(summary.actual_saving)}",
            f"Saving rate: {summary.saving_rate * 100:.2f}%",
        ])
    except MissingIncomeError:
        text = "Monthly report: tháng này chưa có income để lập báo cáo."
    return AutomationMessage(settings.user_id, text, "monthly_report", period_key)


async def due_startup_digest(settings: UserSettings, now_utc: datetime) -> AutomationMessage | None:
    if not settings.startup_digest_enabled:
        return None
    local_now = _local_now(settings, now_utc)
    if local_now.weekday() != 0:
        return None
    if local_now.strftime("%H:%M") != settings.daily_reminder_time:
        return None
    iso_year, iso_week, _ = local_now.isocalendar()
    period_key = f"{iso_year}-W{iso_week:02d}"
    if await already_sent(settings.user_id, "startup_digest", period_key):
        return None
    digest = await build_startup_digest(settings.startup_digest_topic)
    lines = [
        f"Startup digest: {digest['topic']}",
        f"Nguồn: {digest['source_note']} (sample/mock nếu provider=mock)",
        "Top news:",
    ]
    lines.extend(f"- {item.get('title', 'chưa có tiêu đề')}" for item in digest["news"][:5])
    lines.append(f"Trend: {digest['trend']}")
    return AutomationMessage(settings.user_id, "\n".join(lines), "startup_digest", period_key)


async def due_price_alerts(settings: UserSettings) -> list[AutomationMessage]:
    if not settings.price_alert_enabled:
        return []
    results = await check_price_alerts(settings.user_id)
    messages: list[AutomationMessage] = []
    for result in results:
        if not result.triggered:
            continue
        period_key = f"alert-{result.id}"
        if await already_sent(settings.user_id, "price_alert", period_key):
            continue
        text = (
            f"Price alert triggered #{result.id}: {result.symbol}\n"
            f"Current: {format_currency(result.current_price or 0)}\n"
            f"Condition: {result.condition_type} {format_currency(result.target_price)}\n"
            "Không phải khuyến nghị đầu tư."
        )
        messages.append(AutomationMessage(settings.user_id, text, "price_alert", period_key))
    return messages


async def _get_or_create_in_session(session, user_id: int) -> UserSettings:
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserSettings(
            user_id=user_id,
            timezone=config.DEFAULT_TIMEZONE,
        )
        session.add(settings)
    return settings


def _local_now(settings: UserSettings, now_utc: datetime) -> datetime:
    tz = ZoneInfo(settings.timezone or config.DEFAULT_TIMEZONE)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=ZoneInfo("UTC"))
    return now_utc.astimezone(tz)
