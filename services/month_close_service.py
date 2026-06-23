"""Month closing and rollover logic for JARS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

import config
from database.db import get_session
from database.models import (
    MonthCloseSettings,
    MonthlyClosure,
    MonthlyRolloverDetail,
)
from services.accounting_service import (
    current_month_year,
    get_income_for_month,
    list_jars,
)
from services.reminder_service import get_telegram_user_id


ROLLOVER_SOURCE_JARS = ["NEC", "FFA", "EDU", "PLAY", "GIVE"]
JARS_CODES = ["NEC", "FFA", "LTS", "EDU", "PLAY", "GIVE"]


class MonthCloseError(Exception):
    """Base month close error."""


class MonthAlreadyClosedError(MonthCloseError):
    """Raised when a month is already closed."""


@dataclass(frozen=True)
class RolloverLine:
    jar_code: str
    budget_amount: float
    spent_amount: float
    remaining_amount: float
    rollover_amount: float


@dataclass(frozen=True)
class MonthClosePreview:
    user_id: int
    month: int
    year: int
    income_amount: float
    total_spent: float
    original_lts_budget: float
    lts_spent_or_saved: float
    rollover_to_lts: float
    final_lts_amount: float
    details: list[RolloverLine]
    is_closed: bool = False


def _format_vnd(amount: float | int | None) -> str:
    value = int(round(amount or 0))
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,}".replace(",", ".") + " ₫"


def _month_bounds(month: int, year: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def _is_last_calendar_day(local_now: datetime) -> bool:
    _, end = _month_bounds(local_now.month, local_now.year)
    return local_now.date() == date.fromordinal(end.toordinal() - 1)


async def is_month_closed(user_id: int, month: int | None = None, year: int | None = None) -> bool:
    if month is None or year is None:
        month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyClosure.id).where(
                MonthlyClosure.user_id == user_id,
                MonthlyClosure.month == month,
                MonthlyClosure.year == year,
                MonthlyClosure.is_closed.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None


async def get_month_close_settings(user_id: int) -> MonthCloseSettings:
    async with get_session() as session:
        result = await session.execute(
            select(MonthCloseSettings).where(MonthCloseSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = MonthCloseSettings(
                user_id=user_id,
                timezone=config.DEFAULT_TIMEZONE,
            )
            session.add(settings)
        return settings


async def update_month_close_auto(user_id: int, enabled: bool) -> MonthCloseSettings:
    async with get_session() as session:
        result = await session.execute(
            select(MonthCloseSettings).where(MonthCloseSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = MonthCloseSettings(user_id=user_id, timezone=config.DEFAULT_TIMEZONE)
            session.add(settings)
        settings.auto_month_close_enabled = enabled
        return settings


async def list_auto_month_close_settings() -> list[MonthCloseSettings]:
    async with get_session() as session:
        result = await session.execute(
            select(MonthCloseSettings)
            .where(MonthCloseSettings.auto_month_close_enabled.is_(True))
            .order_by(MonthCloseSettings.user_id)
        )
        return list(result.scalars().all())


async def build_month_close_preview(user_id: int, month: int | None = None, year: int | None = None) -> MonthClosePreview:
    if month is None or year is None:
        month, year = current_month_year()
    income = await get_income_for_month(user_id, month, year) or 0.0
    statuses = {status.name.upper(): status for status in await list_jars(user_id, month, year)}
    total_spent = sum(status.spent_amount for status in statuses.values())
    lts = statuses.get("LTS")
    original_lts_budget = lts.budget_amount if lts else 0.0
    lts_spent_or_saved = lts.spent_amount if lts else 0.0

    details: list[RolloverLine] = []
    rollover_to_lts = 0.0
    for code in ROLLOVER_SOURCE_JARS:
        status = statuses.get(code)
        budget = status.budget_amount if status else 0.0
        spent = status.spent_amount if status else 0.0
        remaining = budget - spent
        rollover = remaining if remaining > 0 else 0.0
        rollover_to_lts += rollover
        details.append(
            RolloverLine(
                jar_code=code,
                budget_amount=budget,
                spent_amount=spent,
                remaining_amount=remaining,
                rollover_amount=rollover,
            )
        )

    return MonthClosePreview(
        user_id=user_id,
        month=month,
        year=year,
        income_amount=income,
        total_spent=total_spent,
        original_lts_budget=original_lts_budget,
        lts_spent_or_saved=lts_spent_or_saved,
        rollover_to_lts=rollover_to_lts,
        final_lts_amount=original_lts_budget + lts_spent_or_saved + rollover_to_lts,
        details=details,
        is_closed=await is_month_closed(user_id, month, year),
    )


async def confirm_month_close(user_id: int) -> MonthClosePreview:
    month, year = current_month_year()
    preview = await build_month_close_preview(user_id, month, year)
    if preview.is_closed:
        raise MonthAlreadyClosedError(f"Month {month:02d}/{year} already closed.")

    async with get_session() as session:
        existing = await session.scalar(
            select(MonthlyClosure).where(
                MonthlyClosure.user_id == user_id,
                MonthlyClosure.month == month,
                MonthlyClosure.year == year,
                MonthlyClosure.is_closed.is_(True),
            )
        )
        if existing is not None:
            raise MonthAlreadyClosedError(f"Month {month:02d}/{year} already closed.")

        closure = MonthlyClosure(
            user_id=user_id,
            month=month,
            year=year,
            income_amount=preview.income_amount,
            total_spent=preview.total_spent,
            original_lts_budget=preview.original_lts_budget,
            rollover_to_lts=preview.rollover_to_lts,
            final_lts_amount=preview.final_lts_amount,
            is_closed=True,
        )
        session.add(closure)
        await session.flush()
        for detail in preview.details:
            session.add(
                MonthlyRolloverDetail(
                    closure_id=closure.id,
                    jar_code=detail.jar_code,
                    budget_amount=detail.budget_amount,
                    spent_amount=detail.spent_amount,
                    remaining_amount=detail.remaining_amount,
                    rollover_amount=detail.rollover_amount,
                )
            )
    return MonthClosePreview(**{**preview.__dict__, "is_closed": True})


async def get_closure(user_id: int, month: int, year: int) -> MonthlyClosure | None:
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyClosure).where(
                MonthlyClosure.user_id == user_id,
                MonthlyClosure.month == month,
                MonthlyClosure.year == year,
                MonthlyClosure.is_closed.is_(True),
            )
        )
        return result.scalar_one_or_none()


async def list_closures(user_id: int) -> list[MonthlyClosure]:
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyClosure)
            .where(MonthlyClosure.user_id == user_id, MonthlyClosure.is_closed.is_(True))
            .order_by(MonthlyClosure.year, MonthlyClosure.month)
        )
        return list(result.scalars().all())


def format_month_close_preview(preview: MonthClosePreview) -> str:
    lines = [f"Dự kiến chốt tháng {preview.month:02d}/{preview.year}", ""]
    for detail in preview.details:
        if detail.rollover_amount > 0:
            lines.append(f"{detail.jar_code} còn dư: {_format_vnd(detail.rollover_amount)} → LTS")
        else:
            lines.append(f"{detail.jar_code} còn dư: 0 ₫")
    lines.extend([
        "",
        f"Tổng chuyển vào LTS: {_format_vnd(preview.rollover_to_lts)}",
        f"LTS ban đầu: {_format_vnd(preview.original_lts_budget)}",
        f"LTS cuối tháng: {_format_vnd(preview.final_lts_amount)}",
        "",
        "Dùng /month_close confirm để chốt.",
    ])
    return "\n".join(lines)


def format_month_close_confirm(preview: MonthClosePreview) -> str:
    return "\n".join([
        f"Đã chốt tháng {preview.month:02d}/{preview.year}.",
        "",
        f"Tổng rollover vào LTS: {_format_vnd(preview.rollover_to_lts)}",
        f"LTS cuối tháng: {_format_vnd(preview.final_lts_amount)}",
    ])


async def format_month_summary(user_id: int, month: int | None = None, year: int | None = None) -> str:
    if month is None or year is None:
        month, year = current_month_year()
    closure = await get_closure(user_id, month, year)
    if closure is None:
        preview = await build_month_close_preview(user_id, month, year)
        status = "Chưa chốt"
        income = preview.income_amount
        total_spent = preview.total_spent
        original_lts = preview.original_lts_budget
        rollover = preview.rollover_to_lts
        final_lts = preview.final_lts_amount
    else:
        status = "Đã chốt"
        income = closure.income_amount
        total_spent = closure.total_spent
        original_lts = closure.original_lts_budget
        rollover = closure.rollover_to_lts
        final_lts = closure.final_lts_amount
    return "\n".join([
        f"Tổng kết tháng {month:02d}/{year}",
        f"Trạng thái: {status}",
        "",
        f"Thu nhập: {_format_vnd(income)}",
        f"Tổng chi: {_format_vnd(total_spent)}",
        f"LTS ban đầu: {_format_vnd(original_lts)}",
        f"Rollover vào LTS: {_format_vnd(rollover)}",
        f"LTS cuối tháng: {_format_vnd(final_lts)}",
    ])


async def format_compare_months(user_id: int) -> str:
    closures = await list_closures(user_id)
    if not closures:
        return "Chưa có tháng nào đã chốt để so sánh."
    lines = ["So sánh các tháng"]
    for closure in closures:
        retained_rate = closure.final_lts_amount / closure.income_amount * 100 if closure.income_amount else 0.0
        lines.extend([
            "",
            f"{closure.month:02d}/{closure.year}:",
            f"Thu nhập: {_format_vnd(closure.income_amount)}",
            f"Tổng chi: {_format_vnd(closure.total_spent)}",
            f"LTS cuối tháng: {_format_vnd(closure.final_lts_amount)}",
            f"Tỷ lệ giữ lại: {retained_rate:.1f}%",
        ])
    return "\n".join(lines)


async def due_auto_month_close(settings: MonthCloseSettings, now_utc: datetime):
    if not settings.auto_month_close_enabled:
        return None
    tz = ZoneInfo(settings.timezone or config.DEFAULT_TIMEZONE)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=ZoneInfo("UTC"))
    local_now = now_utc.astimezone(tz)
    if local_now.strftime("%H:%M") != settings.auto_month_close_time:
        return None
    if not _is_last_calendar_day(local_now):
        return None
    if await is_month_closed(settings.user_id, local_now.month, local_now.year):
        return None
    try:
        preview = await confirm_month_close(settings.user_id)
    except MonthAlreadyClosedError:
        return None
    telegram_user_id = await get_telegram_user_id(settings.user_id)
    if telegram_user_id is None:
        return None
    return (
        settings.user_id,
        telegram_user_id,
        "\n".join([
            f"Tự động chốt tháng {preview.month:02d}/{preview.year}.",
            f"Rollover vào LTS: {_format_vnd(preview.rollover_to_lts)}",
            f"LTS cuối tháng: {_format_vnd(preview.final_lts_amount)}",
        ]),
        "month_close",
        f"{preview.year}-{preview.month:02d}",
    )
