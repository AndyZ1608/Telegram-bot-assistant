"""Financial coaching helpers for the 6 JARS model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

import config
from database.db import get_session
from database.models import Expense, MonthlyIncome
from services.accounting_service import current_month_year, list_jars
from services.jars_service import JAR_ORDER, days_left_in_month, get_jars_overview


def _today() -> date:
    return datetime.now(ZoneInfo(config.TIMEZONE)).date()


def _month_bounds(month: int, year: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def _previous_month(month: int, year: int) -> tuple[int, int]:
    if month == 1:
        return 12, year - 1
    return month - 1, year


def _days_in_month(month: int, year: int) -> int:
    start, end = _month_bounds(month, year)
    return (end - start).days


@dataclass(frozen=True)
class JarExpenseState:
    has_expense: bool
    spent: float


async def _current_income_record(user_id: int) -> MonthlyIncome | None:
    month, year = current_month_year()
    async with get_session() as session:
        result = await session.execute(
            select(MonthlyIncome).where(
                MonthlyIncome.user_id == user_id,
                MonthlyIncome.month == month,
                MonthlyIncome.year == year,
            )
        )
        return result.scalar_one_or_none()


async def _expense_state_by_jar(user_id: int, month: int | None = None, year: int | None = None) -> dict[str, JarExpenseState]:
    if month is None or year is None:
        month, year = current_month_year()
    start, end = _month_bounds(month, year)
    async with get_session() as session:
        result = await session.execute(
            select(Expense.jar_name, func.coalesce(func.sum(Expense.amount), 0), func.count(Expense.id))
            .where(
                Expense.user_id == user_id,
                Expense.transaction_date >= start,
                Expense.transaction_date < end,
            )
            .group_by(Expense.jar_name)
        )
        return {
            (jar_name or "").upper(): JarExpenseState(
                has_expense=bool(count),
                spent=float(total or 0),
            )
            for jar_name, total, count in result.all()
        }


def build_post_expense_warning(jar) -> str:
    """Return short coaching text after an expense, or an empty string."""
    if jar.budget <= 0:
        return ""

    days = days_left_in_month()
    avg_left = max(jar.remaining, 0) / days
    planned_daily = jar.budget / _days_in_month(*current_month_year())

    if jar.usage_percent >= 100:
        over = abs(jar.remaining)
        if jar.code == "NEC":
            suggestion = "Gợi ý: kiểm tra lại nhóm ăn uống, xăng xe hoặc chi phí phát sinh."
        elif jar.code == "PLAY":
            suggestion = "Gợi ý: giảm ăn ngoài, hẹn hò hoặc giải trí trong vài ngày tới."
        else:
            suggestion = "Gợi ý: tạm dừng khoản không bắt buộc của lọ này."
        return "\n".join([
            "",
            f"Bạn đã vượt {jar.code} {over:,.0f} ₫.".replace(",", "."),
            suggestion,
        ])

    lines: list[str] = []
    if jar.usage_percent >= 80:
        lines.extend([
            "",
            f"Cảnh báo: {jar.code} đã dùng {jar.usage_percent:.0f}% ngân sách tháng này.",
            f"Bạn còn {jar.remaining:,.0f} ₫ cho {days} ngày còn lại.".replace(",", "."),
            f"Trung bình chỉ nên tiêu khoảng {avg_left:,.0f} ₫/ngày.".replace(",", "."),
        ])
    elif jar.remaining > 0 and avg_left < planned_daily * 0.6:
        lines.extend([
            "",
            f"{jar.code} còn {jar.remaining:,.0f} ₫ cho {days} ngày.".replace(",", "."),
            f"Nên giữ mức chi khoảng {avg_left:,.0f} ₫/ngày.".replace(",", "."),
        ])
    return "\n".join(lines)


async def build_allocation_check(user_id: int) -> str:
    states = await _expense_state_by_jar(user_id)
    income = await _current_income_record(user_id)
    days_since_allocate = None
    if income and income.updated_at:
        days_since_allocate = (datetime.utcnow() - income.updated_at.replace(tzinfo=None)).days

    def status(code: str, empty_text: str = "chưa phân bổ") -> str:
        return "đã phân bổ" if states.get(code, JarExpenseState(False, 0)).has_expense else empty_text

    lines = ["Kiểm tra phân bổ tháng này", ""]
    if days_since_allocate is not None:
        lines.append(f"Đã chia thu nhập khoảng {days_since_allocate} ngày trước.")
        lines.append("")
    lines.extend([
        f"FFA: {status('FFA')}",
        f"LTS: {status('LTS')}",
        f"EDU: {status('EDU', 'chưa dùng')}",
        "",
        "Gợi ý:",
    ])

    suggestions = []
    if not states.get("FFA", JarExpenseState(False, 0)).has_expense:
        suggestions.append("- Chuyển FFA sang tài khoản đầu tư riêng nếu đã nhận lương.")
    if not states.get("LTS", JarExpenseState(False, 0)).has_expense:
        suggestions.append("- Chuyển LTS sang tài khoản tiết kiệm/quỹ dự phòng.")
    if not states.get("EDU", JarExpenseState(False, 0)).has_expense:
        suggestions.append("- Dành một khoản nhỏ cho sách, khóa học hoặc học tập trong tháng.")
    if not suggestions:
        suggestions.append("- FFA/LTS/EDU đều đã có giao dịch. Tiếp tục giữ nhịp này.")
    lines.extend(suggestions[:4])
    return "\n".join(lines)


async def build_coach(user_id: int) -> str:
    overview = await get_jars_overview(user_id)
    if overview.income is None:
        return "Bạn chưa chia thu nhập tháng này. Dùng /allocate 30000000 trước."

    states = await _expense_state_by_jar(user_id)
    ok = []
    attention = []
    actions = []
    days = days_left_in_month()

    for jar in overview.jars:
        if jar.usage_percent >= 100:
            attention.append(f"- {jar.code} đã vượt ngân sách {abs(jar.remaining):,.0f} ₫.".replace(",", "."))
        elif jar.usage_percent >= 80:
            attention.append(f"- {jar.code} đã dùng {jar.usage_percent:.0f}%.")
        else:
            ok.append(f"- {jar.code} đang ổn, đã dùng {jar.usage_percent:.0f}%.")

    nec = next((jar for jar in overview.jars if jar.code == "NEC"), None)
    if nec and nec.remaining > 0:
        attention.append(f"- NEC còn {nec.remaining:,.0f} ₫ cho {days} ngày.".replace(",", "."))

    if not states.get("FFA", JarExpenseState(False, 0)).has_expense:
        actions.append("- Chuyển đủ FFA nếu chưa tách sang tài khoản đầu tư riêng.")
    if not states.get("LTS", JarExpenseState(False, 0)).has_expense:
        actions.append("- Chuyển LTS sang tiết kiệm/quỹ dự phòng sớm trong tháng.")
    if not states.get("EDU", JarExpenseState(False, 0)).has_expense:
        actions.append("- Chọn một khoản EDU nhỏ: sách, khóa học hoặc lab học tập.")
    if any(jar.code == "PLAY" and jar.usage_percent >= 80 for jar in overview.jars):
        actions.append("- Giảm ăn ngoài/hẹn hò/giải trí trong 1 tuần tới.")
    if nec and nec.usage_percent >= 80:
        actions.append("- Ưu tiên giữ NEC dưới 90% để tránh thiếu tiền cuối tháng.")
    if not actions:
        actions.append("- Tiếp tục ghi chi tiêu đều, ưu tiên giữ FFA/LTS đúng kế hoạch.")

    lines = ["Coaching tháng này", "", "Tốt:"]
    lines.extend(ok[:3] or ["- Chưa có lọ nào đủ dữ liệu để đánh giá là ổn."])
    lines.extend(["", "Cần chú ý:"])
    lines.extend(attention[:4] or ["- Chưa có cảnh báo lớn."])
    lines.extend(["", "Gợi ý:"])
    lines.extend(actions[:5])
    return "\n".join(lines)


async def build_monthly_jars_report(user_id: int) -> str:
    overview = await get_jars_overview(user_id)
    if overview.income is None:
        return "Bạn chưa chia thu nhập tháng này. Dùng /allocate 30000000 trước."

    total_spent = sum(jar.spent for jar in overview.jars)
    remaining = (overview.income or 0) - total_spent
    saving_rate = remaining / overview.income * 100 if overview.income else 0
    over = [jar for jar in overview.jars if jar.usage_percent >= 100]
    good = [jar for jar in overview.jars if jar.usage_percent <= 80 and jar.remaining > 0]

    lines = [
        "Báo cáo 6 lọ cuối tháng",
        "",
        f"Thu nhập: {overview.income:,.0f} ₫".replace(",", "."),
        f"Tổng chi: {total_spent:,.0f} ₫".replace(",", "."),
        f"Còn lại: {remaining:,.0f} ₫".replace(",", "."),
        f"Tỷ lệ còn lại/thực tế: {saving_rate:.1f}%",
        "",
        "6 lọ:",
    ]
    for jar in overview.jars:
        lines.append(
            f"- {jar.code}: budget {jar.budget:,.0f} ₫, chi {jar.spent:,.0f} ₫, "
            f"còn {jar.remaining:,.0f} ₫, used {jar.usage_percent:.0f}%"
        .replace(",", "."))

    lines.extend(["", "Lọ vượt ngân sách:"])
    lines.extend([f"- {jar.code} vượt {abs(jar.remaining):,.0f} ₫".replace(",", ".") for jar in over] or ["- Không có."])
    lines.extend(["", "Lọ tiết kiệm tốt:"])
    lines.extend([f"- {jar.code} còn {jar.remaining:,.0f} ₫".replace(",", ".") for jar in good[:3]] or ["- Chưa có."])
    lines.extend(["", "Tháng sau nên cân nhắc:"])
    lines.extend(await _ratio_suggestion_lines(user_id, current_only=True))
    return "\n".join(lines)


async def _ratio_suggestion_lines(user_id: int, current_only: bool = False) -> list[str]:
    month, year = current_month_year()
    current = {jar.name.upper(): jar for jar in await list_jars(user_id, month, year)}
    prev_month, prev_year = _previous_month(month, year)
    previous = {} if current_only else {
        jar.name.upper(): jar for jar in await list_jars(user_id, prev_month, prev_year)
    }
    states = await _expense_state_by_jar(user_id, month, year)

    suggestions: list[str] = []
    nec_current = current.get("NEC")
    play_current = current.get("PLAY")
    nec_prev = previous.get("NEC")
    play_prev = previous.get("PLAY")

    if current_only:
        if nec_current and nec_current.usage_ratio >= 1:
            suggestions.append("- Tăng NEC từ 55% lên 60% nếu tiền thuê nhà/ăn uống luôn vượt.")
        if play_current and play_current.usage_ratio >= 1:
            suggestions.append("- Giảm PLAY nếu tháng này vượt quá 100%.")
    else:
        if nec_current and nec_prev and nec_current.usage_ratio >= 1 and nec_prev.usage_ratio >= 1:
            suggestions.append("- NEC vượt 2 tháng liên tiếp: cân nhắc tăng NEC +5% tháng sau.")
        if play_current and play_prev and play_current.usage_ratio >= 1 and play_prev.usage_ratio >= 1:
            suggestions.append("- PLAY vượt 2 tháng liên tiếp: cân nhắc giảm PLAY -5%.")

    if not states.get("FFA", JarExpenseState(False, 0)).has_expense:
        suggestions.append("- FFA chưa có giao dịch: giữ kỷ luật, không tự giảm tỷ lệ đầu tư.")
    if not states.get("LTS", JarExpenseState(False, 0)).has_expense:
        suggestions.append("- LTS chưa có giao dịch: ưu tiên chuyển quỹ dự phòng/tiết kiệm trước.")
    if nec_current and nec_current.usage_ratio < 0.8:
        suggestions.append("- NEC dưới 80%: cân nhắc chuyển phần dư sang FFA/LTS.")
    if not suggestions:
        suggestions.append("- Tỷ lệ hiện tại ổn. Giữ FFA/LTS tối thiểu 20% tổng thu nhập.")
    return suggestions[:5]


async def build_ratio_suggest(user_id: int) -> str:
    lines = ["Gợi ý tỷ lệ tháng sau", ""]
    lines.extend(await _ratio_suggestion_lines(user_id))
    lines.append("")
    lines.append("Bot chỉ gợi ý, không tự thay đổi tỷ lệ.")
    return "\n".join(lines)
