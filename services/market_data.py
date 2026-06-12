"""
services/market_data.py - Stock Price Data Service

Adapter pattern with pluggable market-data implementations.  The default
provider uses the `vnstock` package and falls back to mock data on provider
errors.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging
from typing import Any, Optional

import config


logger = logging.getLogger(__name__)


class StockDataProvider(ABC):
    """Base interface every stock-data source must implement."""

    @abstractmethod
    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        """Fetch the latest price snapshot for *symbol*."""
        pass


class MockMarketProvider(StockDataProvider):
    """Mock provider with sample Vietnamese stock data."""

    _MOCK_DATA: dict[str, dict] = {
        "FPT": {"price": 123_400, "change": 1_200, "change_percent": 0.98, "market": "HOSE"},
        "VNM": {"price": 74_500, "change": -500, "change_percent": -0.67, "market": "HOSE"},
        "HPG": {"price": 26_800, "change": 300, "change_percent": 1.13, "market": "HOSE"},
        "VIC": {"price": 43_200, "change": -200, "change_percent": -0.46, "market": "HOSE"},
        "MSN": {"price": 89_500, "change": 1_500, "change_percent": 1.70, "market": "HOSE"},
        "TCB": {"price": 25_100, "change": 200, "change_percent": 0.80, "market": "HOSE"},
        "VHM": {"price": 38_700, "change": -100, "change_percent": -0.26, "market": "HOSE"},
        "MWG": {"price": 52_300, "change": 800, "change_percent": 1.55, "market": "HOSE"},
        "VCB": {"price": 91_000, "change": 500, "change_percent": 0.55, "market": "HOSE"},
        "ACB": {"price": 24_300, "change": -300, "change_percent": -1.22, "market": "HOSE"},
        "SSI": {"price": 30_200, "change": 400, "change_percent": 1.34, "market": "HOSE"},
        "PNJ": {"price": 78_100, "change": 600, "change_percent": 0.77, "market": "HOSE"},
        "SHB": {"price": 11_500, "change": 50, "change_percent": 0.44, "market": "HNX"},
        "PVS": {"price": 28_400, "change": -200, "change_percent": -0.70, "market": "HNX"},
    }

    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        symbol = symbol.upper().strip()
        data = self._MOCK_DATA.get(symbol)
        if data is None:
            return None
        return {
            "symbol": symbol,
            "market": data["market"],
            "exchange": data["market"],
            "price": data["price"],
            "change": data["change"],
            "change_percent": data["change_percent"],
            "percent_change": data["change_percent"],
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "source": "Mock Data (fallback)",
            "is_realtime": False,
            "note": "mock/sample data",
        }


MockStockProvider = MockMarketProvider


class VnstockMarketProvider(StockDataProvider):
    """Market provider using the `vnstock` package."""

    def __init__(self, source: str = "VCI", timeout: float = 10):
        self.source = source
        self.timeout = timeout
        self._mock = MockMarketProvider()

    async def get_stock_price(self, symbol: str) -> Optional[dict]:
        symbol = symbol.upper().strip()
        if not symbol:
            return None

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._fetch_sync, symbol),
                timeout=self.timeout,
            )
        except Exception as exc:
            logger.warning("vnstock provider failed for %s; falling back to mock: %s", symbol, exc)
            return await self._mock.get_stock_price(symbol)

    def _fetch_sync(self, symbol: str) -> Optional[dict]:
        stock = self._make_stock(symbol)
        data = self._fetch_price_board(stock, symbol)
        if data:
            return data
        return self._fetch_history(stock, symbol)

    def _make_stock(self, symbol: str) -> Any:
        try:
            from vnstock import Vnstock
        except Exception as exc:
            raise RuntimeError("vnstock import lỗi") from exc

        try:
            return Vnstock().stock(symbol=symbol, source=self.source)
        except TypeError:
            return Vnstock().stock(symbol=symbol)

    def _fetch_price_board(self, stock: Any, symbol: str) -> Optional[dict]:
        trading = getattr(stock, "trading", None)
        if trading is None or not hasattr(trading, "price_board"):
            return None

        board = trading.price_board([symbol])
        row = _first_row(board)
        if not row:
            return None

        price = _normalize_vn_price(_pick_number(row, (
            "match_match_price",
            "matched_price",
            "matchedprice",
            "match_price",
            "matchprice",
            "last_price",
            "lastprice",
            "price",
            "close",
        ), contains=(("match", "price"), ("last", "price")), blocked=("change", "percent", "pct")))
        if price is None:
            return None

        change = _normalize_vn_price(_pick_number(row, (
            "match_price_change",
            "price_change",
            "pricechange",
            "change",
        ), contains=(("change",),), blocked=("percent", "pct")))
        percent = _pick_number(row, (
            "match_percent_price_change",
            "price_change_percent",
            "pricechangepercent",
            "percent_change",
            "change_percent",
            "pct_change",
        ), contains=(("percent",), ("pct",)))
        exchange = _pick_text(row, ("exchange", "market", "floor", "stock_exchange", "listing_exchange"))

        return _quote(
            symbol=symbol,
            price=price,
            change=change,
            percent_change=percent,
            exchange=exchange,
            source=f"vnstock/{self.source}",
            is_realtime=True,
        )

    def _fetch_history(self, stock: Any, symbol: str) -> Optional[dict]:
        quote_api = getattr(stock, "quote", None)
        if quote_api is None or not hasattr(quote_api, "history"):
            return None

        end = datetime.now().date()
        start = end - timedelta(days=14)
        history = quote_api.history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1D",
        )
        rows = _rows(history)
        if not rows:
            return None

        last = rows[-1]
        previous = rows[-2] if len(rows) > 1 else None
        price = _normalize_vn_price(_pick_number(last, ("close", "price", "match_price")))
        if price is None:
            return None

        prev_price = _normalize_vn_price(_pick_number(previous or {}, ("close", "price", "match_price")))
        change = price - prev_price if prev_price is not None else None
        percent = (change / prev_price * 100) if change is not None and prev_price else None
        exchange = _pick_text(last, ("exchange", "market", "floor", "stock_exchange"))

        return _quote(
            symbol=symbol,
            price=price,
            change=change,
            percent_change=percent,
            exchange=exchange,
            source=f"vnstock/{self.source}",
            is_realtime=False,
            note="daily close gần nhất",
        )


RealMarketProvider = VnstockMarketProvider
VnStockProvider = VnstockMarketProvider


def _quote(
    symbol: str,
    price: float,
    change: float | None,
    percent_change: float | None,
    exchange: str | None,
    source: str,
    is_realtime: bool,
    note: str | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "market": exchange,
        "exchange": exchange,
        "price": price,
        "change": change,
        "change_percent": percent_change,
        "percent_change": percent_change,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "source": source,
        "is_realtime": is_realtime,
        "note": note,
    }


def _first_row(data: Any) -> dict[str, Any] | None:
    rows = _rows(data)
    return rows[0] if rows else None


def _rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []

    if hasattr(data, "empty") and data.empty:
        return []

    if hasattr(data, "to_dict"):
        try:
            records = data.to_dict("records")
            return [_flatten_record(record) for record in records]
        except TypeError:
            pass

    if isinstance(data, list):
        return [_flatten_record(row) for row in data if isinstance(row, dict)]

    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return [_flatten_record(row) for row in data["data"] if isinstance(row, dict)]
        return [_flatten_record(data)]

    return []


def _flatten_record(record: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in record.items():
        flat[_normalize_key(key)] = value
    return flat


def _normalize_key(key: Any) -> str:
    if isinstance(key, tuple):
        key = "_".join(str(part) for part in key if part not in (None, ""))
    key = str(key).strip().lower()
    for char in (" ", "-", ".", "/"):
        key = key.replace(char, "_")
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def _pick_number(
    row: dict[str, Any],
    keys: tuple[str, ...],
    contains: tuple[tuple[str, ...], ...] = (),
    blocked: tuple[str, ...] = (),
) -> float | None:
    for key in keys:
        value = _to_float(row.get(key))
        if value is not None:
            return value

    for key, raw in row.items():
        if contains and not any(all(part in key for part in parts) for parts in contains):
            continue
        if any(part in key for part in ("volume", "value", "ref", "ceil", "floor", *blocked)):
            continue
        value = _to_float(raw)
        if value is not None:
            return value
    return None


def _pick_text(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        if str(value).lower() == "nan":
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _normalize_vn_price(value: float | None) -> float | None:
    if value is None:
        return None
    if abs(value) < 1_000:
        return value * 1_000
    return value


def get_stock_provider() -> StockDataProvider:
    """Return the configured stock data provider."""
    if config.MARKET_PROVIDER in {"vnstock", "real"}:
        return VnstockMarketProvider(
            source=config.VNSTOCK_SOURCE,
            timeout=config.VNSTOCK_TIMEOUT,
        )
    return MockMarketProvider()
