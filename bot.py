"""
Telegram runtime and command handlers for the Phase 0 MVP.
"""

from __future__ import annotations

import html
import io
import logging
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from database.migrations import init_db
from services.accounting_service import (
    ExpenseNotFoundError,
    JarHasExpensesError,
    JarNotFoundError,
    MissingIncomeError,
    NoExportDataError,
    add_expense,
    add_or_update_jar,
    delete_expense,
    delete_jar,
    ensure_user,
    export_expenses_csv,
    get_monthly_summary,
    get_weekly_spending_by_jar,
    list_expenses,
    list_jars,
    set_income,
    update_expense,
    update_jar,
)
from services.gold_price import AUTH_ERROR_MESSAGE, GoldAuthError, get_gold_provider
from services.investment_service import (
    AlertNotFoundError,
    DuplicateSymbolError,
    InvalidConditionError,
    PortfolioNotFoundError,
    SymbolNotFoundError,
    WatchlistNotFoundError,
    add_portfolio_position,
    add_price_alert,
    add_watch_symbol,
    check_price_alerts,
    delete_price_alert,
    list_portfolio,
    list_price_alerts,
    list_watch_quotes,
    remove_portfolio_position,
    remove_watch_symbol,
)
from services.market_data import get_stock_provider
from services.reminder_service import (
    InvalidDayError,
    InvalidTimeError,
    format_settings,
    get_or_create_user_settings,
    update_daily_reminder,
    update_monthly_report,
    update_price_alert_setting,
    update_startup_digest,
)
from services.scheduler_service import start_scheduler, stop_scheduler
from services.silver_price import get_silver_provider
from services.startup_news import (
    UnsupportedTopicError,
    build_startup_digest,
    get_funding,
    get_startup_news,
)
from services.unicorn_service import get_company, search_unicorns
from utils.formatter import format_currency, format_gold_k
from utils.parser import detect_intent, normalize_jar_name, parse_vietnamese_amount
from utils.validators import validate_amount, validate_jar_name, validate_symbol


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


HELP_TEXT = """Các lệnh MVP:
/income <amount>
/jar add <name> <amount>
/jar update <name> <amount>
/jar delete <name>
/jar list
/expense <jar_name> <amount> <note>
/expense list [today|week|month]
/expense update <id> <amount> <note>
/expense delete <id>
/saving
/report [month year]
/weekreport
/stock <symbol>
/gold
/silver
/watch add <symbol>
/watch list
/watch remove <symbol>
/alert add <symbol> above|below <price>
/alert list
/alert check
/alert delete <id>
/portfolio add <symbol> <quantity> <buy_price>
/portfolio list
/portfolio remove <id>
/startup [topic]
/unicorn [keyword]
/company <name>
/funding [topic]
/startup_digest [topic]
/settings
/reminder on|off
/reminder time <HH:MM>
/monthly_report on|off
/monthly_report day <1-28>
/price_alert on|off
/export

Ví dụ:
/income 30000000
/jar add an_uong 2000000
/jar update an_uong 2500000
/expense an_uong 50000 ăn sáng
"""


AMOUNT_AT_END_RE = re.compile(
    r"^(?P<prefix>.+?)\s+(?P<amount>\d+(?:[.,]\d+)?\s*(?:k|tr|triệu|nghìn|ngàn|củ|tỷ|vnd|vnđ|đồng)?)$",
    re.IGNORECASE,
)


def _message(update: Update):
    return update.effective_message


async def _telegram_user_id(update: Update) -> int:
    user = update.effective_user
    if user is None:
        raise RuntimeError("Cannot identify Telegram user.")
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    await ensure_user(user.id, user.username, full_name or None)
    await get_or_create_user_settings(user.id)
    return user.id


def _args_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args or []).strip()


def _parse_amount_or_none(text: str) -> float | None:
    return parse_vietnamese_amount(text)


def _parse_positive_float(text: str) -> float | None:
    try:
        value = float(text.replace(",", "."))
    except (AttributeError, ValueError):
        return None
    return value if value > 0 else None


def _validate_amount_for_reply(amount: float | None) -> str | None:
    if amount is None:
        return "Amount sai định dạng. Ví dụ: 50000, 50k, 2 triệu."
    ok, error = validate_amount(amount)
    return None if ok else error


def _split_name_amount(text: str) -> tuple[str, float | None]:
    match = AMOUNT_AT_END_RE.match(text.strip())
    if not match:
        return "", None
    name = match.group("prefix").strip()
    amount = _parse_amount_or_none(match.group("amount"))
    return name, amount


def _jar_warning(status) -> str:
    if status.usage_ratio > 1:
        return "VUOT NGAN SACH"
    if status.usage_ratio > 0.8:
        return "CANH BAO >80%"
    return "OK"


def _format_percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_jar_line(status) -> str:
    return (
        f"- {status.name}: budget {format_currency(status.budget_amount)}, "
        f"da chi {format_currency(status.spent_amount)}, "
        f"con lai {format_currency(status.remaining_amount)}, "
        f"used {_format_percent(status.usage_ratio)} "
        f"[{_jar_warning(status)}]"
    )


def _format_expense_line(expense) -> str:
    note = f" - {expense.note}" if expense.note else ""
    return (
        f"#{expense.id} {expense.transaction_date:%d/%m} "
        f"{expense.jar_name or 'khong_ro_hu'} "
        f"{format_currency(expense.amount)}{note}"
    )


def _format_quote_line(quote) -> str:
    if quote.error:
        return f"- {quote.symbol}: lỗi provider ({quote.error})"
    return (
        f"- {quote.symbol} {quote.market or ''}: "
        f"{format_currency(quote.price or 0)}, "
        f"{quote.change or 0:,.0f} ({quote.change_percent or 0:.2f}%)"
    )


def _format_alert_line(alert) -> str:
    status = "active" if alert.is_active else "inactive"
    return (
        f"#{alert.id} {alert.symbol} {alert.condition_type} "
        f"{format_currency(alert.target_price)} [{status}]"
    )


def _format_alert_check_line(result) -> str:
    if result.error:
        return f"#{result.id} {result.symbol}: lỗi provider ({result.error})"
    state = "TRIGGERED" if result.triggered else "not yet"
    return (
        f"#{result.id} {result.symbol}: {format_currency(result.current_price or 0)} "
        f"{result.condition_type} {format_currency(result.target_price)} -> {state}"
    )


def _format_portfolio_line(row) -> str:
    if row.error:
        return (
            f"#{row.id} {row.symbol}: qty {row.quantity:g}, "
            f"cost {format_currency(row.cost_value)} - lỗi provider ({row.error})"
        )
    return (
        f"#{row.id} {row.symbol}: qty {row.quantity:g}, "
        f"buy {format_currency(row.buy_price)}, now {format_currency(row.current_price or 0)}, "
        f"value {format_currency(row.market_value or 0)}, "
        f"P/L {format_currency(row.pnl or 0)} ({(row.pnl_percent or 0) * 100:.2f}%)"
    )


def _format_startup_news_item(item: dict) -> str:
    url = item.get("url") or "chưa có link"
    return (
        f"- {item.get('title', 'chưa có tiêu đề')}\n"
        f"  {item.get('summary', 'chưa có tóm tắt')}\n"
        f"  Topic: {item.get('topic', 'chưa có dữ liệu')} | "
        f"Region: {item.get('region', 'chưa có dữ liệu')} | "
        f"Date: {item.get('published_at', 'chưa có dữ liệu')}\n"
        f"  Source: {item.get('source', 'sample/mock data')} | {url}"
    )


def _format_company_item(company: dict) -> str:
    investors = company.get("notable_investors") or []
    investor_text = ", ".join(investors[:3]) if investors else "chưa có dữ liệu"
    return (
        f"{company.get('name', 'N/A')} ({company.get('country', 'chưa có dữ liệu')})\n"
        f"Sector: {company.get('sector', 'chưa có dữ liệu')}\n"
        f"Valuation: {company.get('valuation_usd', 'chưa có dữ liệu')}\n"
        f"Investors: {investor_text}\n"
        f"Website: {company.get('website', 'chưa có dữ liệu')}\n"
        f"{company.get('description', 'chưa có mô tả')}\n"
        "Nguồn: data/unicorns_seed.json (sample/mock data)"
    )


def _format_company_brief(company: dict) -> str:
    return (
        f"- {company.get('name', 'N/A')} ({company.get('country', 'chưa có dữ liệu')}, "
        f"{company.get('sector', 'chưa có dữ liệu')}): "
        f"{company.get('valuation_usd', 'chưa có dữ liệu')}"
    )


def _format_funding_item(item: dict) -> str:
    return (
        f"- {item.get('startup_name', 'chưa có dữ liệu')}: "
        f"{item.get('round', 'chưa có dữ liệu')} | "
        f"{item.get('amount', 'chưa có dữ liệu')}\n"
        f"  Industry: {item.get('industry', 'chưa có dữ liệu')} | "
        f"Region: {item.get('region', 'chưa có dữ liệu')} | "
        f"Date: {item.get('date', 'chưa có dữ liệu')}\n"
        f"  Investor: {item.get('investor', 'chưa có dữ liệu')} | "
        f"Source: {item.get('source', 'sample/mock data')}"
    )


def _parse_month_year(args: list[str]) -> tuple[int | None, int | None, str | None]:
    if not args:
        return None, None, None
    if len(args) != 2:
        return None, None, "Sai cú pháp. Ví dụ: /report 06 2026"
    try:
        month = int(args[0])
        year = int(args[1])
    except ValueError:
        return None, None, "Month/year không hợp lệ. Ví dụ: /report 06 2026"
    if month < 1 or month > 12 or year < 2000 or year > 2100:
        return None, None, "Month/year không hợp lệ. Ví dụ: /report 06 2026"
    return month, year, None


def _format_summary(summary) -> str:
    lines = [
        f"Bao cao thang {summary.month:02d}/{summary.year}",
        f"Income: {format_currency(summary.income)}",
        "",
        "Hu chi tieu:",
    ]
    if summary.jars:
        lines.extend(_format_jar_line(status) for status in summary.jars)
    else:
        lines.append("- Chua co hu chi tieu.")

    lines.extend([
        "",
        f"Tong budget hu: {format_currency(summary.total_budget)}",
        f"Tong da chi: {format_currency(summary.total_expense)}",
        f"Saving du kien: {format_currency(summary.projected_saving)}",
        f"Saving thuc te: {format_currency(summary.actual_saving)}",
        f"Ty le tiet kiem: {summary.saving_rate * 100:.2f}%",
    ])
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    await _message(update).reply_text(
        "Chào bạn. Telegram Assistant Bot đã sẵn sàng cho Phase 0 MVP.\n\n"
        "Gõ /help để xem lệnh."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    await _message(update).reply_text(HELP_TEXT)


async def income_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    text = _args_text(context)
    amount = _parse_amount_or_none(text)
    error = _validate_amount_for_reply(amount)
    if error:
        await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /income 30000000\n{error}")
        return

    await set_income(user_id, amount)
    await _message(update).reply_text(f"Đã lưu income tháng này: {format_currency(amount)}")


async def jar_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if not args:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /jar add an_uong 2000000, /jar update an_uong 2500000, /jar delete an_uong, /jar list")
        return

    action = args[0].lower()
    if action == "list":
        await _send_jar_list(update, user_id)
        return

    if action == "delete":
        if len(args) < 2:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /jar delete an_uong")
            return
        jar_name = normalize_jar_name(" ".join(args[1:]))
        try:
            await delete_jar(user_id, jar_name)
        except JarNotFoundError:
            await _message(update).reply_text(f"Hũ {jar_name} không tồn tại trong tháng hiện tại.")
            return
        except JarHasExpensesError:
            await _message(update).reply_text(
                f"Không thể xóa hũ {jar_name} vì đã có expense. Hãy xóa/chỉnh expense trước."
            )
            return
        await _message(update).reply_text(f"Đã xóa hũ {jar_name}.")
        return

    if action not in {"add", "update"}:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /jar add an_uong 2000000 hoặc /jar list")
        return

    name_raw, amount = _split_name_amount(" ".join(args[1:]))
    if not name_raw:
        await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /jar {action} an_uong 2000000")
        return

    jar_name = normalize_jar_name(name_raw)
    ok, jar_error = validate_jar_name(jar_name)
    amount_error = _validate_amount_for_reply(amount)
    if not ok:
        await _message(update).reply_text(jar_error)
        return
    if amount_error:
        await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /jar {action} an_uong 2000000\n{amount_error}")
        return

    try:
        if action == "update":
            await update_jar(user_id, jar_name, amount)
            await _message(update).reply_text(f"Đã cập nhật hũ {jar_name}: {format_currency(amount)}")
        else:
            await add_or_update_jar(user_id, jar_name, amount)
            await _message(update).reply_text(f"Đã lưu hũ {jar_name}: {format_currency(amount)}")
    except JarNotFoundError:
        await _message(update).reply_text(f"Hũ {jar_name} không tồn tại. Tạo bằng: /jar add {jar_name} <amount>")


async def _send_jar_list(update: Update, user_id: int) -> None:
    jars = await list_jars(user_id)
    if not jars:
        await _message(update).reply_text("Bạn chưa có hũ chi tiêu nào trong tháng này.")
        return
    lines = ["Danh sách hũ tháng này:"]
    lines.extend(_format_jar_line(status) for status in jars)
    await _message(update).reply_text("\n".join(lines))


async def expense_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if args and args[0].lower() == "list":
        period = args[1].lower() if len(args) > 1 else "month"
        if period not in {"today", "week", "month"}:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /expense list today|week|month")
            return
        await _send_expense_list(update, user_id, period)
        return

    if args and args[0].lower() == "delete":
        if len(args) != 2 or not args[1].isdigit():
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /expense delete 12")
            return
        try:
            await delete_expense(user_id, int(args[1]))
        except ExpenseNotFoundError:
            await _message(update).reply_text(f"Không tìm thấy expense #{args[1]} của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa expense #{args[1]}.")
        return

    if args and args[0].lower() == "update":
        if len(args) < 3 or not args[1].isdigit():
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /expense update 12 60000 ăn sáng + cafe")
            return
        amount = _parse_amount_or_none(args[2])
        note_start = 3
        if amount is None and len(args) >= 4:
            amount = _parse_amount_or_none(f"{args[2]} {args[3]}")
            note_start = 4
        amount_error = _validate_amount_for_reply(amount)
        if amount_error:
            await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /expense update 12 60000 ăn sáng\n{amount_error}")
            return
        note = " ".join(args[note_start:]).strip() or None
        try:
            await update_expense(user_id, int(args[1]), amount, note)
        except ExpenseNotFoundError:
            await _message(update).reply_text(f"Không tìm thấy expense #{args[1]} của bạn.")
            return
        await _message(update).reply_text(f"Đã cập nhật expense #{args[1]}: {format_currency(amount)}.")
        return

    if len(args) < 2:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /expense an_uong 50000 ăn sáng")
        return

    jar_name = normalize_jar_name(args[0])
    amount = _parse_amount_or_none(args[1])
    note_start = 2
    if amount is None and len(args) >= 3:
        amount = _parse_amount_or_none(f"{args[1]} {args[2]}")
        note_start = 3
    amount_error = _validate_amount_for_reply(amount)
    if amount_error:
        await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /expense an_uong 50000 ăn sáng\n{amount_error}")
        return

    note = " ".join(args[note_start:]).strip() or None
    try:
        await add_expense(user_id, jar_name, amount, note)
    except JarNotFoundError:
        await _message(update).reply_text(
            f"Hũ {jar_name} không tồn tại trong tháng này. Tạo trước bằng: /jar add {jar_name} <amount>"
        )
        return

    await _message(update).reply_text(
        f"Đã ghi chi tiêu {format_currency(amount)} vào hũ {jar_name}."
    )


async def _send_expense_list(update: Update, user_id: int, period: str) -> None:
    expenses = await list_expenses(user_id, period)
    if not expenses:
        await _message(update).reply_text("Không có expense để hiển thị.")
        return
    title = {
        "today": "Expense hôm nay",
        "week": "Expense 7 ngày gần nhất",
        "month": "Expense tháng này",
    }[period]
    lines = [title]
    lines.extend(_format_expense_line(expense) for expense in expenses)
    await _message(update).reply_text("\n".join(lines))


async def saving_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    try:
        summary = await get_monthly_summary(user_id)
    except MissingIncomeError:
        await _message(update).reply_text("Chưa có income tháng này. Ví dụ: /income 30000000")
        return

    await _message(update).reply_text(
        "\n".join([
            f"Saving tháng {summary.month:02d}/{summary.year}",
            f"Saving dự kiến: {format_currency(summary.projected_saving)}",
            f"Saving thực tế: {format_currency(summary.actual_saving)}",
            f"Tỷ lệ tiết kiệm: {summary.saving_rate * 100:.2f}%",
        ])
    )


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    month, year, parse_error = _parse_month_year(context.args or [])
    if parse_error:
        await _message(update).reply_text(parse_error)
        return
    try:
        summary = await get_monthly_summary(user_id, month=month, year=year)
    except MissingIncomeError:
        await _message(update).reply_text("Chưa có income cho kỳ report này.")
        return
    await _message(update).reply_text(_format_summary(summary))


async def weekreport_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    rows = await get_weekly_spending_by_jar(user_id)
    if not rows:
        await _message(update).reply_text("Chưa có chi tiêu trong 7 ngày gần nhất.")
        return
    total = sum(row.spent_amount for row in rows)
    lines = ["Week report - 7 ngày gần nhất"]
    lines.extend(f"- {row.name}: {format_currency(row.spent_amount)}" for row in rows)
    lines.append(f"Tổng chi: {format_currency(total)}")
    await _message(update).reply_text("\n".join(lines))


async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    symbol = _args_text(context).upper()
    ok, error = validate_symbol(symbol)
    if not ok:
        await _message(update).reply_text(f"Sai cú pháp. Ví dụ: /stock FPT\n{error}")
        return

    try:
        data = await get_stock_provider().get_stock_price(symbol)
    except Exception:
        logger.exception("Stock provider failed")
        await _message(update).reply_text("Provider cổ phiếu đang lỗi. Vui lòng thử lại sau.")
        return

    await _send_stock(update, data, symbol)


async def _send_stock(update: Update, data: dict | None, symbol: str) -> None:
    if not data:
        await _message(update).reply_text(f"Không có dữ liệu cổ phiếu {symbol}.")
        return
    await _message(update).reply_text(
        "\n".join([
            f"Cổ phiếu: {data.get('symbol', symbol)}",
            f"Sàn: {data.get('market', 'N/A')}",
            f"Giá: {format_currency(float(data.get('price', 0)))}",
            f"Thay đổi: {data.get('change', 0):,.0f} ({data.get('change_percent', 0):.2f}%)",
            f"Cập nhật: {data.get('updated_at', 'N/A')}",
            f"Nguồn: {data.get('source', 'N/A')}",
            "Không phải khuyến nghị đầu tư.",
        ])
    )


def _format_gold_value(value: object) -> str:
    return format_gold_k(value)


def _format_gold_table(items: list[dict], group_name: str) -> str:
    label_header = "Loại" if group_name == "SJC" else "Khu vực"
    label_width = max(
        14,
        min(24, max([len(label_header), *[len(str(item.get("label") or "")) for item in items]])),
    )
    buy_width = max(10, max((len(_format_gold_value(item.get("buy"))) for item in items), default=0))
    sell_width = max(10, max((len(_format_gold_value(item.get("sell"))) for item in items), default=0))
    lines = [
        f"{label_header:<{label_width}}  {'Mua vào':>{buy_width}}  {'Bán ra':>{sell_width}}",
    ]
    for item in items:
        label = str(item.get("label") or "")
        buy = _format_gold_value(item.get("buy"))
        sell = _format_gold_value(item.get("sell"))
        lines.append(f"{label:<{label_width}}  {buy:>{buy_width}}  {sell:>{sell_width}}")
    return "\n".join(lines)


def _format_gold_response(data: dict, source_filter: str | None = None) -> str:
    groups = data.get("groups") or {}
    errors = data.get("errors") or {}
    lines = ["Giá vàng SJC hôm nay", ""]
    order = ["SJC"]

    has_item = False
    for group_name in order:
        group = groups.get(group_name)
        items = group.get("items", []) if isinstance(group, dict) else []
        if not items and group_name not in errors:
            continue

        lines.append(group_name)
        if items:
            has_item = True
            table = html.escape(_format_gold_table(items, group_name))
            lines.append(f"<pre>{table}</pre>")
        if group_name in errors and not items:
            lines.append(html.escape(errors[group_name]))
        lines.append("")

    if not has_item:
        return "Không có dữ liệu giá vàng."

    lines.extend([
        f"Nguồn: {html.escape(str(data.get('source', 'N/A')))}",
        f"Cập nhật: {html.escape(str(data.get('updated_at', 'N/A')))}",
        "Không phải khuyến nghị đầu tư.",
    ])
    if data.get("is_mock"):
        lines.append("Ghi chú: mock/sample data.")
    return "\n".join(lines).strip()


async def _send_gold(update: Update, source_filter: str | None = None) -> None:
    if source_filter and source_filter.lower() in {"doji", "pnj"}:
        await _message(update).reply_text("Hiện bot chỉ hỗ trợ giá vàng SJC.")
        return

    try:
        data = await get_gold_provider().get_gold_price("sjc")
    except GoldAuthError:
        await _message(update).reply_text(AUTH_ERROR_MESSAGE)
        return
    except Exception:
        logger.exception("Gold provider failed")
        await _message(update).reply_text("Provider giá vàng đang lỗi. Vui lòng thử lại sau.")
        return

    if not data:
        await _message(update).reply_text("Không có dữ liệu giá vàng.")
        return
    await _message(update).reply_text(_format_gold_response(data, source_filter), parse_mode="HTML")


async def gold_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    args = context.args or []
    source_filter = args[0].lower() if args and args[0].lower() in {"sjc", "doji", "pnj"} else None
    await _send_gold(update, source_filter)


async def silver_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    try:
        data = await get_silver_provider().get_silver_price()
    except Exception:
        logger.exception("Silver provider failed")
        await _message(update).reply_text("Provider giá bạc đang lỗi. Vui lòng thử lại sau.")
        return

    if not data:
        await _message(update).reply_text("Không có dữ liệu giá bạc.")
        return
    await _message(update).reply_text(_format_silver_response(data), parse_mode="HTML")


def _format_silver_response(data: dict) -> str:
    items = data.get("items") or []
    if not items and ("buy" in data or "sell" in data):
        items = [{
            "product": data.get("product") or "Bạc",
            "unit": data.get("unit") or "VND",
            "buy": data.get("buy"),
            "sell": data.get("sell"),
        }]

    if not items:
        return "Không có dữ liệu giá bạc."

    product_width = max(28, max(len(str(item.get("product") or "")) for item in items))
    unit_width = max(10, max(len(str(item.get("unit") or "")) for item in items))
    buy_width = max(9, max(len(format_gold_k(item.get("buy"))) for item in items))
    sell_width = max(8, max(len(format_gold_k(item.get("sell"))) for item in items))

    table_lines = [
        f"{'Loại':<{product_width}}  {'Đơn vị':<{unit_width}}  {'Mua vào':>{buy_width}}  {'Bán ra':>{sell_width}}",
    ]
    for item in items:
        product = str(item.get("product") or "")
        unit = str(item.get("unit") or "VND")
        buy = format_gold_k(item.get("buy"))
        sell = format_gold_k(item.get("sell"))
        table_lines.append(f"{product:<{product_width}}  {unit:<{unit_width}}  {buy:>{buy_width}}  {sell:>{sell_width}}")

    lines = [
        "Giá bạc Phú Quý hôm nay",
        "",
        f"<pre>{html.escape(chr(10).join(table_lines))}</pre>",
        f"Nguồn: {html.escape(str(data.get('source', 'N/A')))}",
        f"Cập nhật: {html.escape(str(data.get('updated_at', 'N/A')))}",
        "Không phải khuyến nghị đầu tư.",
    ]
    if data.get("is_mock"):
        lines.append("Ghi chú: mock/sample data.")
    return "\n".join(lines)


async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    action = args[0].lower() if args else "list"

    if action in {"list", ""}:
        await _send_watchlist(update, user_id)
        return

    if action == "add":
        if len(args) != 2:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /watch add FPT")
            return
        symbol = args[1].upper()
        ok, error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(error)
            return
        try:
            await add_watch_symbol(user_id, symbol)
        except DuplicateSymbolError:
            await _message(update).reply_text(f"{symbol} đã có trong watchlist.")
            return
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        except Exception:
            logger.exception("Add watch symbol failed")
            await _message(update).reply_text("Không thêm được symbol do lỗi provider/database.")
            return
        await _message(update).reply_text(f"Đã thêm {symbol} vào watchlist.")
        return

    if action in {"remove", "delete"}:
        if len(args) != 2:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /watch remove FPT")
            return
        symbol = args[1].upper()
        try:
            await remove_watch_symbol(user_id, symbol)
        except WatchlistNotFoundError:
            await _message(update).reply_text(f"{symbol} không có trong watchlist của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa {symbol} khỏi watchlist.")
        return

    await _message(update).reply_text("Sai cú pháp. Ví dụ: /watch add FPT, /watch list, /watch remove FPT")


async def _send_watchlist(update: Update, user_id: int) -> None:
    quotes = await list_watch_quotes(user_id)
    if not quotes:
        await _message(update).reply_text("Watchlist chưa có dữ liệu. Ví dụ: /watch add FPT")
        return
    lines = ["Watchlist"]
    lines.extend(_format_quote_line(quote) for quote in quotes)
    source = next((quote.source for quote in quotes if quote.source), "provider")
    updated = next((quote.updated_at for quote in quotes if quote.updated_at), "N/A")
    lines.append(f"Nguồn: {source}")
    lines.append(f"Cập nhật: {updated}")
    lines.append("Không phải khuyến nghị đầu tư.")
    await _message(update).reply_text("\n".join(lines))


async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    action = args[0].lower() if args else "list"

    if action == "add":
        if len(args) != 4:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /alert add HPG above 30000")
            return
        symbol = args[1].upper()
        condition = args[2].lower()
        price = _parse_amount_or_none(args[3])
        ok, symbol_error = validate_symbol(symbol)
        amount_error = _validate_amount_for_reply(price)
        if not ok:
            await _message(update).reply_text(symbol_error)
            return
        if amount_error:
            await _message(update).reply_text(f"Giá không hợp lệ. Ví dụ: /alert add HPG above 30000\n{amount_error}")
            return
        try:
            alert = await add_price_alert(user_id, symbol, condition, price)
        except InvalidConditionError:
            await _message(update).reply_text("Condition phải là above hoặc below.")
            return
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        await _message(update).reply_text(
            f"Đã tạo alert #{alert.id}: {symbol} {condition} {format_currency(price)}."
        )
        return

    if action == "list":
        alerts = await list_price_alerts(user_id)
        if not alerts:
            await _message(update).reply_text("Bạn chưa có alert nào.")
            return
        lines = ["Price alerts"]
        lines.extend(_format_alert_line(alert) for alert in alerts)
        await _message(update).reply_text("\n".join(lines))
        return

    if action == "check":
        results = await check_price_alerts(user_id)
        if not results:
            await _message(update).reply_text("Bạn chưa có alert active nào để check.")
            return
        lines = ["Alert check"]
        lines.extend(_format_alert_check_line(result) for result in results)
        lines.append("Không phải khuyến nghị đầu tư.")
        await _message(update).reply_text("\n".join(lines))
        return

    if action in {"delete", "remove"}:
        if len(args) != 2 or not args[1].isdigit():
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /alert delete 3")
            return
        try:
            await delete_price_alert(user_id, int(args[1]))
        except AlertNotFoundError:
            await _message(update).reply_text(f"Không tìm thấy alert #{args[1]} của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa alert #{args[1]}.")
        return

    await _message(update).reply_text("Sai cú pháp. Ví dụ: /alert add HPG above 30000, /alert list, /alert check")


async def portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    action = args[0].lower() if args else "list"

    if action == "add":
        if len(args) != 4:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /portfolio add FPT 100 95000")
            return
        symbol = args[1].upper()
        quantity = _parse_positive_float(args[2])
        buy_price = _parse_amount_or_none(args[3])
        ok, symbol_error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(symbol_error)
            return
        if quantity is None:
            await _message(update).reply_text("Quantity không hợp lệ. Ví dụ: /portfolio add FPT 100 95000")
            return
        amount_error = _validate_amount_for_reply(buy_price)
        if amount_error:
            await _message(update).reply_text(f"Buy price không hợp lệ. Ví dụ: /portfolio add FPT 100 95000\n{amount_error}")
            return
        try:
            position = await add_portfolio_position(user_id, symbol, quantity, buy_price)
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        await _message(update).reply_text(
            f"Đã thêm portfolio #{position.id}: {symbol} qty {quantity:g} giá {format_currency(buy_price)}."
        )
        return

    if action == "list":
        rows = await list_portfolio(user_id)
        if not rows:
            await _message(update).reply_text("Portfolio chưa có dữ liệu. Ví dụ: /portfolio add FPT 100 95000")
            return
        lines = ["Portfolio"]
        lines.extend(_format_portfolio_line(row) for row in rows)
        total_cost = sum(row.cost_value for row in rows)
        total_value = sum(row.market_value or 0 for row in rows)
        lines.append(f"Tổng vốn: {format_currency(total_cost)}")
        lines.append(f"Giá trị hiện tại: {format_currency(total_value)}")
        lines.append(f"Tạm tính P/L: {format_currency(total_value - total_cost)}")
        lines.append("Không phải khuyến nghị đầu tư.")
        await _message(update).reply_text("\n".join(lines))
        return

    if action in {"remove", "delete"}:
        if len(args) != 2 or not args[1].isdigit():
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /portfolio remove 2")
            return
        try:
            await remove_portfolio_position(user_id, int(args[1]))
        except PortfolioNotFoundError:
            await _message(update).reply_text(f"Không tìm thấy portfolio #{args[1]} của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa portfolio #{args[1]}.")
        return

    await _message(update).reply_text("Sai cú pháp. Ví dụ: /portfolio add FPT 100 95000, /portfolio list")


async def startup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    topic = _args_text(context) or "all"
    await _send_startup_news(update, topic)


async def _send_startup_news(update: Update, topic: str = "all") -> None:
    try:
        result = await get_startup_news(topic, limit=5)
    except UnsupportedTopicError:
        await _message(update).reply_text(
            "Topic chưa hỗ trợ. Ví dụ: /startup vn, global, ai, fintech, saas, ecommerce, healthtech, edtech"
        )
        return
    except Exception:
        logger.exception("Startup provider failed")
        await _message(update).reply_text("Provider startup đang lỗi và cache không có dữ liệu fallback.")
        return

    if not result.items:
        await _message(update).reply_text("Không có tin startup theo topic này.")
        return

    cache_note = "cache" if result.from_cache else "provider"
    if result.stale_cache:
        cache_note = "stale cache fallback"
    lines = [
        f"Startup news: {topic}",
        f"Nguồn: {result.source_note} ({cache_note}, sample/mock nếu provider=mock)",
    ]
    lines.extend(_format_startup_news_item(item) for item in result.items)
    await _message(update).reply_text("\n".join(lines))


async def unicorn_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    query = _args_text(context) or None
    country = "Vietnam" if query and query.lower() in {"vn", "vietnam", "viet nam", "việt nam"} else None
    companies = await search_unicorns(query=None if country else query, country=country, limit=5)
    if not companies:
        await _message(update).reply_text("Không tìm thấy công ty kỳ lân trong sample data.")
        return

    lines = ["Unicorn sample data", "Nguồn: data/unicorns_seed.json"]
    for company in companies:
        lines.append(_format_company_brief(company))
    await _message(update).reply_text("\n".join(lines))


async def company_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    name = _args_text(context)
    if not name:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /company OpenAI")
        return
    company = await get_company(name)
    if not company:
        await _message(update).reply_text(f"Không tìm thấy company '{name}' trong sample data.")
        return
    await _message(update).reply_text(_format_company_item(company))


async def funding_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _telegram_user_id(update)
    topic = _args_text(context) or "all"
    try:
        items = await get_funding(topic, limit=5)
    except UnsupportedTopicError:
        await _message(update).reply_text("Topic funding chưa hỗ trợ. Ví dụ: /funding vn, global, ai, fintech")
        return
    except Exception:
        logger.exception("Funding provider failed")
        await _message(update).reply_text("Provider funding đang lỗi.")
        return
    if not items:
        await _message(update).reply_text("Không có funding item theo topic này.")
        return
    lines = [f"Funding sample: {topic}", "Nguồn: startup provider (sample/mock nếu provider=mock)"]
    lines.extend(_format_funding_item(item) for item in items)
    await _message(update).reply_text("\n".join(lines))


async def startup_digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if args and args[0].lower() in {"on", "off", "topic"}:
        action = args[0].lower()
        if action == "on":
            await update_startup_digest(user_id, enabled=True)
            await _message(update).reply_text("Đã bật startup digest định kỳ.")
            return
        if action == "off":
            await update_startup_digest(user_id, enabled=False)
            await _message(update).reply_text("Đã tắt startup digest định kỳ.")
            return
        if len(args) < 2:
            await _message(update).reply_text("Sai cú pháp. Ví dụ: /startup_digest topic ai")
            return
        topic_value = " ".join(args[1:]).strip().lower()
        await update_startup_digest(user_id, topic=topic_value)
        await _message(update).reply_text(f"Đã đặt startup digest topic: {topic_value}.")
        return

    topic = _args_text(context) or "all"
    try:
        digest = await build_startup_digest(topic)
    except UnsupportedTopicError:
        await _message(update).reply_text("Topic digest chưa hỗ trợ. Ví dụ: /startup_digest vn hoặc global")
        return
    except Exception:
        logger.exception("Startup digest failed")
        await _message(update).reply_text("Không tạo được startup digest do provider/cache lỗi.")
        return

    lines = [
        f"Startup digest: {digest['topic']}",
        f"Nguồn: {digest['source_note']} (sample/mock nếu provider=mock)",
        "Top news:",
    ]
    lines.extend(f"- {item.get('title', 'chưa có tiêu đề')}" for item in digest["news"][:5])
    lines.append("Funding:")
    if digest["funding"]:
        lines.extend(
            f"- {item.get('startup_name', 'chưa có dữ liệu')}: {item.get('round', 'chưa có dữ liệu')} {item.get('amount', 'chưa có dữ liệu')}"
            for item in digest["funding"][:3]
        )
    else:
        lines.append("- chưa có dữ liệu")
    lines.append("Companies:")
    if digest["companies"]:
        lines.extend(
            f"- {item.get('name', 'N/A')} ({item.get('sector', 'chưa có dữ liệu')})"
            for item in digest["companies"][:3]
        )
    else:
        lines.append("- chưa có dữ liệu")
    lines.append(f"Trend: {digest['trend']}")
    await _message(update).reply_text("\n".join(lines))


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    settings = await get_or_create_user_settings(user_id)
    await _message(update).reply_text(format_settings(settings))


async def reminder_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if not args:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /reminder on, /reminder off, /reminder time 21:30")
        return
    action = args[0].lower()
    try:
        if action == "on":
            await update_daily_reminder(user_id, enabled=True)
            await _message(update).reply_text("Đã bật nhắc ghi chi tiêu hằng ngày.")
            return
        if action == "off":
            await update_daily_reminder(user_id, enabled=False)
            await _message(update).reply_text("Đã tắt nhắc ghi chi tiêu hằng ngày.")
            return
        if action == "time" and len(args) == 2:
            await update_daily_reminder(user_id, time_value=args[1])
            await _message(update).reply_text(f"Đã đặt giờ nhắc chi tiêu: {args[1]}.")
            return
    except InvalidTimeError:
        await _message(update).reply_text("Time không hợp lệ. Ví dụ: /reminder time 21:30")
        return
    await _message(update).reply_text("Sai cú pháp. Ví dụ: /reminder on, /reminder off, /reminder time 21:30")


async def monthly_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if not args:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /monthly_report on, /monthly_report day 28")
        return
    action = args[0].lower()
    try:
        if action == "on":
            await update_monthly_report(user_id, enabled=True)
            await _message(update).reply_text("Đã bật báo cáo tài chính tháng.")
            return
        if action == "off":
            await update_monthly_report(user_id, enabled=False)
            await _message(update).reply_text("Đã tắt báo cáo tài chính tháng.")
            return
        if action == "day" and len(args) == 2 and args[1].isdigit():
            day = int(args[1])
            await update_monthly_report(user_id, day=day)
            await _message(update).reply_text(f"Đã đặt ngày gửi báo cáo tháng: {day}.")
            return
    except InvalidDayError:
        await _message(update).reply_text("Ngày không hợp lệ. Chọn từ 1 đến 28.")
        return
    await _message(update).reply_text("Sai cú pháp. Ví dụ: /monthly_report on, /monthly_report day 28")


async def price_alert_setting_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    args = context.args or []
    if len(args) != 1 or args[0].lower() not in {"on", "off"}:
        await _message(update).reply_text("Sai cú pháp. Ví dụ: /price_alert on hoặc /price_alert off")
        return
    enabled = args[0].lower() == "on"
    await update_price_alert_setting(user_id, enabled)
    await _message(update).reply_text(f"Đã {'bật' if enabled else 'tắt'} tự động check price alert.")


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    try:
        filename, content = await export_expenses_csv(user_id)
    except NoExportDataError:
        await _message(update).reply_text("Export không có dữ liệu. Hãy ghi expense trước.")
        return

    await _message(update).reply_document(
        document=io.BytesIO(content),
        filename=filename,
        caption="CSV expense tháng hiện tại của bạn.",
    )


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = await _telegram_user_id(update)
    text = (_message(update).text or "").strip()
    intent = detect_intent(text)
    kind = intent.get("intent")

    if kind == "expense_delete":
        expense_id = intent.get("expense_id")
        try:
            await delete_expense(user_id, int(expense_id))
        except (TypeError, ValueError, ExpenseNotFoundError):
            await _message(update).reply_text(f"Không tìm thấy expense #{expense_id} của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa expense #{expense_id}.")
        return

    if kind == "expense_update":
        expense_id = intent.get("expense_id")
        amount = intent.get("amount")
        error = _validate_amount_for_reply(amount)
        if error:
            await _message(update).reply_text(f"Không đọc được amount. Ví dụ: sửa chi tiêu {expense_id} 100k ăn trưa")
            return
        try:
            await update_expense(user_id, int(expense_id), amount, intent.get("note"))
        except (TypeError, ValueError, ExpenseNotFoundError):
            await _message(update).reply_text(f"Không tìm thấy expense #{expense_id} của bạn.")
            return
        await _message(update).reply_text(f"Đã cập nhật expense #{expense_id}: {format_currency(amount)}.")
        return

    if kind == "reminder_set":
        enabled = bool(intent.get("enabled"))
        await update_daily_reminder(user_id, enabled=enabled)
        await _message(update).reply_text(f"Đã {'bật' if enabled else 'tắt'} nhắc ghi chi tiêu hằng ngày.")
        return

    if kind == "reminder_time":
        try:
            await update_daily_reminder(user_id, time_value=intent.get("time"))
        except InvalidTimeError:
            await _message(update).reply_text("Giờ nhắc không hợp lệ. Ví dụ: nhắc tôi ghi chi tiêu lúc 21:30")
            return
        await _message(update).reply_text(f"Đã đặt giờ nhắc chi tiêu: {intent.get('time')}.")
        return

    if kind == "monthly_report_set":
        enabled = bool(intent.get("enabled"))
        await update_monthly_report(user_id, enabled=enabled)
        await _message(update).reply_text(f"Đã {'bật' if enabled else 'tắt'} báo cáo tháng.")
        return

    if kind == "monthly_report_day":
        try:
            await update_monthly_report(user_id, day=int(intent.get("day")))
        except (TypeError, ValueError, InvalidDayError):
            await _message(update).reply_text("Ngày gửi báo cáo không hợp lệ. Chọn từ 1 đến 28.")
            return
        await _message(update).reply_text(f"Đã đặt ngày gửi báo cáo tháng: {intent.get('day')}.")
        return

    if kind == "startup_digest_set":
        enabled = bool(intent.get("enabled"))
        await update_startup_digest(user_id, enabled=enabled)
        await _message(update).reply_text(f"Đã {'bật' if enabled else 'tắt'} startup digest định kỳ.")
        return

    if kind == "startup_digest_topic":
        topic = intent.get("topic") or "vn"
        await update_startup_digest(user_id, topic=topic)
        await _message(update).reply_text(f"Đã đặt startup digest topic: {topic}.")
        return

    if kind == "price_alert_set":
        enabled = bool(intent.get("enabled"))
        await update_price_alert_setting(user_id, enabled)
        await _message(update).reply_text(f"Đã {'bật' if enabled else 'tắt'} tự động check cảnh báo giá.")
        return

    if kind == "income":
        amount = intent.get("amount")
        error = _validate_amount_for_reply(amount)
        if error:
            await _message(update).reply_text(f"Không đọc được income. Ví dụ: Thu nhập tháng này 30 triệu\n{error}")
            return
        await set_income(user_id, amount)
        await _message(update).reply_text(f"Đã lưu income tháng này: {format_currency(amount)}")
        return

    if kind == "jar_add":
        jar_name = normalize_jar_name(intent.get("name") or "")
        amount = intent.get("amount")
        if not jar_name or _validate_amount_for_reply(amount):
            await _message(update).reply_text("Không đọc được hũ. Ví dụ: Tạo hũ ăn uống 2 triệu")
            return
        await add_or_update_jar(user_id, jar_name, amount)
        await _message(update).reply_text(f"Đã lưu hũ {jar_name}: {format_currency(amount)}")
        return

    if kind == "jar_update":
        jar_name = normalize_jar_name(intent.get("name") or "")
        amount = intent.get("amount")
        if not jar_name or _validate_amount_for_reply(amount):
            await _message(update).reply_text("Không đọc được hũ. Ví dụ: đổi hũ ăn uống thành 2500000")
            return
        try:
            await update_jar(user_id, jar_name, amount)
        except JarNotFoundError:
            await _message(update).reply_text(f"Hũ {jar_name} không tồn tại. Tạo bằng: /jar add {jar_name} <amount>")
            return
        await _message(update).reply_text(f"Đã cập nhật hũ {jar_name}: {format_currency(amount)}")
        return

    if kind == "expense":
        if not intent.get("category"):
            await _message(update).reply_text(
                "Mình chưa chắc khoản này thuộc hũ nào. Ghi rõ bằng: /expense <jar_name> <amount> <note>"
            )
            return
        jar_name = normalize_jar_name(intent.get("category"))
        amount = intent.get("amount")
        note = intent.get("note")
        error = _validate_amount_for_reply(amount)
        if error:
            await _message(update).reply_text(error)
            return
        try:
            await add_expense(user_id, jar_name, amount, note)
        except JarNotFoundError:
            await _message(update).reply_text(
                f"Đã nhận dạng hũ {jar_name}, nhưng hũ này chưa tồn tại. "
                f"Tạo trước bằng: /jar add {jar_name} <amount>"
            )
            return
        await _message(update).reply_text(
            f"Đã ghi chi tiêu {format_currency(amount)} vào hũ {jar_name}."
        )
        return

    if kind == "watch_add":
        symbol = (intent.get("symbol") or "").upper()
        ok, error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(error)
            return
        try:
            await add_watch_symbol(user_id, symbol)
        except DuplicateSymbolError:
            await _message(update).reply_text(f"{symbol} đã có trong watchlist.")
            return
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        await _message(update).reply_text(f"Đã thêm {symbol} vào watchlist.")
        return

    if kind == "watch_remove":
        symbol = (intent.get("symbol") or "").upper()
        try:
            await remove_watch_symbol(user_id, symbol)
        except WatchlistNotFoundError:
            await _message(update).reply_text(f"{symbol} không có trong watchlist của bạn.")
            return
        await _message(update).reply_text(f"Đã xóa {symbol} khỏi watchlist.")
        return

    if kind == "alert_add":
        symbol = (intent.get("symbol") or "").upper()
        condition = intent.get("condition_type")
        target_price = intent.get("target_price")
        ok, error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(error)
            return
        amount_error = _validate_amount_for_reply(target_price)
        if amount_error:
            await _message(update).reply_text("Không đọc được giá cảnh báo. Ví dụ: thêm cảnh báo FPT trên 120000")
            return
        try:
            alert = await add_price_alert(user_id, symbol, condition, target_price)
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        await _message(update).reply_text(
            f"Đã tạo alert #{alert.id}: {symbol} {condition} {format_currency(target_price)}."
        )
        return

    if kind == "portfolio_add":
        symbol = (intent.get("symbol") or "").upper()
        quantity = intent.get("quantity")
        buy_price = intent.get("buy_price")
        ok, error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(error)
            return
        if quantity is None or quantity <= 0:
            await _message(update).reply_text("Không đọc được quantity. Ví dụ: thêm portfolio FPT 100 cổ giá 95000")
            return
        amount_error = _validate_amount_for_reply(buy_price)
        if amount_error:
            await _message(update).reply_text("Không đọc được giá mua. Ví dụ: thêm portfolio FPT 100 cổ giá 95000")
            return
        try:
            position = await add_portfolio_position(user_id, symbol, quantity, buy_price)
        except SymbolNotFoundError:
            await _message(update).reply_text(f"Provider chưa có dữ liệu cho mã {symbol}.")
            return
        await _message(update).reply_text(
            f"Đã thêm portfolio #{position.id}: {symbol} qty {quantity:g} giá {format_currency(buy_price)}."
        )
        return

    if kind == "stock":
        symbol = (intent.get("symbol") or "").upper()
        ok, error = validate_symbol(symbol)
        if not ok:
            await _message(update).reply_text(error)
            return
        data = await get_stock_provider().get_stock_price(symbol)
        await _send_stock(update, data, symbol)
        return

    if kind == "gold":
        await _send_gold(update, intent.get("source"))
        return

    if kind == "silver":
        await silver_command(update, context)
        return

    if kind == "startup_news":
        await _send_startup_news(update, intent.get("topic", "all"))
        return

    if kind == "company_lookup":
        company = await get_company(intent.get("name", ""))
        if not company:
            await _message(update).reply_text("Không tìm thấy company trong sample data.")
            return
        await _message(update).reply_text(_format_company_item(company))
        return

    if kind == "unicorn_search":
        query = intent.get("query") or None
        companies = await search_unicorns(
            query=None if query == "vn" else query,
            country="Vietnam" if query == "vn" else None,
            limit=5,
        )
        if not companies:
            await _message(update).reply_text("Không tìm thấy kỳ lân trong sample data.")
            return
        lines = ["Unicorn sample data", "Nguồn: data/unicorns_seed.json"]
        lines.extend(_format_company_brief(company) for company in companies)
        await _message(update).reply_text("\n".join(lines))
        return

    if kind == "funding":
        try:
            items = await get_funding(intent.get("topic", "all"), limit=5)
        except UnsupportedTopicError:
            await _message(update).reply_text("Topic funding chưa hỗ trợ.")
            return
        if not items:
            await _message(update).reply_text("Không có funding item theo topic này.")
            return
        lines = ["Funding sample", "Nguồn: startup provider (sample/mock nếu provider=mock)"]
        lines.extend(_format_funding_item(item) for item in items)
        await _message(update).reply_text("\n".join(lines))
        return

    if kind == "startup_digest":
        try:
            digest = await build_startup_digest(intent.get("topic", "all"))
        except UnsupportedTopicError:
            await _message(update).reply_text("Topic digest chưa hỗ trợ.")
            return
        lines = [
            f"Startup digest: {digest['topic']}",
            f"Nguồn: {digest['source_note']} (sample/mock nếu provider=mock)",
            "Top news:",
        ]
        lines.extend(f"- {item.get('title', 'chưa có tiêu đề')}" for item in digest["news"][:5])
        lines.append("Funding:")
        if digest["funding"]:
            lines.extend(
                f"- {item.get('startup_name', 'chưa có dữ liệu')}: {item.get('round', 'chưa có dữ liệu')} {item.get('amount', 'chưa có dữ liệu')}"
                for item in digest["funding"][:3]
            )
        else:
            lines.append("- chưa có dữ liệu")
        lines.append("Companies:")
        if digest["companies"]:
            lines.extend(_format_company_brief(item) for item in digest["companies"][:3])
        else:
            lines.append("- chưa có dữ liệu")
        lines.append(f"Trend: {digest['trend']}")
        await _message(update).reply_text("\n".join(lines))
        return

    await _message(update).reply_text("Mình chưa hiểu yêu cầu này. Gõ /help để xem lệnh MVP.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Có lỗi hệ thống khi xử lý yêu cầu. Vui lòng thử lại sau."
        )


async def post_init(application: Application) -> None:
    await init_db()
    start_scheduler(application)
    logger.info("Bot initialized")


async def post_shutdown(application: Application) -> None:
    stop_scheduler()
    logger.info("Bot shutdown complete")


def build_application() -> Application:
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN. Please configure it in .env.")

    application = (
        Application.builder()
        .token(config.TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("income", income_command))
    application.add_handler(CommandHandler("jar", jar_command))
    application.add_handler(CommandHandler("expense", expense_command))
    application.add_handler(CommandHandler("saving", saving_command))
    application.add_handler(CommandHandler("report", report_command))
    application.add_handler(CommandHandler("weekreport", weekreport_command))
    application.add_handler(CommandHandler("stock", stock_command))
    application.add_handler(CommandHandler("gold", gold_command))
    application.add_handler(CommandHandler("silver", silver_command))
    application.add_handler(CommandHandler("watch", watch_command))
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("portfolio", portfolio_command))
    application.add_handler(CommandHandler("startup", startup_command))
    application.add_handler(CommandHandler("unicorn", unicorn_command))
    application.add_handler(CommandHandler("company", company_command))
    application.add_handler(CommandHandler("funding", funding_command))
    application.add_handler(CommandHandler("startup_digest", startup_digest_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("reminder", reminder_command))
    application.add_handler(CommandHandler("monthly_report", monthly_report_command))
    application.add_handler(CommandHandler("price_alert", price_alert_setting_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logger.info("Starting Telegram Assistant Bot")
    application = build_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
