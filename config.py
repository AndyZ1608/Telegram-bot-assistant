"""
Configuration module for the Telegram Assistant Bot.

Loads environment variables from a .env file and provides
centralized access to all configuration settings including
API keys, database URLs, rate limiting, and category mappings.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _normalize_database_url(url: str) -> str:
    """Accept common SQLite URLs while keeping SQLAlchemy async-compatible."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url

# Bot
TELEGRAM_BOT_TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')

# Database
DATABASE_URL: str = _normalize_database_url(os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///bot.db'))

# Timezone
TIMEZONE: str = os.getenv('TIMEZONE', 'Asia/Ho_Chi_Minh')
DEFAULT_TIMEZONE: str = os.getenv('DEFAULT_TIMEZONE', TIMEZONE)

# API Keys
STOCK_API_KEY: str = os.getenv('STOCK_API_KEY', '')
GOLD_API_KEY: str = os.getenv('GOLD_API_KEY', '')
SILVER_API_KEY: str = os.getenv('SILVER_API_KEY', '')
NEWS_API_KEY: str = os.getenv('NEWS_API_KEY', '')

# Providers
MARKET_PROVIDER: str = os.getenv('MARKET_PROVIDER', 'mock').lower()
GOLD_PROVIDER: str = os.getenv('GOLD_PROVIDER', 'vnappmob').lower()
VNAPPMOB_GOLD_API_KEY: str = os.getenv('VNAPPMOB_GOLD_API_KEY', '')
VNAPPMOB_GOLD_BASE_URL: str = os.getenv('VNAPPMOB_GOLD_BASE_URL', 'https://api.vnappmob.com').rstrip('/')
VNAPPMOB_GOLD_TIMEOUT: float = float(os.getenv('VNAPPMOB_GOLD_TIMEOUT', '10'))
VNAPPMOB_AUTO_REFRESH_GOLD_KEY: bool = (
    os.getenv('VNAPPMOB_AUTO_REFRESH_GOLD_KEY', 'false').lower() in {'1', 'true', 'yes', 'on'}
)
STARTUP_NEWS_PROVIDER: str = os.getenv('STARTUP_NEWS_PROVIDER', 'mock').lower()
STARTUP_CACHE_TTL_MINUTES: int = int(os.getenv('STARTUP_CACHE_TTL_MINUTES', '60'))
ENABLE_SCHEDULER: bool = os.getenv('ENABLE_SCHEDULER', 'true').lower() in {'1', 'true', 'yes', 'on'}

# Rate limiting
RATE_LIMIT_MESSAGES: int = int(os.getenv('RATE_LIMIT_MESSAGES', '20'))
RATE_LIMIT_PERIOD: int = int(os.getenv('RATE_LIMIT_PERIOD', '60'))  # seconds

# Reminder defaults
DEFAULT_REMINDER_TIME: str = '21:00'
MONTHLY_REPORT_DAY: int = 28

# Vietnamese category keyword mapping for expense classification
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    'an_uong': ['ăn', 'uống', 'cơm', 'bún', 'phở', 'cafe', 'cà phê', 'trà sữa', 'trà', 'bia', 'nhậu',
                'bánh', 'chè', 'kem', 'sáng', 'trưa', 'tối', 'chiều', 'ăn sáng', 'ăn trưa', 'ăn tối',
                'ăn chiều', 'nước', 'sinh tố', 'nước ép', 'pizza', 'gà', 'bò', 'heo', 'cá',
                'rau', 'thịt', 'đồ ăn', 'quán', 'nhà hàng', 'buffet', 'lẩu', 'nướng',
                'mì', 'hủ tiếu', 'bánh mì', 'xôi', 'cháo'],
    'nha_o': ['thuê nhà', 'tiền nhà', 'điện', 'nước', 'internet', 'wifi', 'phòng',
              'gas', 'rác', 'chung cư', 'phí quản lý', 'sửa nhà', 'đồ gia dụng'],
    'xang_xe': ['xăng', 'gửi xe', 'sửa xe', 'grab', 'taxi', 'xe ôm', 'đổ xăng',
                'rửa xe', 'bảo dưỡng', 'vé xe', 'xe buýt', 'xe bus', 'di chuyển',
                'đi lại', 'gojek', 'be', 'uber', 'parking', 'đỗ xe'],
    'mua_sam': ['áo', 'quần', 'giày', 'dép', 'mua sắm', 'shopping', 'mỹ phẩm',
                'nước hoa', 'túi', 'balo', 'đồ dùng', 'siêu thị', 'tiki', 'shopee',
                'lazada', 'mua đồ', 'quần áo', 'thời trang', 'phụ kiện'],
    'giai_tri': ['phim', 'game', 'đi chơi', 'du lịch', 'karaoke', 'bar', 'club',
                 'netflix', 'spotify', 'youtube', 'giải trí', 'vui chơi', 'nhạc',
                 'concert', 'sự kiện', 'party', 'tiệc', 'bowling', 'billiard'],
}
