"""
Vietnamese NLP Parser for Telegram Assistant Bot.

Provides natural language understanding for Vietnamese financial text,
including amount parsing, intent detection, category classification,
and jar name normalization.
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------

# Regex patterns ordered from most specific to least specific to avoid
# partial matches.  We support both shorthand ('50k', '2tr') and full
# Vietnamese words ('triệu', 'nghìn', 'ngàn', 'củ', 'tỷ').
_AMOUNT_PATTERNS: list[tuple[re.Pattern, float]] = [
    # 1.5tr / 2tr / 2TR  (triệu shorthand)
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:tr)\b', re.IGNORECASE), 1_000_000),
    # 50k / 700K  (nghìn shorthand)
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:k)\b', re.IGNORECASE), 1_000),
    # 3 triệu / 30 triệu
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:triệu)\b', re.IGNORECASE), 1_000_000),
    # 500 nghìn / 500 ngàn
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:nghìn|ngàn)\b', re.IGNORECASE), 1_000),
    # 2 củ  (slang for triệu)
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:củ)\b', re.IGNORECASE), 1_000_000),
    # 1 tỷ
    (re.compile(r'(\d+(?:[.,]\d+)?)\s*(?:tỷ)\b', re.IGNORECASE), 1_000_000_000),
]

# Vietnamese-format plain number: 2.000.000  (dots as thousands separators)
_VN_NUMBER_RE = re.compile(r'(?<!\d)(\d{1,3}(?:\.\d{3})+)(?!\d)')

# Fallback plain number (integer or decimal with comma/dot)
_PLAIN_NUMBER_RE = re.compile(r'(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)')


def parse_vietnamese_amount(text: str) -> Optional[float]:
    """Parse a Vietnamese-formatted monetary amount from *text*.

    Supports shorthand notations (``50k``, ``2tr``), full Vietnamese words
    (``triệu``, ``nghìn``, ``ngàn``, ``củ``, ``tỷ``), Vietnamese number
    formatting with dot separators (``2.000.000``), and plain numbers.

    Returns the **first** valid amount found, or ``None`` if no amount can
    be extracted.

    Examples:
        >>> parse_vietnamese_amount('50k')
        50000.0
        >>> parse_vietnamese_amount('2tr')
        2000000.0
        >>> parse_vietnamese_amount('1.5tr')
        1500000.0
        >>> parse_vietnamese_amount('3 triệu')
        3000000.0
        >>> parse_vietnamese_amount('500 nghìn')
        500000.0
        >>> parse_vietnamese_amount('2 củ')
        2000000.0
        >>> parse_vietnamese_amount('1 tỷ')
        1000000000.0
        >>> parse_vietnamese_amount('2.000.000')
        2000000.0
        >>> parse_vietnamese_amount('50000')
        50000.0
        >>> parse_vietnamese_amount('hello')  # no amount
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 1. Try each unit-suffix pattern first
    for pattern, multiplier in _AMOUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            raw = match.group(1).replace(',', '.')
            try:
                return float(raw) * multiplier
            except ValueError:
                continue

    # 2. Try Vietnamese dot-separated thousands: 2.000.000
    vn_match = _VN_NUMBER_RE.search(text)
    if vn_match:
        raw = vn_match.group(1).replace('.', '')
        try:
            return float(raw)
        except ValueError:
            pass

    # 3. Fallback to plain number
    plain_match = _PLAIN_NUMBER_RE.search(text)
    if plain_match:
        raw = plain_match.group(1).replace(',', '.')
        try:
            return float(raw)
        except ValueError:
            pass

    return None


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

# Pre-compiled keyword sets for fast lookup
_INCOME_KEYWORDS = {'thu nhập', 'lương', 'income', 'thu nhap', 'luong'}
_JAR_ADD_KEYWORDS = {'tạo hũ', 'thêm hũ', 'tao hu', 'them hu'}
_JAR_UPDATE_KEYWORDS = {
    'đổi hũ', 'sửa hũ', 'cập nhật hũ',
    'doi hu', 'sua hu', 'cap nhat hu',
}
_STOCK_KEYWORDS = {'giá cổ phiếu', 'check mã', 'cổ phiếu', 'gia co phieu', 'co phieu'}
_GOLD_KEYWORDS = {
    'giá vàng', 'vàng', 'gia vang', 'vang',
    'giá sjc', 'gia sjc', 'giá doji', 'gia doji', 'giá pnj', 'gia pnj',
}
_SILVER_KEYWORDS = {'giá bạc', 'bạc', 'gia bac', 'bac', 'giá bạc phú quý', 'gia bac phu quy'}
_STARTUP_KEYWORDS = {'tin startup', 'startup'}

_JARS_CATEGORY_MAP: dict[str, dict[str, tuple[str, ...]]] = {
    'NEC': {
        'Ăn uống': (
            'ăn sáng', 'ăn trưa', 'ăn tối', 'ăn', 'uống', 'cơm', 'phở', 'bún',
            'cafe thường ngày', 'cà phê thường ngày', 'cafe', 'cà phê',
        ),
        'Nhà thuê': ('tiền nhà', 'thuê nhà', 'nhà thuê'),
        'Hóa đơn': ('điện', 'tiền điện', 'nước', 'tiền nước', 'internet', 'wifi'),
        'Di chuyển': (
            'đổ xăng', 'xăng', 'gửi xe', 'sửa xe', 'bảo dưỡng xe',
            'bảo trì xe',
        ),
        'Y tế': ('thuốc', 'mua thuốc', 'khám bệnh', 'đi khám'),
        'Sinh hoạt': (
            'đi chợ', 'siêu thị', 'rau', 'thịt', 'gạo', 'đồ sinh hoạt',
            'nước giặt', 'dầu gội',
        ),
        'Khác': (),
    },
    'FFA': {
        'Cổ phiếu': (
            'mua cổ phiếu', 'cổ phiếu', 'chứng khoán', 'mua fpt', 'mua hpg',
        ),
        'Quỹ đầu tư': ('quỹ đầu tư', 'quỹ', 'etf'),
        'Vàng đầu tư': ('vàng đầu tư', 'mua vàng đầu tư'),
        'Crypto': ('crypto', 'bitcoin', 'btc', 'eth'),
        'Tài sản khác': ('đầu tư', 'tài sản', 'thu nhập thụ động'),
    },
    'LTS': {
        'Quỹ dự phòng': ('quỹ dự phòng', 'emergency fund', 'dự phòng'),
        'Mục tiêu dài hạn': ('tiết kiệm', 'dài hạn', 'lập gia đình', 'cưới'),
        'Mua nhà': ('mua nhà',),
        'Mua xe': ('mua xe',),
        'Khác': (),
    },
    'EDU': {
        'Sách': ('sách', 'mua sách'),
        'Khóa học': ('khóa học tiếng anh', 'khóa học', 'học', 'training'),
        'Chứng chỉ': ('chứng chỉ', 'thi chứng chỉ'),
        'Lab/Học tập': ('lab', 'network', 'security', 'tiếng anh'),
        'Workshop': ('workshop', 'seminar'),
    },
    'PLAY': {
        'Hẹn hò': ('hẹn hò', 'người yêu'),
        'Bạn bè': ('bạn bè', 'nhậu'),
        'Ăn ngoài': ('ăn ngoài', 'ăn tối với bạn bè'),
        'Du lịch': ('du lịch',),
        'Mua sắm': ('mua đồ thích', 'mua sắm'),
        'Thể thao': ('gym', 'thể thao', 'đá bóng', 'bóng đá'),
        'Giải trí': ('đi chơi', 'xem phim', 'game', 'giải trí', 'cafe chill'),
    },
    'GIVE': {
        'Gia đình': ('gửi bố mẹ', 'gửi mẹ', 'biếu', 'giúp đỡ'),
        'Quà tặng': ('tặng quà', 'quà', 'sinh nhật', 'mừng cưới'),
        'Từ thiện': ('từ thiện', 'ủng hộ'),
        'Cộng đồng': ('cộng đồng',),
        'Khác': (),
    },
}

_JARS_AMBIGUOUS_KEYWORDS: dict[str, dict[str, str]] = {
    'mua đồ': {'PLAY': 'Mua sắm', 'NEC': 'Sinh hoạt'},
    'mua do': {'PLAY': 'Mua sắm', 'NEC': 'Sinh hoạt'},
}

_JARS_DEFAULT_CATEGORY: dict[str, str] = {
    'NEC': 'Khác',
    'FFA': 'Tài sản khác',
    'LTS': 'Khác',
    'EDU': 'Lab/Học tập',
    'PLAY': 'Giải trí',
    'GIVE': 'Khác',
}


def _text_lower(text: str) -> str:
    """Return lower-cased, whitespace-normalized text."""
    return ' '.join(text.lower().split())


def _normalize_for_match(text: str) -> str:
    return _text_lower(_remove_diacritics(text))


def _contains_keyword(normalized_text: str, keyword: str) -> bool:
    normalized_keyword = _normalize_for_match(keyword)
    pattern = rf'(?<!\w){re.escape(normalized_keyword)}(?!\w)'
    return bool(re.search(pattern, normalized_text, flags=re.IGNORECASE))


def _strip_amount_from_note(text: str) -> str:
    note = re.sub(
        r'\d+(?:[.,]\d+)?\s*(?:k|tr|triệu|nghìn|ngàn|củ|tỷ|đồng|vnd|vnđ)?\s*',
        '',
        text,
        flags=re.IGNORECASE,
    ).strip()
    return note or text.strip()


def _find_jars_category_matches(text: str) -> list[dict]:
    normalized = _normalize_for_match(text)
    matches: list[dict] = []

    for jar_code, categories in _JARS_CATEGORY_MAP.items():
        for category, keywords in categories.items():
            for keyword in keywords:
                if _contains_keyword(normalized, keyword):
                    normalized_keyword = _normalize_for_match(keyword)
                    matches.append({
                        'jar': jar_code,
                        'category': category,
                        'keyword': keyword,
                        'score': len(normalized_keyword),
                    })

    # Uppercase ticker purchase shorthand: "mua FPT 2tr", "mua HPG 5tr".
    if re.search(r'(?<!\w)mua\s+[A-Z]{2,10}(?!\w)', text):
        matches.append({
            'jar': 'FFA',
            'category': 'Cổ phiếu',
            'keyword': 'mua <ticker>',
            'score': 40,
        })

    return sorted(matches, key=lambda item: item['score'], reverse=True)


def parse_jars_expense(text: str) -> dict:
    """Parse natural Vietnamese expense text into JARS fields and confidence."""
    amount = parse_vietnamese_amount(text)
    note = _strip_amount_from_note(text) if text else ''

    if amount is None:
        matches = _find_jars_category_matches(text)
        best = matches[0] if matches else {}
        return {
            'intent': 'expense',
            'amount': None,
            'note': note or None,
            'category': best.get('jar'),
            'subcategory': best.get('category'),
            'confidence': 'LOW',
            'category_candidates': {},
            'reason': 'missing_amount',
        }

    normalized = _normalize_for_match(text)
    for keyword, candidates in _JARS_AMBIGUOUS_KEYWORDS.items():
        if _contains_keyword(normalized, keyword):
            return {
                'intent': 'expense',
                'amount': amount,
                'note': note,
                'category': None,
                'subcategory': None,
                'confidence': 'MEDIUM',
                'category_candidates': candidates,
                'reason': 'ambiguous_category',
            }

    matches = _find_jars_category_matches(text)
    if not matches:
        return {
            'intent': 'expense',
            'amount': amount,
            'note': note,
            'category': None,
            'subcategory': None,
            'confidence': 'LOW',
            'category_candidates': {},
            'reason': 'unknown_category',
        }

    best_score = matches[0]['score']
    top_matches = [match for match in matches if match['score'] == best_score]
    top_jars = {match['jar'] for match in top_matches}
    best = top_matches[0]
    confidence = 'HIGH' if len(top_jars) == 1 else 'MEDIUM'

    return {
        'intent': 'expense',
        'amount': amount,
        'note': note,
        'category': best['jar'] if confidence == 'HIGH' else None,
        'subcategory': best['category'] if confidence == 'HIGH' else None,
        'confidence': confidence,
        'category_candidates': {
            match['jar']: match['category'] for match in top_matches
        },
        'reason': 'matched_keyword' if confidence == 'HIGH' else 'ambiguous_keyword',
        'matched_keyword': best['keyword'],
    }


def _extract_stock_symbol(text: str) -> Optional[str]:
    """Extract an uppercase stock ticker symbol from *text*.

    Looks for 1-10 uppercase letter sequences that appear after common
    trigger phrases or standalone.
    """
    # Try to find symbol after keywords
    match = re.search(
        r'(?:cổ phiếu|co phieu|check mã|check ma|mã|ma)\s+([A-Za-z]{1,10})',
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()

    # Fallback: find any standalone uppercase token of 2-10 chars
    tokens = text.split()
    for token in tokens:
        clean = re.sub(r'[^A-Za-z]', '', token)
        if clean and clean.isupper() and 2 <= len(clean) <= 10:
            return clean

    return None


def _extract_stock_symbol_from_price_query(text: str) -> Optional[str]:
    """Extract ticker from short queries like ``Giá FPT hôm nay``."""
    lower = _text_lower(text)
    if not (lower.startswith('giá ') or lower.startswith('gia ')):
        return None
    if any(word in lower for word in _GOLD_KEYWORDS | _SILVER_KEYWORDS):
        return None

    words = text.split()
    if len(words) < 2:
        return None
    candidate = re.sub(r'[^A-Za-z]', '', words[1])
    if 2 <= len(candidate) <= 10:
        return candidate.upper()
    return _extract_stock_symbol(text)


def _extract_gold_source(text: str) -> Optional[str]:
    """Detect source-specific Vietnamese gold queries."""
    lower = _text_lower(text)
    if not (
        lower.startswith('giá ')
        or lower.startswith('gia ')
        or 'vàng' in lower
        or 'vang' in lower
    ):
        return None

    for source in ('sjc', 'doji', 'pnj'):
        if re.search(rf'(?<!\w){source}(?!\w)', lower, flags=re.IGNORECASE):
            return source
    return None


def _extract_startup_topic(text: str) -> Optional[str]:
    """Extract startup news topic from *text*."""
    match = re.search(
        r'(?:tin startup|startup)\s+(\S+)',
        text,
        re.IGNORECASE,
    )
    if match:
        topic = match.group(1).lower()
        # Filter out noise words
        if topic not in {'hôm', 'nay', 'hom', 'ngày', 'ngay', 'mới', 'moi'}:
            return topic
    return None


def _extract_jar_name_from_text(text: str, trigger: str) -> str:
    """Extract jar name that follows *trigger* phrase in *text*."""
    lower = _text_lower(text)
    idx = lower.find(trigger)
    if idx == -1:
        return ''
    after = lower[idx + len(trigger):].strip()
    # Remove amount portion at the end
    after = re.sub(r'\d+(?:[.,]\d+)?\s*(?:k|tr|triệu|nghìn|ngàn|củ|tỷ)?\s*$', '', after, flags=re.IGNORECASE).strip()
    return after


def _extract_jar_update_name(text: str, trigger: str) -> str:
    """Extract jar name from phrases like ``đổi hũ ăn uống thành 2500000``."""
    lower = _text_lower(text)
    idx = lower.find(trigger)
    if idx == -1:
        return ''
    after = lower[idx + len(trigger):].strip()
    after = re.sub(r'\b(?:thành|thanh|lên|len|sang|to)\b', ' ', after, flags=re.IGNORECASE)
    after = re.sub(r'\d+(?:[.,]\d+)?\s*(?:k|tr|triệu|nghìn|ngàn|củ|tỷ)?\s*$', '', after, flags=re.IGNORECASE).strip()
    return after


def _detect_expense_mutation(text: str) -> Optional[dict]:
    """Detect natural-language expense delete/update commands."""
    delete_match = re.search(r'^(?:xóa|xoá|xoa)\s+chi\s+tiêu\s+(\d+)\s*$', text, re.IGNORECASE)
    if delete_match:
        return {
            'intent': 'expense_delete',
            'expense_id': int(delete_match.group(1)),
        }

    update_match = re.search(
        r'^(?:sửa|sua|đổi|doi)\s+chi\s+tiêu\s+(\d+)\s+(.+)$',
        text,
        re.IGNORECASE,
    )
    if update_match:
        payload = update_match.group(2).strip()
        amount = parse_vietnamese_amount(payload)
        note = re.sub(
            r'\d+(?:[.,]\d+)?\s*(?:k|tr|triệu|nghìn|ngàn|củ|tỷ|đồng|vnd|vnđ)?\s*',
            '',
            payload,
            flags=re.IGNORECASE,
        ).strip()
        return {
            'intent': 'expense_update',
            'expense_id': int(update_match.group(1)),
            'amount': amount,
            'note': note or None,
        }

    return None


def _detect_investment_command(text: str) -> Optional[dict]:
    """Detect natural-language investment helper commands."""
    watch_add = re.search(
        r'^(?:thêm|them)\s+([A-Za-z]{2,10})\s+(?:vào|vao)\s+watchlist\s*$',
        text,
        re.IGNORECASE,
    )
    if watch_add:
        return {
            'intent': 'watch_add',
            'symbol': watch_add.group(1).upper(),
        }

    watch_remove = re.search(
        r'^(?:xóa|xoá|xoa)\s+([A-Za-z]{2,10})\s+(?:khỏi|khoi)\s+watchlist\s*$',
        text,
        re.IGNORECASE,
    )
    if watch_remove:
        return {
            'intent': 'watch_remove',
            'symbol': watch_remove.group(1).upper(),
        }

    alert_add = re.search(
        r'^(?:thêm|them)\s+cảnh\s+báo\s+([A-Za-z]{2,10})\s+(trên|tren|dưới|duoi|above|below)\s+(.+)$',
        text,
        re.IGNORECASE,
    )
    if alert_add:
        raw_condition = alert_add.group(2).lower()
        condition = 'above' if raw_condition in {'trên', 'tren', 'above'} else 'below'
        return {
            'intent': 'alert_add',
            'symbol': alert_add.group(1).upper(),
            'condition_type': condition,
            'target_price': parse_vietnamese_amount(alert_add.group(3)),
        }

    portfolio_add = re.search(
        r'^(?:thêm|them)\s+portfolio\s+([A-Za-z]{2,10})\s+(\d+(?:[.,]\d+)?)\s*(?:cổ|co|cp)?\s+(?:giá|gia)\s+(.+)$',
        text,
        re.IGNORECASE,
    )
    if portfolio_add:
        quantity_raw = portfolio_add.group(2).replace(',', '.')
        try:
            quantity = float(quantity_raw)
        except ValueError:
            quantity = None
        return {
            'intent': 'portfolio_add',
            'symbol': portfolio_add.group(1).upper(),
            'quantity': quantity,
            'buy_price': parse_vietnamese_amount(portfolio_add.group(3)),
        }

    return None


def _detect_automation_command(text: str) -> Optional[dict]:
    """Detect natural-language automation/reminder settings commands."""
    reminder_on = re.search(r'^(?:bật|bat)\s+nhắc\s+chi\s+tiêu\s*$', text, re.IGNORECASE)
    if reminder_on:
        return {'intent': 'reminder_set', 'enabled': True}

    reminder_off = re.search(r'^(?:tắt|tat)\s+nhắc\s+chi\s+tiêu\s*$', text, re.IGNORECASE)
    if reminder_off:
        return {'intent': 'reminder_set', 'enabled': False}

    reminder_time = re.search(
        r'^nhắc\s+tôi\s+ghi\s+chi\s+tiêu\s+lúc\s+([0-2]?\d:[0-5]\d)\s*$',
        text,
        re.IGNORECASE,
    )
    if reminder_time:
        hour, minute = reminder_time.group(1).split(':')
        return {'intent': 'reminder_time', 'time': f'{int(hour):02d}:{minute}'}

    monthly_on = re.search(r'^(?:bật|bat)\s+báo\s+cáo\s+tháng\s*$', text, re.IGNORECASE)
    if monthly_on:
        return {'intent': 'monthly_report_set', 'enabled': True}

    monthly_off = re.search(r'^(?:tắt|tat)\s+báo\s+cáo\s+tháng\s*$', text, re.IGNORECASE)
    if monthly_off:
        return {'intent': 'monthly_report_set', 'enabled': False}

    monthly_day = re.search(
        r'^gửi\s+báo\s+cáo\s+tháng\s+ngày\s+(\d{1,2})\s*$',
        text,
        re.IGNORECASE,
    )
    if monthly_day:
        return {'intent': 'monthly_report_day', 'day': int(monthly_day.group(1))}

    digest_on = re.search(r'^(?:bật|bat)\s+startup\s+digest\s*$', text, re.IGNORECASE)
    if digest_on:
        return {'intent': 'startup_digest_set', 'enabled': True}

    digest_topic = re.search(
        r'^startup\s+digest\s+(?:chủ đề|chu de|topic)\s+(.+)$',
        text,
        re.IGNORECASE,
    )
    if digest_topic:
        return {'intent': 'startup_digest_topic', 'topic': digest_topic.group(1).strip().lower()}

    price_alert_on = re.search(r'^(?:bật|bat)\s+cảnh\s+báo\s+giá\s*$', text, re.IGNORECASE)
    if price_alert_on:
        return {'intent': 'price_alert_set', 'enabled': True}

    price_alert_off = re.search(r'^(?:tắt|tat)\s+cảnh\s+báo\s+giá\s*$', text, re.IGNORECASE)
    if price_alert_off:
        return {'intent': 'price_alert_set', 'enabled': False}

    return None


def _clean_startup_topic(raw: str | None) -> Optional[str]:
    if not raw:
        return None
    topic = _text_lower(raw)
    topic = re.sub(r'\b(?:hôm nay|hom nay|tuần này|tuan nay|mới|moi|news)\b', '', topic, flags=re.IGNORECASE)
    topic = topic.strip()
    if not topic:
        return None
    if topic in {'việt nam', 'viet nam', 'vietnam'}:
        return 'vn'
    return topic


def _detect_startup_command(text: str) -> Optional[dict]:
    """Detect natural-language startup assistant commands."""
    lower = _text_lower(text)

    digest_match = re.search(r'^(?:tóm tắt|tom tat)\s+startup(?:\s+(.+))?$', text, re.IGNORECASE)
    if digest_match:
        return {
            'intent': 'startup_digest',
            'topic': _clean_startup_topic(digest_match.group(1)) or 'all',
        }

    company_match = re.search(r'^(?:công ty|cong ty|thông tin|thong tin)\s+(.+)$', text, re.IGNORECASE)
    if company_match:
        return {
            'intent': 'company_lookup',
            'name': company_match.group(1).strip(),
        }

    unicorn_match = re.search(r'^(?:kỳ lân|ky lan)\s+(.+)$', text, re.IGNORECASE)
    if unicorn_match:
        return {
            'intent': 'unicorn_search',
            'query': _clean_startup_topic(unicorn_match.group(1)) or '',
        }

    funding_match = re.search(r'^(?:funding|startup\s+(?:gọi vốn|goi von))(?:\s+(.+))?$', text, re.IGNORECASE)
    if funding_match:
        return {
            'intent': 'funding',
            'topic': _clean_startup_topic(funding_match.group(1)) or 'all',
        }

    news_match = re.search(r'^(?:tin\s+startup)(?:\s+(.+))?$', text, re.IGNORECASE)
    if news_match:
        return {
            'intent': 'startup_news',
            'topic': _clean_startup_topic(news_match.group(1)) or 'all',
        }

    if lower == 'startup':
        return {'intent': 'startup_news', 'topic': 'all'}

    return None


def _detect_jars_coaching_command(text: str) -> Optional[dict]:
    """Detect natural-language JARS coaching commands."""
    normalized = _normalize_for_match(text)
    if normalized == 'xem chot thang':
        return {'intent': 'month_close_preview'}
    if normalized == 'chot thang nay':
        return {'intent': 'month_close_confirm'}
    if normalized == 'tong ket thang nay':
        return {'intent': 'month_summary'}
    if normalized == 'so sanh cac thang':
        return {'intent': 'compare_months'}
    if normalized == 'bat tu dong chot thang':
        return {'intent': 'month_close_auto', 'enabled': True}
    if normalized == 'tat tu dong chot thang':
        return {'intent': 'month_close_auto', 'enabled': False}
    if normalized in {
        'tu van tai chinh thang nay',
        'thang nay toi tieu on khong',
    }:
        return {'intent': 'coach'}
    if normalized == 'kiem tra 6 lo':
        return {'intent': 'allocation_check'}
    if normalized == 'goi y ty le thang sau':
        return {'intent': 'ratio_suggest'}
    if normalized == 'bao cao 6 lo cuoi thang':
        return {'intent': 'monthly_jars_report'}
    return None


# ---------------------------------------------------------------------------
# Rule-based personal-finance parser
# ---------------------------------------------------------------------------

_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "finance_parser_rules.yaml"
_JAR_DISPLAY_NAMES = {
    "NEC": "Chi tiêu cần thiết",
    "FFA": "Tự do tài chính",
    "LTS": "Tiết kiệm dài hạn",
    "EDU": "Giáo dục",
    "PLAY": "Hưởng thụ",
    "GIVE": "Cho đi",
}
_CONFIDENCE_HIGH = "HIGH"
_CONFIDENCE_MEDIUM = "MEDIUM"
_CONFIDENCE_LOW = "LOW"

_INCOME_PHRASES = (
    "thu nhập",
    "lương",
    "nhận lương",
    "được trả lương",
    "thưởng",
    "bonus",
    "hoàn tiền",
    "refund",
)
_FINANCE_ACTION_PREFIXES = (
    "chi",
    "tiêu",
    "mua",
    "trả",
    "đóng",
    "thanh toán",
    "nạp",
    "chuyển",
    "gửi",
    "biếu",
    "tặng",
    "ủng hộ",
    "đầu tư",
    "tiết kiệm",
    "nhận",
    "được trả",
    "lương",
    "thưởng",
    "hoàn tiền",
    "hết",
    "vào",
)
_AMOUNT_TOKEN_RE = re.compile(
    r"""
    (?P<formatted>(?<!\d)\d{1,3}(?:[.,]\d{3})+(?!\d))
    |
    (?P<tr_half>\b\d+\s*(?:tr|triệu)\s*rưỡi\b)
    |
    (?P<tr_tail>\b\d+\s*(?:tr|triệu)\s*\d{1,3}\b)
    |
    (?P<tr_decimal>\b\d+(?:[.,]\d+)?\s*(?:tr|triệu|củ)\b)
    |
    (?P<k>\b\d+(?:[.,]\d+)?\s*(?:k|nghìn|ngàn)\b)
    |
    (?P<ty>\b\d+(?:[.,]\d+)?\s*tỷ\b)
    |
    (?P<plain>(?<!\d)\d{4,}(?!\d))
    """,
    re.IGNORECASE | re.VERBOSE,
)


@lru_cache(maxsize=1)
def load_finance_parser_rules() -> list[dict]:
    """Load finance parser rules from ``data/finance_parser_rules.yaml``.

    The file intentionally uses JSON-compatible YAML so the parser does not
    need an extra runtime dependency.
    """
    data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return list(data.get("rules") or [])


def get_finance_parser_rule_stats() -> dict:
    rules = load_finance_parser_rules()
    jars = {rule.get("jar") for rule in rules}
    categories = {(rule.get("jar"), rule.get("category")) for rule in rules}
    keyword_count = sum(len(rule.get("keywords") or []) for rule in rules)
    alias_count = sum(len(rule.get("aliases") or []) for rule in rules)
    negative_count = sum(len(rule.get("negative_keywords") or []) for rule in rules)
    return {
        "rules": len(rules),
        "jars": len(jars),
        "categories": len(categories),
        "keywords": keyword_count,
        "aliases": alias_count,
        "negative_keywords": negative_count,
    }


def _parse_number_piece(raw: str) -> float | None:
    cleaned = raw.strip().lower().replace(" ", "")
    if not cleaned:
        return None
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", cleaned):
        return float(cleaned.replace(".", "").replace(",", ""))
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _tail_to_vnd(tail: str) -> float:
    digits = re.sub(r"\D", "", tail)
    if not digits:
        return 0.0
    value = int(digits)
    if len(digits) == 1:
        return value * 100_000
    if len(digits) == 2:
        return value * 10_000
    return value * 1_000


def _parse_amount_token(raw: str) -> float | None:
    normalized = _text_lower(raw)
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", normalized):
        return _parse_number_piece(normalized)

    match = re.match(r"(\d+)\s*(?:tr|triệu)\s*rưỡi\b", normalized, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 1_000_000 + 500_000

    match = re.match(r"(\d+)\s*(?:tr|triệu)\s*(\d{1,3})\b", normalized, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 1_000_000 + _tail_to_vnd(match.group(2))

    match = re.match(r"(\d+(?:[.,]\d+)?)\s*(?:tr|triệu|củ)\b", normalized, re.IGNORECASE)
    if match:
        number = _parse_number_piece(match.group(1))
        return None if number is None else number * 1_000_000

    match = re.match(r"(\d+(?:[.,]\d+)?)\s*(?:k|nghìn|ngàn)\b", normalized, re.IGNORECASE)
    if match:
        number = _parse_number_piece(match.group(1))
        return None if number is None else number * 1_000

    match = re.match(r"(\d+(?:[.,]\d+)?)\s*tỷ\b", normalized, re.IGNORECASE)
    if match:
        number = _parse_number_piece(match.group(1))
        return None if number is None else number * 1_000_000_000

    return _parse_number_piece(normalized)


def find_vietnamese_amounts(text: str) -> list[dict]:
    """Return all VND amount tokens found in a sentence with spans."""
    amounts: list[dict] = []
    occupied: list[tuple[int, int]] = []
    for match in _AMOUNT_TOKEN_RE.finditer(text or ""):
        start, end = match.span()
        if any(start < old_end and end > old_start for old_start, old_end in occupied):
            continue
        value = _parse_amount_token(match.group(0))
        if value is None:
            continue
        amounts.append({"amount": float(value), "start": start, "end": end, "raw": match.group(0)})
        occupied.append((start, end))
    return sorted(amounts, key=lambda item: item["start"])


def parse_vietnamese_amount(text: str) -> Optional[float]:
    """Parse the first Vietnamese VND amount from natural text."""
    amounts = find_vietnamese_amounts(text)
    return amounts[0]["amount"] if amounts else None


def _remove_amount_spans(text: str, spans: list[dict]) -> str:
    if not spans:
        return text.strip()
    pieces = []
    cursor = 0
    for span in spans:
        pieces.append(text[cursor:span["start"]])
        cursor = span["end"]
    pieces.append(text[cursor:])
    return "".join(pieces).strip()


def _clean_transaction_note(text: str, amount_spans: list[dict]) -> str:
    note = _remove_amount_spans(text, amount_spans)
    note = re.sub(r"\b(?:tháng này|hôm nay|vào|cho|khoản)\b", " ", note, flags=re.IGNORECASE)
    changed = True
    while changed:
        changed = False
        for prefix in sorted(_FINANCE_ACTION_PREFIXES, key=len, reverse=True):
            pattern = rf"^\s*{re.escape(prefix)}\b\s*"
            new_note = re.sub(pattern, "", note, flags=re.IGNORECASE).strip()
            if new_note != note:
                note = new_note
                changed = True
                break
    note = re.sub(r"\s+", " ", note).strip(" ,.-")
    return note or _remove_amount_spans(text, amount_spans) or text.strip()


def _keyword_hit(normalized_text: str, keyword: str) -> bool:
    keyword_norm = _normalize_for_match(keyword)
    if not keyword_norm:
        return False
    if " " in keyword_norm:
        return keyword_norm in normalized_text
    return bool(re.search(rf"(?<!\w){re.escape(keyword_norm)}(?!\w)", normalized_text))


def _user_alias_matches(text: str, user_aliases: list[dict] | None) -> list[dict]:
    normalized = _normalize_for_match(text)
    matches: list[dict] = []
    for alias in user_aliases or []:
        phrase = alias.get("phrase") or ""
        if not phrase or not _keyword_hit(normalized, phrase):
            continue
        jar = (alias.get("jar_code") or alias.get("jar") or "").upper()
        category = alias.get("category") or "Khác"
        matches.append({
            "jar": jar,
            "category": category,
            "transaction_type": alias.get("transaction_type") or ("allocation" if jar in {"FFA", "LTS"} else "expense"),
            "keyword": phrase,
            "score": 10_000 + len(_normalize_for_match(phrase)),
            "source": "user_alias",
        })
    return matches


def _rule_matches(text: str, user_aliases: list[dict] | None = None) -> list[dict]:
    normalized = _normalize_for_match(text)
    matches = _user_alias_matches(text, user_aliases)
    for rule in load_finance_parser_rules():
        negative_keywords = rule.get("negative_keywords") or []
        if any(_keyword_hit(normalized, keyword) for keyword in negative_keywords):
            continue
        terms = list(rule.get("keywords") or []) + list(rule.get("aliases") or [])
        for term in terms:
            if not _keyword_hit(normalized, term):
                continue
            term_norm = _normalize_for_match(term)
            matches.append({
                "jar": rule.get("jar"),
                "category": rule.get("category"),
                "transaction_type": rule.get("transaction_type") or "expense",
                "keyword": term,
                "score": int(rule.get("priority") or 0) * 100 + len(term_norm),
                "source": "rules",
            })
    if re.search(r"(?<!\w)mua\s+[A-Z]{2,10}(?!\w)", text or ""):
        matches.append({
            "jar": "FFA",
            "category": "Cổ phiếu",
            "transaction_type": "allocation",
            "keyword": "mua <ticker>",
            "score": 10_500,
            "source": "ticker_pattern",
        })
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def _default_candidates() -> list[dict]:
    return [
        {"jar": "NEC", "category": "Sinh hoạt thiết yếu"},
        {"jar": "PLAY", "category": "Mua sắm không thiết yếu"},
        {"jar": "EDU", "category": "Lab/công cụ học tập"},
    ]


def _top_candidates(matches: list[dict], limit: int = 3) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    candidates: list[dict] = []
    for match in matches:
        key = (match.get("jar") or "", match.get("category") or "")
        if key in seen or not key[0]:
            continue
        seen.add(key)
        candidates.append({
            "jar": key[0],
            "category": key[1] or "Khác",
            "transaction_type": match.get("transaction_type") or "expense",
        })
        if len(candidates) >= limit:
            break
    if not candidates:
        candidates = _default_candidates()
    return candidates[:limit]


def _is_income_text(text: str) -> bool:
    normalized = _normalize_for_match(text)
    return any(_keyword_hit(normalized, phrase) for phrase in _INCOME_PHRASES)


def _is_expense_like_text(text: str) -> bool:
    normalized = _normalize_for_match(text)
    if any(_keyword_hit(normalized, prefix) for prefix in _FINANCE_ACTION_PREFIXES):
        return True
    return bool(_rule_matches(text))


def _transaction_from_segment(segment: str, user_aliases: list[dict] | None = None) -> dict:
    amounts = find_vietnamese_amounts(segment)
    amount = amounts[0]["amount"] if amounts else None
    note = _clean_transaction_note(segment, amounts[:1]) if segment else ""

    if amount is not None and _is_income_text(segment):
        return {
            "transaction_type": "income",
            "amount": amount,
            "jar": None,
            "category": None,
            "note": note,
            "confidence": _CONFIDENCE_HIGH,
            "candidates": [],
            "reason": "income_keyword",
        }

    matches = _rule_matches(segment, user_aliases)
    if amount is None:
        return {
            "transaction_type": "expense",
            "amount": None,
            "jar": matches[0]["jar"] if matches else None,
            "category": matches[0]["category"] if matches else None,
            "note": note or segment.strip(),
            "confidence": _CONFIDENCE_LOW,
            "candidates": _top_candidates(matches),
            "reason": "missing_amount",
        }
    if not matches:
        return {
            "transaction_type": "expense",
            "amount": amount,
            "jar": None,
            "category": None,
            "note": note,
            "confidence": _CONFIDENCE_LOW,
            "candidates": _default_candidates(),
            "reason": "unknown_category",
        }

    best = matches[0]
    top_score = best["score"]
    close_matches = [
        match for match in matches
        if top_score - match["score"] <= 500
    ]
    top_keys = {(match["jar"], match["category"]) for match in close_matches}
    segment_norm = _normalize_for_match(segment)
    generic_ambiguous = (
        _keyword_hit(segment_norm, "mua đồ")
        and not _keyword_hit(segment_norm, "mua đồ ăn")
        and not _keyword_hit(segment_norm, "đồ sinh hoạt")
    )
    if len(top_keys) > 1 or generic_ambiguous:
        return {
            "transaction_type": best.get("transaction_type") or "expense",
            "amount": amount,
            "jar": None,
            "category": None,
            "note": note,
            "confidence": _CONFIDENCE_MEDIUM,
            "candidates": _default_candidates() if generic_ambiguous else _top_candidates(matches),
            "reason": "ambiguous_category",
        }

    return {
        "transaction_type": best.get("transaction_type") or "expense",
        "amount": amount,
        "jar": best.get("jar"),
        "category": best.get("category"),
        "note": note,
        "confidence": _CONFIDENCE_HIGH,
        "candidates": _top_candidates(matches),
        "reason": "matched_keyword",
        "matched_keyword": best.get("keyword"),
        "match_source": best.get("source"),
    }


def _split_multi_transaction_text(text: str) -> list[str]:
    amounts = find_vietnamese_amounts(text)
    if len(amounts) <= 1:
        return [text.strip()]
    parts = [part.strip() for part in re.split(r"\s*[;\n,]\s*", text) if part.strip()]
    amount_parts = [part for part in parts if find_vietnamese_amounts(part)]
    if len(amount_parts) >= 2:
        return amount_parts
    return [text.strip()]


def parse_finance_message(text: str, user_aliases: list[dict] | None = None) -> dict:
    """Parse natural personal-finance messages into transaction objects."""
    clean = (text or "").strip()
    if not clean:
        return {"intent": "unknown", "transactions": []}

    if not find_vietnamese_amounts(clean) and not _is_expense_like_text(clean) and not _is_income_text(clean):
        return {"intent": "unknown", "transactions": []}

    transactions = [
        _transaction_from_segment(segment, user_aliases)
        for segment in _split_multi_transaction_text(clean)
    ]
    return {
        "intent": "finance_transactions",
        "transactions": transactions,
        "confidence": min((item["confidence"] for item in transactions), default=_CONFIDENCE_LOW),
        "is_multi": len(transactions) > 1,
    }


def parse_alias_learning(text: str) -> Optional[dict]:
    """Parse user-defined category alias instructions."""
    match = re.match(
        r'^\s*từ\s+giờ\s+["“]?(.+?)["”]?\s+là\s+([A-Za-z]{3,4})\s*(?:-|–|—|:)?\s*(.+?)\s*$',
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "phrase": match.group(1).strip(),
        "jar_code": match.group(2).upper().strip(),
        "category": match.group(3).strip(),
    }


def parse_jars_expense(text: str) -> dict:
    """Backwards-compatible wrapper around the rule-based finance parser."""
    parsed = parse_finance_message(text)
    transactions = parsed.get("transactions") or []
    if not transactions:
        return {
            "intent": "expense",
            "amount": None,
            "note": text,
            "category": None,
            "subcategory": None,
            "confidence": "LOW",
            "category_candidates": {},
            "choices": _default_candidates(),
            "reason": "unknown",
        }
    first = transactions[0]
    candidates = {
        candidate["jar"]: candidate["category"]
        for candidate in first.get("candidates") or []
    }
    return {
        "intent": "expense",
        "transaction_type": first.get("transaction_type") or "expense",
        "amount": first.get("amount"),
        "note": first.get("note"),
        "category": first.get("jar"),
        "subcategory": first.get("category"),
        "confidence": first.get("confidence") or "LOW",
        "category_candidates": candidates,
        "choices": first.get("candidates") or [],
        "reason": first.get("reason"),
        "matched_keyword": first.get("matched_keyword"),
    }


def detect_intent(text: str) -> dict:
    """Detect user intent from natural Vietnamese text.

    Returns a ``dict`` with an ``'intent'`` key and additional parameters
    extracted from the input.

    Supported intents:
        - ``'income'`` – user reports income
        - ``'jar_add'`` – user creates a new budget jar
        - ``'jar_update'`` – user updates an existing jar budget
        - ``'stock'`` – user asks for stock price
        - ``'gold'`` – user asks for gold price
        - ``'silver'`` – user asks for silver price
        - ``'startup_news'`` – user asks for startup news
        - ``'expense'`` – user logs an expense
        - ``'unknown'`` – fallback

    Examples:
        >>> detect_intent('Ăn sáng 50k')
        {'intent': 'expense', 'amount': 50000.0, 'note': 'Ăn sáng', 'category': 'an_uong'}
        >>> detect_intent('Thu nhập tháng này 30 triệu')['intent']
        'income'
        >>> detect_intent('Giá vàng hôm nay')
        {'intent': 'gold'}
    """
    if not text or not text.strip():
        return {'intent': 'unknown'}

    lower = _text_lower(text)

    expense_mutation = _detect_expense_mutation(text)
    if expense_mutation:
        return expense_mutation

    startup_command = _detect_startup_command(text)
    if startup_command:
        return startup_command

    coaching_command = _detect_jars_coaching_command(text)
    if coaching_command:
        return coaching_command

    automation_command = _detect_automation_command(text)
    if automation_command:
        return automation_command

    investment_command = _detect_investment_command(text)
    if investment_command:
        return investment_command

    # --- Income ---
    for kw in _INCOME_KEYWORDS:
        if kw in lower:
            amount = parse_vietnamese_amount(text)
            return {
                'intent': 'income',
                'amount': amount,
                'month': None,
                'year': None,
            }

    # --- Jar add ---
    for kw in _JAR_ADD_KEYWORDS:
        if kw in lower:
            jar_raw = _extract_jar_name_from_text(text, kw)
            amount = parse_vietnamese_amount(text)
            return {
                'intent': 'jar_add',
                'name': normalize_jar_name(jar_raw) if jar_raw else '',
                'amount': amount,
            }

    # --- Jar update ---
    for kw in _JAR_UPDATE_KEYWORDS:
        if kw in lower:
            jar_raw = _extract_jar_update_name(text, kw)
            amount = parse_vietnamese_amount(text)
            return {
                'intent': 'jar_update',
                'name': normalize_jar_name(jar_raw) if jar_raw else '',
                'amount': amount,
            }

    expense_parse = parse_jars_expense(text)
    if expense_parse.get('amount') is not None or expense_parse.get('category'):
        return expense_parse

    # --- Gold ---
    gold_source = _extract_gold_source(text)
    if gold_source:
        return {'intent': 'gold', 'source': gold_source}

    for kw in _GOLD_KEYWORDS:
        if kw in lower:
            return {'intent': 'gold'}

    # --- Stock ---
    for kw in _STOCK_KEYWORDS:
        if kw in lower:
            symbol = _extract_stock_symbol(text)
            return {
                'intent': 'stock',
                'symbol': symbol,
            }

    stock_symbol = _extract_stock_symbol_from_price_query(text)
    if stock_symbol:
        return {
            'intent': 'stock',
            'symbol': stock_symbol,
        }

    # --- Silver ---
    for kw in _SILVER_KEYWORDS:
        if kw in lower:
            return {'intent': 'silver'}

    # --- Startup news ---
    for kw in _STARTUP_KEYWORDS:
        if kw in lower:
            topic = _extract_startup_topic(text)
            result: dict = {'intent': 'startup_news'}
            if topic:
                result['topic'] = topic
            return result

    return {'intent': 'unknown'}


# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

def detect_category(text: str) -> Optional[str]:
    """Map a natural Vietnamese expense sentence to one of the 6 JARS codes."""
    if not text:
        return None

    match = parse_jars_expense(text)
    if match.get('confidence') == 'HIGH':
        return match.get('category')
    return None


# ---------------------------------------------------------------------------
# Jar name normalization
# ---------------------------------------------------------------------------

# Known mappings for common Vietnamese jar names (pre-normalized)
_JAR_NAME_MAP: dict[str, str] = {
    'ăn uống': 'an_uong',
    'an uong': 'an_uong',
    'nhà ở': 'nha_o',
    'nha o': 'nha_o',
    'xăng xe': 'xang_xe',
    'xang xe': 'xang_xe',
    'mua sắm': 'mua_sam',
    'mua sam': 'mua_sam',
    'giải trí': 'giai_tri',
    'giai tri': 'giai_tri',
    'chi phí khác': 'chi_phi_khac',
    'chi phi khac': 'chi_phi_khac',
    'tiết kiệm': 'tiet_kiem',
    'tiet kiem': 'tiet_kiem',
    'giáo dục': 'giao_duc',
    'giao duc': 'giao_duc',
    'sức khỏe': 'suc_khoe',
    'suc khoe': 'suc_khoe',
    'đầu tư': 'dau_tu',
    'dau tu': 'dau_tu',
}


def _remove_diacritics(text: str) -> str:
    """Remove Vietnamese diacritical marks from *text*.

    Uses Unicode NFD decomposition to strip combining characters while
    preserving the base Latin letters.  The special Vietnamese ``đ`` / ``Đ``
    is handled separately since its decomposition does not produce a
    combining mark.
    """
    # Handle đ/Đ explicitly (not decomposed by NFD)
    text = text.replace('đ', 'd').replace('Đ', 'D')
    # Decompose and strip combining marks
    nfkd = unicodedata.normalize('NFD', text)
    return ''.join(ch for ch in nfkd if unicodedata.category(ch) != 'Mn')


def normalize_jar_name(text: str) -> str:
    """Convert a Vietnamese jar name to its normalized internal form.

    Examples:
        >>> normalize_jar_name('ăn uống')
        'an_uong'
        >>> normalize_jar_name('Nhà ở')
        'nha_o'
        >>> normalize_jar_name('xăng xe')
        'xang_xe'
        >>> normalize_jar_name('mua sắm')
        'mua_sam'
        >>> normalize_jar_name('giải trí')
        'giai_tri'
        >>> normalize_jar_name('chi phí khác')
        'chi_phi_khac'
        >>> normalize_jar_name('an_uong')  # already normalized
        'an_uong'
    """
    if not text:
        return ''

    stripped = text.strip().lower()

    # Check direct mapping first
    if stripped in _JAR_NAME_MAP:
        return _JAR_NAME_MAP[stripped]

    # If it already looks normalized (only ASCII + underscores), return as-is
    if re.fullmatch(r'[a-z0-9_]+', stripped):
        return stripped

    # General normalization: remove diacritics → replace spaces with _
    normalized = _remove_diacritics(stripped)
    normalized = re.sub(r'\s+', '_', normalized)
    normalized = re.sub(r'[^a-z0-9_]', '', normalized)
    return normalized
