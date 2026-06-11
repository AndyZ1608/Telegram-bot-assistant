"""
services/silver_price.py - Silver Price Data Service

Adapter pattern mirroring gold_price.py.  Ships with a
MockSilverProvider returning realistic Vietnamese silver prices.

Usage:
    provider = get_silver_provider()
    result = await provider.get_silver_price()
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import config


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class SilverPriceProvider(ABC):
    """Base interface for silver-price data sources."""

    @abstractmethod
    async def get_silver_price(self) -> Optional[dict]:
        """Fetch the latest domestic silver prices.

        Returns
        -------
        dict or None
            Keys: buy, sell, unit, updated_at, source.
        """
        pass


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockSilverProvider(SilverPriceProvider):
    """Mock provider with realistic Vietnamese silver prices (VND/lượng)."""

    async def get_silver_price(self) -> Optional[dict]:
        """Return sample silver buy/sell prices."""
        return {
            'buy': 1_350_000,
            'sell': 1_450_000,
            'unit': 'VND/lượng',
            'updated_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'source': 'Mock Data (cần cấu hình API thật)',
        }


# ---------------------------------------------------------------------------
# Real provider (placeholder)
# ---------------------------------------------------------------------------

# TODO: Implement a real silver-price provider.  Options include:
#   - Crawling pnj.com.vn or a precious-metals dealer site
#   - Calling a third-party API for Vietnamese silver prices
#
# class RealSilverProvider(SilverPriceProvider):
#     """Fetch live silver prices from a real data source."""
#
#     def __init__(self, api_key: str | None = None):
#         self.api_key = api_key
#
#     async def get_silver_price(self) -> Optional[dict]:
#         import aiohttp
#         try:
#             async with aiohttp.ClientSession() as session:
#                 async with session.get('https://example.com/api/silver') as resp:
#                     if resp.status == 200:
#                         data = await resp.json()
#                         return {
#                             'buy': data['buy'],
#                             'sell': data['sell'],
#                             'unit': 'VND/lượng',
#                             'updated_at': datetime.now().strftime('%d/%m/%Y %H:%M'),
#                             'source': 'Real API',
#                         }
#         except Exception:
#             return await MockSilverProvider().get_silver_price()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class RealSilverProvider(SilverPriceProvider):
    """Placeholder real provider; falls back to sample data until configured."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def get_silver_price(self) -> Optional[dict]:
        data = await MockSilverProvider().get_silver_price()
        if data:
            data['source'] = f"{data.get('source', 'Mock Data')} (real provider placeholder)"
        return data


def get_silver_provider() -> SilverPriceProvider:
    """Return the configured silver-price provider.

    MARKET_PROVIDER=real selects a placeholder real provider that currently
    falls back to mock/sample data.
    """
    if config.MARKET_PROVIDER == 'real':
        return RealSilverProvider(config.SILVER_API_KEY)
    return MockSilverProvider()
