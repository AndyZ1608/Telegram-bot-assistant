"""
Accounting service for the Telegram bot personal-finance MVP.

This module keeps command handlers small and centralizes all per-user,
current-month accounting queries.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select

import config
from database.db import get_session
from database.models import BudgetJar, Expense, MonthlyIncome, User


class AccountingError(Exception):
    """Base error for user-facing accounting failures."""


class MissingIncomeError(AccountingError):
    """Raised when a monthly report needs income but none exists."""


class JarNotFoundError(AccountingError):
    """Raised when an expense targets a missing current-month jar."""


class JarHasExpensesError(AccountingError):
    """Raised when deleting a jar that still has current-month expenses."""


class ExpenseNotFoundError(AccountingError):
    """Raised when an expense is not owned by the user or does not exist."""


class NoExportDataError(AccountingError):
    """Raised when there are no expenses to export."""


@dataclass(frozen=True)
class JarStatus:
    name: str
    budget_amount: float
    spent_amount: float

    @property
    def remaining_amount(self) -> float:
        return self.budget_amount - self.spent_amount

    @property
    def usage_ratio(self) -> float:
        if self.budget_amount <= 0:
            return 1.0 if self.spent_amount > 0 else 0.0
        return self.spent_amount / self.budget_amount


@dataclass(frozen=True)
class MonthlySummary:
    month: int
    year: int
    income: float
    jars: list[JarStatus]
    total_budget: float
    total_expense: float
    projected_saving: float
    actual_saving: float
    saving_rate: float


@dataclass(frozen=True)
class ExpenseView:
    id: int
    jar_name: str | None
    category: str | None
    amount: float
    note: str | None
    transaction_date: date


def current_month_year() -> tuple[int, int]:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    return now.month, now.year


def _today() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def _month_bounds(month: int, year: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _current_month_bounds() -> tuple[date, date]:
    month, year = current_month_year()
    return _month_bounds(month, year)


async def ensure_user(telegram_user_id: int, username: str | None, full_name: str | None) -> User:
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                username=username,
                full_name=full_name,
            )
            session.add(user)
        else:
            user.username = username
            user.full_name = full_name
            user.updated_at = datetime.utcnow()
        return user


async def set_income(user_id: int, amount: float) -> MonthlyIncome:
    month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyIncome).where(
                MonthlyIncome.user_id == user_id,
                MonthlyIncome.month == month,
                MonthlyIncome.year == year,
            )
        )
        income = result.scalar_one_or_none()
        if income is None:
            income = MonthlyIncome(
                user_id=user_id,
                month=month,
                year=year,
                amount=amount,
            )
            session.add(income)
        else:
            income.amount = amount
        return income


async def add_or_update_jar(user_id: int, name: str, amount: float) -> BudgetJar:
    month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(BudgetJar).where(
                BudgetJar.user_id == user_id,
                BudgetJar.month == month,
                BudgetJar.year == year,
                BudgetJar.name == name,
            )
        )
        jar = result.scalar_one_or_none()
        if jar is None:
            jar = BudgetJar(
                user_id=user_id,
                month=month,
                year=year,
                name=name,
                budget_amount=amount,
            )
            session.add(jar)
        else:
            jar.budget_amount = amount
        return jar


async def update_jar(user_id: int, name: str, amount: float) -> BudgetJar:
    month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(BudgetJar).where(
                BudgetJar.user_id == user_id,
                BudgetJar.month == month,
                BudgetJar.year == year,
                BudgetJar.name == name,
            )
        )
        jar = result.scalar_one_or_none()
        if jar is None:
            raise JarNotFoundError(f"Hu '{name}' khong ton tai trong thang hien tai.")
        jar.budget_amount = amount
        return jar


async def delete_jar(user_id: int, name: str) -> None:
    month, year = current_month_year()
    start, end = _month_bounds(month, year)
    async with get_session() as session:
        result = await session.execute(
            select(BudgetJar).where(
                BudgetJar.user_id == user_id,
                BudgetJar.month == month,
                BudgetJar.year == year,
                BudgetJar.name == name,
            )
        )
        jar = result.scalar_one_or_none()
        if jar is None:
            raise JarNotFoundError(f"Hu '{name}' khong ton tai trong thang hien tai.")

        expense_count = await session.scalar(
            select(func.count(Expense.id)).where(
                Expense.user_id == user_id,
                Expense.jar_name == name,
                Expense.transaction_date >= start,
                Expense.transaction_date < end,
            )
        )
        if expense_count:
            raise JarHasExpensesError(f"Hu '{name}' da co expense trong thang hien tai.")

        await session.delete(jar)


async def get_income(user_id: int) -> float | None:
    month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyIncome.amount).where(
                MonthlyIncome.user_id == user_id,
                MonthlyIncome.month == month,
                MonthlyIncome.year == year,
            )
        )
        return result.scalar_one_or_none()


async def list_jars(user_id: int, month: int | None = None, year: int | None = None) -> list[JarStatus]:
    if month is None or year is None:
        month, year = current_month_year()
    start, end = _month_bounds(month, year)
    async with get_session() as session:
        jar_result = await session.execute(
            select(BudgetJar)
            .where(
                BudgetJar.user_id == user_id,
                BudgetJar.month == month,
                BudgetJar.year == year,
            )
            .order_by(BudgetJar.name)
        )
        jars = list(jar_result.scalars().all())

        expense_result = await session.execute(
            select(Expense.jar_name, func.coalesce(func.sum(Expense.amount), 0))
            .where(
                Expense.user_id == user_id,
                Expense.transaction_date >= start,
                Expense.transaction_date < end,
            )
            .group_by(Expense.jar_name)
        )
        spent_by_jar = {name: float(total or 0) for name, total in expense_result.all()}

        return [
            JarStatus(
                name=jar.name,
                budget_amount=float(jar.budget_amount),
                spent_amount=spent_by_jar.get(jar.name, 0.0),
            )
            for jar in jars
        ]


async def add_expense(user_id: int, jar_name: str, amount: float, note: str | None) -> Expense:
    return await add_expense_with_category(user_id, jar_name, amount, note, None)


async def add_expense_with_category(
    user_id: int,
    jar_name: str,
    amount: float,
    note: str | None,
    category: str | None = None,
) -> Expense:
    month, year = current_month_year()
    async with get_session() as session:
        jar_result = await session.execute(
            select(BudgetJar.id).where(
                BudgetJar.user_id == user_id,
                BudgetJar.month == month,
                BudgetJar.year == year,
                BudgetJar.name == jar_name,
            )
        )
        if jar_result.scalar_one_or_none() is None:
            raise JarNotFoundError(f"Hu '{jar_name}' khong ton tai trong thang hien tai.")

        expense = Expense(
            user_id=user_id,
            jar_name=jar_name,
            category=category,
            amount=amount,
            note=note,
            transaction_date=_today(),
        )
        session.add(expense)
        return expense


async def list_expenses(user_id: int, period: str = "month") -> list[ExpenseView]:
    today = _today()
    if period == "today":
        start = today
        end = today + timedelta(days=1)
    elif period == "week":
        start = today - timedelta(days=6)
        end = today + timedelta(days=1)
    else:
        start, end = _current_month_bounds()

    async with get_session() as session:
        result = await session.execute(
            select(Expense)
            .where(
                Expense.user_id == user_id,
                Expense.transaction_date >= start,
                Expense.transaction_date < end,
            )
            .order_by(Expense.transaction_date.desc(), Expense.id.desc())
            .limit(30)
        )
        return [
            ExpenseView(
                id=expense.id,
                jar_name=expense.jar_name,
                category=expense.category,
                amount=float(expense.amount),
                note=expense.note,
                transaction_date=expense.transaction_date,
            )
            for expense in result.scalars().all()
        ]


async def update_expense(user_id: int, expense_id: int, amount: float, note: str | None) -> Expense:
    async with get_session() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.user_id == user_id,
                Expense.id == expense_id,
            )
        )
        expense = result.scalar_one_or_none()
        if expense is None:
            raise ExpenseNotFoundError(f"Expense #{expense_id} khong ton tai.")
        expense.amount = amount
        expense.note = note
        return expense


async def delete_expense(user_id: int, expense_id: int) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Expense).where(
                Expense.user_id == user_id,
                Expense.id == expense_id,
            )
        )
        expense = result.scalar_one_or_none()
        if expense is None:
            raise ExpenseNotFoundError(f"Expense #{expense_id} khong ton tai.")
        await session.delete(expense)


async def get_income_for_month(user_id: int, month: int, year: int) -> float | None:
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyIncome.amount).where(
                MonthlyIncome.user_id == user_id,
                MonthlyIncome.month == month,
                MonthlyIncome.year == year,
            )
        )
        return result.scalar_one_or_none()


async def get_monthly_summary(
    user_id: int,
    require_income: bool = True,
    month: int | None = None,
    year: int | None = None,
) -> MonthlySummary:
    if month is None or year is None:
        month, year = current_month_year()
    income = await get_income_for_month(user_id, month, year)
    if income is None:
        if require_income:
            raise MissingIncomeError("Chua co income cho thang hien tai.")
        income = 0.0

    jars = await list_jars(user_id, month, year)
    total_budget = sum(jar.budget_amount for jar in jars)
    total_expense = sum(jar.spent_amount for jar in jars)
    actual_saving = income - total_expense
    saving_rate = actual_saving / income if income > 0 else 0.0

    return MonthlySummary(
        month=month,
        year=year,
        income=income,
        jars=jars,
        total_budget=total_budget,
        total_expense=total_expense,
        projected_saving=income - total_budget,
        actual_saving=actual_saving,
        saving_rate=saving_rate,
    )


async def get_weekly_spending_by_jar(user_id: int) -> list[JarStatus]:
    today = _today()
    start = today - timedelta(days=6)
    end = today + timedelta(days=1)
    async with get_session() as session:
        result = await session.execute(
            select(Expense.jar_name, func.coalesce(func.sum(Expense.amount), 0))
            .where(
                Expense.user_id == user_id,
                Expense.transaction_date >= start,
                Expense.transaction_date < end,
            )
            .group_by(Expense.jar_name)
            .order_by(func.coalesce(func.sum(Expense.amount), 0).desc())
        )
        return [
            JarStatus(
                name=jar_name or "khong_ro_hu",
                budget_amount=0,
                spent_amount=float(total or 0),
            )
            for jar_name, total in result.all()
        ]


async def export_expenses_csv(user_id: int, export_owner_id: int | None = None) -> tuple[str, bytes]:
    month, year = current_month_year()
    start, end = _month_bounds(month, year)
    async with get_session() as session:
        result = await session.execute(
            select(Expense)
            .where(
                Expense.user_id == user_id,
                or_(
                    (
                        (Expense.transaction_date >= start)
                        & (Expense.transaction_date < end)
                    ),
                    (
                        Expense.transaction_date.is_(None)
                        & (func.date(Expense.created_at) >= start.isoformat())
                        & (func.date(Expense.created_at) < end.isoformat())
                    ),
                ),
            )
            .order_by(
                func.coalesce(Expense.transaction_date, func.date(Expense.created_at)),
                Expense.created_at,
                Expense.id,
            )
        )
        expenses = list(result.scalars().all())

    if not expenses:
        raise NoExportDataError("Khong co expense de export.")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Ngày chi", "Hũ", "Danh mục", "Số tiền", "Ghi chú"])
    for expense in expenses:
        expense_date = expense.transaction_date
        if expense_date is None and expense.created_at is not None:
            expense_date = expense.created_at.date()
        writer.writerow([
            expense_date.strftime("%d/%m/%Y") if expense_date else "",
            expense.jar_name or "",
            expense.category or "",
            f"{expense.amount:.0f}",
            expense.note or "",
        ])

    filename = f"expenses_{export_owner_id or user_id}_{year}_{month:02d}.csv"
    return filename, ("\ufeff" + output.getvalue()).encode("utf-8")
