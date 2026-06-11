"""
services/gold_price.py - Gold Price Data Service

Adapter pattern mirroring market_data.py.  Ships with a
MockGoldProvider returning realistic Vietnamese gold prices.

Usage:
    provider = get_gold_provider()
    result = await provider.get_gold_price()
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import config


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class GoldPriceProvider(ABC):
    """Base interface for gold-price data sources."""

    @abstractmethod
    async def get_gold_price(self) -> Optional[dict]:
        """Fetch the latest domestic gold prices.

        Returns
        -------
        dict or None
            Keys: sjc_buy, sjc_sell, nhan_buy, nhan_sell,
                  unit, updated_at, source.
        """
        pass


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockGoldProvider(GoldPriceProvider):
    """Mock provider with realistic Vietnamese gold prices (VND/lượng)."""

    async def get_gold_price(self) -> Optional[dict]:
        """Return sample SJC and nhẫn 9999 prices."""
        return {
            'sjc_buy': 92_500_000,
            'sjc_sell': 94_500_000,
            'nhan_buy': 78_000_000,
            'nhan_sell': 79_500_000,
            'unit': 'VND/lượng',
            'updated_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'source': 'Mock Data (cần cấu hình API thật)',
        }


# ---------------------------------------------------------------------------
# Real provider (placeholder)
# ---------------------------------------------------------------------------

# TODO: Implement a real gold-price provider.  Options include:
#   - Crawling sjc.com.vn or pnj.com.vn
#   - Calling a third-party gold-price API
#   - Using a data service that aggregates Vietnamese precious-metal prices
#
# class RealGoldProvider(GoldPriceProvider):
#     """Fetch live SJC & nhẫn prices from a real data source."""
#
#     def __init__(self, api_key: str | None = None):
#         self.api_key = api_key
#
#     async def get_gold_price(self) -> Optional[dict]:
#         import aiohttp
#         try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.get('https://example.com/api/gold') as resp:
#                     if resp.status == 200:
#                         data = await resp.json()
#                         return {
#                             'sjc_buy': data['sjc']['buy'],
#                             'sjc_sell': data['sjc']['sell'],
#                             'nhan_buy': data['nhan']['buy'],
#                             'nhan_sell': data['nhan']['sell'],
#                             'unit': 'VND/lượng',
#                             'updated_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
#                             'source': 'Real API',
#                         }
#         except Exception:
#             return await MockGoldProvider().get_gold_price()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class RealGoldProvider(GoldPriceProvider):
    """Placeholder real provider; falls back to sample data until configured."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def get_gold_price(self) -> Optional[dict]:
        data = await MockGoldProvider().get_gold_price()
        if data:
            data['source'] = f"{data.get('source', 'Mock Data')} (real provider placeholder)"
        return data


def get_gold_provider() -> GoldPriceProvider:
    """Return the configured gold-price provider.

    MARKET_PROVIDER=real selects a placeholder real provider that currently
    falls back to mock/sample data.
    """
    if config.MARKET_PROVIDER == 'real':
        return RealGoldProvider(config.GOLD_API_KEY)
    return MockGoldProvider()
