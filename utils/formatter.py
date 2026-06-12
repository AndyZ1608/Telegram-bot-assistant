"""
Output Formatting Utilities for Telegram Assistant Bot.

Provides functions to format monetary values, dates, reports, and
market data into human-readable Vietnamese strings suitable for
Telegram messages.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Union


# ---------------------------------------------------------------------------
# Display name mapping  (internal key → Vietnamese display name)
# ---------------------------------------------------------------------------

_DISPLAY_NAMES: dict[str, str] = {
    'an_uong': 'Ăn uống',
    'nha_o': 'Nhà ở',
    'xang_xe': 'Xăng xe',
    'mua_sam': 'Mua sắm',
    'giai_tri': 'Giải trí',
    'chi_phi_khac': 'Chi phí khác',
    'tiet_kiem': 'Tiết kiệm',
    'giao_duc': 'Giáo dục',
    'suc_khoe': 'Sức khỏe',
    'dau_tu': 'Đầu tư',
}


# ---------------------------------------------------------------------------
# Currency & number formatting
# ---------------------------------------------------------------------------

def format_currency(amount: float) -> str:
    """Format a numeric amount as Vietnamese currency.

    Uses dots as thousands separators and appends ``VND``.

    Examples:
        >>> format_currency(1500000)
        '1.500.000 VND'
        >>> format_currency(50000)
        '50.000 VND'
        >>> format_currency(0)
        '0 VND'
        >>> format_currency(1234.5)
        '1.235 VND'
    """
    if amount == 0:
        return '0 VND'

    # Round to nearest integer for display
    rounded = round(abs(amount))
    formatted = f'{rounded:,}'.replace(',', '.')
    if amount < 0:
        formatted = f'-{formatted}'
    return f'{formatted} VND'


def format_gold_k(value: object) -> str:
    """Format raw VND gold price as thousands of VND.

    Examples:
        >>> format_gold_k(142400000.0)
        '142.400K'
        >>> format_gold_k('98510786.0786')
        '98.511K'
    """
    amount = _parse_gold_decimal(value)
    if amount is None:
        return '-'

    thousands = (amount / Decimal('1000')).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    formatted = f'{int(thousands):,}'.replace(',', '.')
    return f'{formatted}K'


def _parse_gold_decimal(value: object) -> Decimal | None:
    if value in (None, ''):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    raw = str(value).strip()
    if not raw:
        return None

    cleaned = re.sub(r'[^0-9,.\-]', '', raw)
    if not cleaned or cleaned in {'-', '.', ','}:
        return None

    try:
        return Decimal(_normalize_gold_number(cleaned))
    except InvalidOperation:
        return None


def _normalize_gold_number(value: str) -> str:
    if ',' in value and '.' in value:
        if value.rfind(',') > value.rfind('.'):
            return value.replace('.', '').replace(',', '.')
        return value.replace(',', '')

    if ',' in value:
        parts = value.split(',')
        if len(parts) > 2:
            return ''.join(parts)
        if len(parts[-1]) == 3 and len(parts[0]) <= 3:
            return ''.join(parts)
        return value.replace(',', '.')

    if value.count('.') > 1:
        parts = value.split('.')
        if all(len(part) == 3 for part in parts[1:]):
            return ''.join(parts)
        return ''.join(parts[:-1]) + '.' + parts[-1]

    if '.' in value:
        before, after = value.split('.', 1)
        if len(after) == 3 and len(before) <= 3:
            return before + after

    return value


def format_percentage(value: float) -> str:
    """Format a decimal value as a percentage string.

    Examples:
        >>> format_percentage(0.8016)
        '80.16%'
        >>> format_percentage(1.0)
        '100.00%'
        >>> format_percentage(0.5)
        '50.00%'
    """
    return f'{value * 100:.2f}%'


# ---------------------------------------------------------------------------
# Date formatting
# ---------------------------------------------------------------------------

def format_date(dt: Union[datetime, None]) -> str:
    """Format a ``datetime`` object to ``dd/mm/yyyy``.

    Returns an empty string if *dt* is ``None``.

    Examples:
        >>> from datetime import datetime
        >>> format_date(datetime(2026, 6, 11))
        '11/06/2026'
    """
    if dt is None:
        return ''
    return dt.strftime('%d/%m/%Y')


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def format_report_header(month: int, year: int) -> str:
    """Return a styled header line for a monthly financial report.

    Example:
        >>> format_report_header(6, 2026)
        '📊 BÁO CÁO TÀI CHÍNH THÁNG 06/2026'
    """
    return f'📊 BÁO CÁO TÀI CHÍNH THÁNG {month:02d}/{year}'


def format_income_section(amount: float) -> str:
    """Return a formatted income section for the monthly report.

    Example:
        >>> format_income_section(30000000)
        '💰 Thu nhập:\\n• 30.000.000 VND'
    """
    return f'💰 Thu nhập:\n• {format_currency(amount)}'


def format_jar_status(name: str, spent: float, budget: float) -> str:
    """Return a formatted jar status line with appropriate emoji warnings.

    Warning levels:
        - Normal (≤80% spent): plain bullet
        - Warning (>80% and ≤100%): ⚠️ prefix
        - Over budget (>100%): 🔴 prefix with overspend amount

    Args:
        name: Internal jar name (e.g. ``'an_uong'``).
        spent: Total amount spent in the jar.
        budget: Budget allocated to the jar.

    Examples:
        >>> format_jar_status('an_uong', 500000, 2000000)
        '• Ăn uống: 500.000/2.000.000 VND, còn 1.500.000 VND'
        >>> format_jar_status('xang_xe', 900000, 1000000)
        '⚠️ Xăng xe: 900.000/1.000.000 VND, còn 100.000 VND'
        >>> format_jar_status('mua_sam', 1200000, 1000000)
        '🔴 Mua sắm: 1.200.000/1.000.000 VND, vượt 200.000 VND'
    """
    disp = display_jar_name(name)
    spent_fmt = f'{round(abs(spent)):,}'.replace(',', '.')
    budget_fmt = f'{round(abs(budget)):,}'.replace(',', '.')

    if budget <= 0:
        # Avoid division by zero – treat as over budget
        return f'🔴 {disp}: {spent_fmt}/{budget_fmt} VND'

    ratio = spent / budget

    if ratio > 1.0:
        over = spent - budget
        over_fmt = f'{round(over):,}'.replace(',', '.')
        return f'🔴 {disp}: {spent_fmt}/{budget_fmt} VND, vượt {over_fmt} VND'
    elif ratio > 0.8:
        remaining = budget - spent
        remaining_fmt = f'{round(remaining):,}'.replace(',', '.')
        return f'⚠️ {disp}: {spent_fmt}/{budget_fmt} VND, còn {remaining_fmt} VND'
    else:
        remaining = budget - spent
        remaining_fmt = f'{round(remaining):,}'.replace(',', '.')
        return f'• {disp}: {spent_fmt}/{budget_fmt} VND, còn {remaining_fmt} VND'


# ---------------------------------------------------------------------------
# Display name helper
# ---------------------------------------------------------------------------

def display_jar_name(name: str) -> str:
    """Convert an internal jar name to its Vietnamese display form.

    Falls back to title-casing the name with underscores replaced by spaces
    if no known mapping exists.

    Examples:
        >>> display_jar_name('an_uong')
        'Ăn uống'
        >>> display_jar_name('nha_o')
        'Nhà ở'
        >>> display_jar_name('custom_jar')
        'Custom Jar'
    """
    return _DISPLAY_NAMES.get(name, name.replace('_', ' ').title())


# ---------------------------------------------------------------------------
# Market data formatting
# ---------------------------------------------------------------------------

def format_stock_info(data: dict) -> str:
    """Format stock market data into a Telegram-friendly message.

    Expected *data* keys:
        - ``symbol`` (str): Ticker symbol
        - ``price`` (float): Current price
        - ``change`` (float): Price change
        - ``change_percent`` (float): Percentage change (0-100 scale)
        - ``volume`` (int, optional): Trading volume
        - ``high`` (float, optional): Day high
        - ``low`` (float, optional): Day low
        - ``open`` (float, optional): Opening price
        - ``time`` (str, optional): Last update time

    Returns a formatted multi-line string with emoji indicators.
    """
    if not data:
        return '❌ Không có dữ liệu cổ phiếu.'

    symbol = data.get('symbol', '???')
    price = data.get('price', 0)
    change = data.get('change', 0)
    change_pct = data.get('change_percent', 0)

    # Trend emoji
    if change > 0:
        trend = '🟢 ▲'
        sign = '+'
    elif change < 0:
        trend = '🔴 ▼'
        sign = ''
    else:
        trend = '🟡 ─'
        sign = ''

    lines = [
        f'📈 Cổ phiếu {symbol}',
        f'━━━━━━━━━━━━━━━━━━',
        f'{trend} Giá: {price:,.2f}',
        f'📊 Thay đổi: {sign}{change:,.2f} ({sign}{change_pct:.2f}%)',
    ]

    if 'volume' in data and data['volume'] is not None:
        vol = f'{data["volume"]:,}'.replace(',', '.')
        lines.append(f'📉 Khối lượng: {vol}')

    if 'high' in data and data['high'] is not None:
        lines.append(f'⬆️ Cao nhất: {data["high"]:,.2f}')

    if 'low' in data and data['low'] is not None:
        lines.append(f'⬇️ Thấp nhất: {data["low"]:,.2f}')

    if 'open' in data and data['open'] is not None:
        lines.append(f'🔓 Mở cửa: {data["open"]:,.2f}')

    if 'time' in data and data['time']:
        lines.append(f'🕐 Cập nhật: {data["time"]}')

    return '\n'.join(lines)


def format_gold_info(data: dict) -> str:
    """Format gold price data into a Telegram-friendly message.

    Expected *data* keys:
        - ``buy_price`` (float): Buying price
        - ``sell_price`` (float): Selling price
        - ``brand`` (str, optional): Gold brand name
        - ``type`` (str, optional): Gold type (SJC, 9999, etc.)
        - ``change`` (float, optional): Price change
        - ``time`` (str, optional): Last update time
        - ``unit`` (str, optional): Price unit (default: VND/lượng)

    Returns a formatted multi-line string.
    """
    if not data:
        return '❌ Không có dữ liệu giá vàng.'

    unit = data.get('unit', 'VND/lượng')
    brand = data.get('brand', '')
    gold_type = data.get('type', '')

    header = '🥇 Giá vàng'
    if brand:
        header += f' {brand}'
    if gold_type:
        header += f' ({gold_type})'

    buy = data.get('buy_price', 0)
    sell = data.get('sell_price', 0)

    buy_fmt = f'{round(buy):,}'.replace(',', '.')
    sell_fmt = f'{round(sell):,}'.replace(',', '.')

    lines = [
        header,
        '━━━━━━━━━━━━━━━━━━',
        f'💰 Mua vào: {buy_fmt} {unit}',
        f'💸 Bán ra: {sell_fmt} {unit}',
    ]

    if 'change' in data and data['change'] is not None:
        change = data['change']
        change_fmt = f'{round(abs(change)):,}'.replace(',', '.')
        if change > 0:
            lines.append(f'📈 Thay đổi: +{change_fmt}')
        elif change < 0:
            lines.append(f'📉 Thay đổi: -{change_fmt}')
        else:
            lines.append('➡️ Thay đổi: 0')

    if 'time' in data and data['time']:
        lines.append(f'🕐 Cập nhật: {data["time"]}')

    return '\n'.join(lines)


def format_silver_info(data: dict) -> str:
    """Format silver price data into a Telegram-friendly message.

    Expected *data* keys:
        - ``buy_price`` (float): Buying price
        - ``sell_price`` (float): Selling price
        - ``change`` (float, optional): Price change
        - ``time`` (str, optional): Last update time
        - ``unit`` (str, optional): Price unit (default: VND/lượng)

    Returns a formatted multi-line string.
    """
    if not data:
        return '❌ Không có dữ liệu giá bạc.'

    unit = data.get('unit', 'VND/lượng')

    buy = data.get('buy_price', 0)
    sell = data.get('sell_price', 0)

    buy_fmt = f'{round(buy):,}'.replace(',', '.')
    sell_fmt = f'{round(sell):,}'.replace(',', '.')

    lines = [
        '🥈 Giá bạc',
        '━━━━━━━━━━━━━━━━━━',
        f'💰 Mua vào: {buy_fmt} {unit}',
        f'💸 Bán ra: {sell_fmt} {unit}',
    ]

    if 'change' in data and data['change'] is not None:
        change = data['change']
        change_fmt = f'{round(abs(change)):,}'.replace(',', '.')
        if change > 0:
            lines.append(f'📈 Thay đổi: +{change_fmt}')
        elif change < 0:
            lines.append(f'📉 Thay đổi: -{change_fmt}')
        else:
            lines.append('➡️ Thay đổi: 0')

    if 'time' in data and data['time']:
        lines.append(f'🕐 Cập nhật: {data["time"]}')

    return '\n'.join(lines)
