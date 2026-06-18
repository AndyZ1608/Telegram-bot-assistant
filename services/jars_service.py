"""Core 6 JARS personal-finance service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

import config
from database.db import get_session
from database.models import JarsSettings
from services.accounting_service import (
    JarNotFoundError,
    add_expense,
    add_or_update_jar,
    get_income,
    get_monthly_summary,
    list_jars,
    set_income,
)


JAR_DEFINITIONS: dict[str, str] = {
    "NEC": "Chi tiêu cần thiết",
    "FFA": "Tự do tài chính",
    "LTS": "Tiết kiệm dài hạn",
    "EDU": "Giáo dục",
    "PLAY": "Hưởng thụ",
    "GIVE": "Cho đi",
}

JAR_ORDER = ["NEC", "FFA", "LTS", "EDU", "PLAY", "GIVE"]

PRESETS: dict[str, dict[str, float]] = {
    "default": {"NEC": 55, "FFA": 10, "LTS": 10, "EDU": 10, "PLAY": 10, "GIVE": 5},
    "single_renter": {"NEC": 60, "FFA": 10, "LTS": 10, "EDU": 5, "PLAY": 10, "GIVE": 5},
}


class InvalidJarCodeError(ValueError):
    """Raised when a jar code is not one of the 6 JARS codes."""


class InvalidPresetError(ValueError):
    """Raised when a JARS preset is unknown."""


@dataclass(frozen=True)
class JarAllocation:
    code: str
    name: str
    ratio: float
    budget: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return self.budget - self.spent

    @property
    def usage_percent(self) -> float:
        if self.budget <= 0:
            return 100.0 if self.spent > 0 else 0.0
        return self.spent / self.budget * 100


@dataclass(frozen=True)
class JarsOverview:
    income: float | None
    preset: str
    jars: list[JarAllocation]


def normalize_jar_code(value: str | None) -> str:
    code = (value or "").strip().upper()
    if code not in JAR_DEFINITIONS:
        raise InvalidJarCodeError(code)
    return code


async def get_user_preset(user_id: int) -> str:
    async with get_session() as session:
        result = await session.execute(
            select(JarsSettings).where(JarsSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = JarsSettings(user_id=user_id, preset="default")
            session.add(settings)
            return "default"
        return settings.preset


async def set_user_preset(user_id: int, preset: str) -> str:
    if preset not in PRESETS:
        raise InvalidPresetError(preset)
    async with get_session() as session:
        result = await session.execute(
            select(JarsSettings).where(JarsSettings.user_id == user_id)
        )
        settings = result.scalar_one_or_none()
        if settings is None:
            settings = JarsSettings(user_id=user_id, preset=preset)
            session.add(settings)
        else:
            settings.preset = preset
    return preset


async def init_jars(user_id: int, preset: str | None = None) -> JarsOverview:
    selected = preset or await get_user_preset(user_id)
    if selected not in PRESETS:
        raise InvalidPresetError(selected)
    if preset:
        await set_user_preset(user_id, selected)

    income = await get_income(user_id)
    for code, ratio in PRESETS[selected].items():
        budget = income * ratio / 100 if income else 0.0
        await add_or_update_jar(user_id, code, budget)
    return await get_jars_overview(user_id)


async def allocate_income(user_id: int, amount: float) -> JarsOverview:
    await set_income(user_id, amount)
    preset = await get_user_preset(user_id)
    for code, ratio in PRESETS[preset].items():
        await add_or_update_jar(user_id, code, amount * ratio / 100)
    return await get_jars_overview(user_id)


async def get_jars_overview(user_id: int) -> JarsOverview:
    preset = await get_user_preset(user_id)
    income = await get_income(user_id)
    statuses = {status.name.upper(): status for status in await list_jars(user_id)}
    jars = []
    for code in JAR_ORDER:
        status = statuses.get(code)
        ratio = PRESETS[preset][code]
        jars.append(
            JarAllocation(
                code=code,
                name=JAR_DEFINITIONS[code],
                ratio=ratio,
                budget=status.budget_amount if status else 0.0,
                spent=status.spent_amount if status else 0.0,
            )
        )
    return JarsOverview(income=income, preset=preset, jars=jars)


async def add_jars_expense(user_id: int, code: str, amount: float, note: str | None) -> JarAllocation:
    normalized = normalize_jar_code(code)
    try:
        await add_expense(user_id, normalized, amount, note)
    except JarNotFoundError:
        await init_jars(user_id)
        await add_expense(user_id, normalized, amount, note)
    overview = await get_jars_overview(user_id)
    return next(jar for jar in overview.jars if jar.code == normalized)


async def get_jars_dashboard(user_id: int):
    summary = await get_monthly_summary(user_id, require_income=False)
    overview = await get_jars_overview(user_id)
    return summary, overview


def days_left_in_month() -> int:
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    return max((next_month - today).days, 1)
