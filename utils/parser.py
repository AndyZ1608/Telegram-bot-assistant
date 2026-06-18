"""
Vietnamese NLP Parser for Telegram Assistant Bot.

Provides natural language understanding for Vietnamese financial text,
including amount parsing, intent detection, category classification,
and jar name normalization.
"""

import re
import unicodedata
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
