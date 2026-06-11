"""
services/market_data.py - Stock Price Data Service

Adapter pattern with abstract base class and pluggable implementations.
Currently ships with a VnStock provider (falls back to mock) and a
MockStockProvider with realistic Vietnamese stock market data.

Usage:
    provider = get_stock_provider()
    result = await provider.get_stock_price('FPT')
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import config


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class StockDataProvider(ABC):
    """Base interface every stock-data source must implement."""

    @abstractmethod
    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        """Fetch the latest price snapshot for *symbol*.

        Returns
        -------
        dict or None
            Keys: symbol, market, price, change, change_percent,
                  updated_at, source.
            ``None`` when the symbol is unknown / unavailable.
        """
        pass


# ---------------------------------------------------------------------------
# Mock provider – realistic VN stock prices
# ---------------------------------------------------------------------------

class MockMarketProvider(StockDataProvider):
    """Mock provider with sample Vietnamese stock data.

    Used as fallback when no real API is configured.
    """

    # Realistic HOSE / HNX sample prices (VND)
    _MOCK_DATA: dict[str, dict] = {
        'FPT': {'price': 123_400, 'change': 1_200, 'change_percent': 0.98, 'market': 'HOSE'},
        'VNM': {'price': 74_500, 'change': -500, 'change_percent': -0.67, 'market': 'HOSE'},
        'HPG': {'price': 26_800, 'change': 300, 'change_percent': 1.13, 'market': 'HOSE'},
        'VIC': {'price': 43_200, 'change': -200, 'change_percent': -0.46, 'market': 'HOSE'},
        'MSN': {'price': 89_500, 'change': 1_500, 'change_percent': 1.70, 'market': 'HOSE'},
        'TCB': {'price': 25_100, 'change': 200, 'change_percent': 0.80, 'market': 'HOSE'},
        'VHM': {'price': 38_700, 'change': -100, 'change_percent': -0.26, 'market': 'HOSE'},
        'MWG': {'price': 52_300, 'change': 800, 'change_percent': 1.55, 'market': 'HOSE'},
        'VCB': {'price': 91_000, 'change': 500, 'change_percent': 0.55, 'market': 'HOSE'},
        'ACB': {'price': 24_300, 'change': -300, 'change_percent': -1.22, 'market': 'HOSE'},
        'SSI': {'price': 30_200, 'change': 400, 'change_percent': 1.34, 'market': 'HOSE'},
        'PNJ': {'price': 78_100, 'change': 600, 'change_percent': 0.77, 'market': 'HOSE'},
        'SHB': {'price': 11_500, 'change': 50, 'change_percent': 0.44, 'market': 'HNX'},
        'PVS': {'price': 28_400, 'change': -200, 'change_percent': -0.70, 'market': 'HNX'},
    }

    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        """Return mock price data for a known Vietnamese stock symbol."""
        data = self._MOCK_DATA.get(symbol.upper())
        if data is None:
            return None
        return {
            'symbol': symbol.upper(),
            'market': data['market'],
            'price': data['price'],
            'change': data['change'],
            'change_percent': data['change_percent'],
            'updated_at': datetime.now().strftime('%d/%m/%Y'),
            'source': 'Mock Data (cần cấu hình API thật)',
        }


# ---------------------------------------------------------------------------
# Real provider – vnstock library
# ---------------------------------------------------------------------------

MockStockProvider = MockMarketProvider


class RealMarketProvider(StockDataProvider):
    """Real provider using the *vnstock* library.

    Falls back to :class:`MockStockProvider` when vnstock is not installed
    or fails at runtime.

    TODO: Replace the import / fallback block with a properly configured
          vnstock call once the library is set up in the deployment
          environment.
    """

    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        """Attempt to fetch live data via vnstock; fall back to mock."""
        try:
            # ------------------------------------------------------------------
            # Uncomment and adapt once vnstock is installed & configured:
            #
            # from vnstock import Vnstock
            # stock = Vnstock().stock(symbol=symbol.upper(), source='TCBS')
            # df = stock.trading.price_board([symbol.upper()])
            # if df.empty:
            #     return None
            # row = df.iloc[0]
            # return {
            #     'symbol': symbol.upper(),
            #     'market': str(row.get('exchange', 'HOSE')),
            #     'price': float(row.get('matchedPrice', 0)) * 1000,
            #     'change': float(row.get('priceChange', 0)) * 1000,
            #     'change_percent': float(row.get('priceChangePercent', 0)),
            #     'updated_at': datetime.now().strftime('%d/%m/%Y'),
            #     'source': 'vnstock / TCBS',
            # }
            # ------------------------------------------------------------------
            raise ImportError('vnstock not configured')
        except (ImportError, Exception):
            return await MockMarketProvider().get_stock_price(symbol)


VnStockProvider = RealMarketProvider


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_stock_provider() -> StockDataProvider:
    """Return the configured stock data provider.

    MARKET_PROVIDER=mock returns sample data. MARKET_PROVIDER=real currently
    uses a placeholder that falls back to mock data until configured.
    """
    if config.MARKET_PROVIDER == 'real':
        return RealMarketProvider()
    return MockMarketProvider()
