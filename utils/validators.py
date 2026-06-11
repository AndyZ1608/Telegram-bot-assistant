"""
Validation and Rate Limiting Utilities for Telegram Assistant Bot.

Provides input validation for monetary amounts, jar names, stock symbols,
and an in-memory per-user rate limiter.
"""

import re
import time
from functools import wraps
from typing import Callable

from config import RATE_LIMIT_MESSAGES, RATE_LIMIT_PERIOD


# ---------------------------------------------------------------------------
# Amount validation
# ---------------------------------------------------------------------------

# Maximum allowed amount: 100 tỷ VND
_MAX_AMOUNT: float = 100_000_000_000.0


def validate_amount(amount) -> tuple[bool, str]:
    """Validate a monetary amount.

    Checks that the value is a positive number and does not exceed the
    maximum threshold of 100 tỷ VND.

    Args:
        amount: The value to validate.  Will be coerced to ``float``.

    Returns:
        A ``(is_valid, error_message)`` tuple.  When valid, the error
        message is an empty string.

    Examples:
        >>> validate_amount(50000)
        (True, '')
        >>> validate_amount(-1)
        (False, 'Số tiền phải lớn hơn 0.')
        >>> validate_amount(200_000_000_000)
        (False, 'Số tiền không được vượt quá 100.000.000.000 VND.')
    """
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return False, 'Giá trị không hợp lệ. Vui lòng nhập một số.'

    if value <= 0:
        return False, 'Số tiền phải lớn hơn 0.'

    if value > _MAX_AMOUNT:
        max_fmt = f'{round(_MAX_AMOUNT):,}'.replace(',', '.')
        return False, f'Số tiền không được vượt quá {max_fmt} VND.'

    return True, ''


# ---------------------------------------------------------------------------
# Jar name validation
# ---------------------------------------------------------------------------

_JAR_NAME_RE = re.compile(r'^[a-zA-Z0-9_àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệ'
                          r'ìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữự'
                          r'ỳýỷỹỵđĐ\s]+$')

_MAX_JAR_NAME_LENGTH: int = 50


def validate_jar_name(name: str) -> tuple[bool, str]:
    """Validate a budget jar name.

    Rules:
        - Must not be empty or whitespace-only.
        - Must not exceed 50 characters.
        - Must contain only alphanumeric characters, underscores, spaces,
          and Vietnamese diacritical letters (no other special characters).

    Args:
        name: The jar name to validate.

    Returns:
        A ``(is_valid, error_message)`` tuple.

    Examples:
        >>> validate_jar_name('ăn uống')
        (True, '')
        >>> validate_jar_name('')
        (False, 'Tên hũ không được để trống.')
        >>> validate_jar_name('a' * 51)
        (False, 'Tên hũ không được vượt quá 50 ký tự.')
    """
    if not name or not name.strip():
        return False, 'Tên hũ không được để trống.'

    stripped = name.strip()

    if len(stripped) > _MAX_JAR_NAME_LENGTH:
        return False, f'Tên hũ không được vượt quá {_MAX_JAR_NAME_LENGTH} ký tự.'

    if not _JAR_NAME_RE.match(stripped):
        return False, 'Tên hũ chỉ được chứa chữ cái, số, dấu gạch dưới và khoảng trắng.'

    return True, ''


# ---------------------------------------------------------------------------
# Stock symbol validation
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r'^[A-Z]{3,10}$')


def validate_symbol(symbol: str) -> tuple[bool, str]:
    """Validate a stock ticker symbol.

    Rules:
        - Must consist of 3 to 10 uppercase ASCII letters.

    Args:
        symbol: The stock symbol to validate.

    Returns:
        A ``(is_valid, error_message)`` tuple.

    Examples:
        >>> validate_symbol('FPT')
        (True, '')
        >>> validate_symbol('fpt')
        (False, 'Mã cổ phiếu phải là 3-10 chữ cái viết hoa.')
        >>> validate_symbol('AB')
        (False, 'Mã cổ phiếu phải là 3-10 chữ cái viết hoa.')
    """
    if not symbol or not symbol.strip():
        return False, 'Mã cổ phiếu không được để trống.'

    stripped = symbol.strip()

    if not _SYMBOL_RE.match(stripped):
        return False, 'Mã cổ phiếu phải là 3-10 chữ cái viết hoa.'

    return True, ''


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

# In-memory store: user_id → list of request timestamps
_user_timestamps: dict[int, list[float]] = {}


def _cleanup_timestamps(user_id: int, now: float) -> None:
    """Remove timestamps older than the rate-limit window for *user_id*."""
    if user_id not in _user_timestamps:
        return
    cutoff = now - RATE_LIMIT_PERIOD
    _user_timestamps[user_id] = [
        ts for ts in _user_timestamps[user_id] if ts > cutoff
    ]


def check_rate_limit(user_id: int) -> bool:
    """Check whether *user_id* is within the configured rate limit.

    Records the current timestamp and returns ``True`` if the user has
    sent fewer than ``RATE_LIMIT_MESSAGES`` messages within the last
    ``RATE_LIMIT_PERIOD`` seconds.  Returns ``False`` if the user has
    exceeded the limit.

    This is a simple in-memory rate limiter suitable for single-process
    deployments.  For multi-process setups, consider using Redis.

    Args:
        user_id: The Telegram user ID.

    Returns:
        ``True`` if the request is allowed, ``False`` if rate-limited.

    Examples:
        >>> check_rate_limit(12345)
        True
    """
    now = time.time()
    _cleanup_timestamps(user_id, now)

    if user_id not in _user_timestamps:
        _user_timestamps[user_id] = []

    if len(_user_timestamps[user_id]) >= RATE_LIMIT_MESSAGES:
        return False

    _user_timestamps[user_id].append(now)
    return True


def get_rate_limit_remaining(user_id: int) -> int:
    """Return the number of requests remaining for *user_id* in the
    current rate-limit window.

    Args:
        user_id: The Telegram user ID.

    Returns:
        Number of remaining allowed requests (non-negative).
    """
    now = time.time()
    _cleanup_timestamps(user_id, now)

    current = len(_user_timestamps.get(user_id, []))
    return max(0, RATE_LIMIT_MESSAGES - current)


def reset_rate_limit(user_id: int) -> None:
    """Reset the rate-limit counter for *user_id*.

    Useful for admin overrides or testing.
    """
    _user_timestamps.pop(user_id, None)


def rate_limit(func: Callable) -> Callable:
    """Decorator that enforces rate limiting on async handler functions.

    The decorated function must accept a first positional argument that
    has a ``from_user.id`` attribute (i.e. an ``aiogram`` ``Message`` or
    ``CallbackQuery`` object).

    If the user exceeds the rate limit, the handler is skipped and a
    warning message is sent via ``message.answer()``.

    Usage::

        @rate_limit
        async def handle_expense(message: Message):
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Extract message from positional args
        message = args[0] if args else kwargs.get('message')
        if message is None:
            return await func(*args, **kwargs)

        user_id = getattr(getattr(message, 'from_user', None), 'id', None)
        if user_id is None:
            return await func(*args, **kwargs)

        if not check_rate_limit(user_id):
            remaining_seconds = RATE_LIMIT_PERIOD
            await message.answer(
                f'⏳ Bạn đã gửi quá nhiều tin nhắn. '
                f'Vui lòng đợi {remaining_seconds} giây.'
            )
            return None

        return await func(*args, **kwargs)

    return wrapper
