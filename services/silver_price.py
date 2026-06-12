"""
services/silver_price.py - Silver Price Data Service

Provider adapter for Vietnamese silver prices.  The default provider fetches
the public Phu Quy silver-price partial and falls back to mock data on errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from html.parser import HTMLParser
import logging
import re
from typing import Optional

import aiohttp

import config


logger = logging.getLogger(__name__)


class SilverPriceProvider(ABC):
    """Base interface for silver-price data sources."""

    @abstractmethod
    async def get_silver_price(self) -> Optional[dict]:
        """Fetch the latest domestic silver prices."""
        pass


class MockSilverProvider(SilverPriceProvider):
    """Mock provider with sample Vietnamese silver prices."""

    async def get_silver_price(self) -> Optional[dict]:
        return {
            "items": [
                {
                    "product": "Bạc miếng 999 1 lượng",
                    "unit": "VND/lượng",
                    "buy": 2_567_000,
                    "sell": 2_646_000,
                },
                {
                    "product": "Bạc thỏi 999 1 kilo",
                    "unit": "VND/kg",
                    "buy": 68_453_000,
                    "sell": 70_560_000,
                },
            ],
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "source": "Mock/sample data",
            "is_mock": True,
        }


class PhuQuySilverProvider(SilverPriceProvider):
    """Fetch silver prices from the public Phu Quy HTML partial."""

    def __init__(self, url: str, timeout: float):
        self.url = url
        self.timeout = timeout
        self._mock = MockSilverProvider()

    async def get_silver_price(self) -> Optional[dict]:
        try:
            items = await self._fetch_items()
        except Exception as exc:
            logger.warning("Phu Quy silver provider failed; falling back to mock: %s", exc)
            return await self._mock.get_silver_price()

        if not items:
            logger.warning("Phu Quy silver parser returned no rows; falling back to mock")
            return await self._mock.get_silver_price()

        return {
            "items": items,
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "source": "Phú Quý Silver",
            "is_mock": False,
        }

    async def _fetch_items(self) -> list[dict]:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": "TelegramAssistantBot/1.0",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(self.url) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                html = await response.text(encoding="utf-8", errors="replace")

        return parse_phuquy_silver_html(html)


class _TableParser(HTMLParser):
    """Small HTML table/row text parser for server-rendered partials."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs):
        if tag.lower() == "tr":
            self._current_row = []
        elif tag.lower() in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._in_cell = True

    def handle_data(self, data: str):
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str):
        if tag.lower() in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = _clean_cell_text(" ".join(self._current_cell))
            self._current_row.append(text)
            self._current_cell = None
            self._in_cell = False
        elif tag.lower() == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def parse_phuquy_silver_html(html: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html or "")
    rows = [row for row in parser.rows if row]
    if not rows:
        return []

    header_indexes: dict[str, int] | None = None
    items: list[dict] = []
    for row in rows:
        detected = _detect_header(row)
        if detected:
            header_indexes = detected
            continue

        item = _parse_row(row, header_indexes)
        if item:
            items.append(item)

    return items


def _detect_header(row: list[str]) -> dict[str, int] | None:
    normalized = [_normalize_text(cell) for cell in row]
    indexes: dict[str, int] = {}
    for index, cell in enumerate(normalized):
        if any(token in cell for token in ("san pham", "loai", "ten")):
            indexes["product"] = index
        elif "don vi" in cell:
            indexes["unit"] = index
        elif "mua" in cell:
            indexes["buy"] = index
        elif "ban" in cell:
            indexes["sell"] = index

    if "buy" in indexes and ("product" in indexes or "unit" in indexes):
        return indexes
    if len(row) >= 4 and "mua" in normalized[2] and ("ban" in normalized[3] or "b?n" in normalized[3]):
        return {"product": 0, "unit": 1, "buy": 2, "sell": 3}
    return None


def _parse_row(row: list[str], header_indexes: dict[str, int] | None) -> dict | None:
    if header_indexes:
        product = _cell(row, header_indexes.get("product"))
        unit = _clean_unit(_cell(row, header_indexes.get("unit")) or _infer_unit(row))
        buy = _cell(row, header_indexes.get("buy"))
        sell = _cell(row, header_indexes.get("sell"))
    else:
        if len(row) < 3:
            return None
        price_indexes = [index for index, cell in enumerate(row) if _looks_like_price(cell)]
        if not price_indexes:
            return None
        buy_index = price_indexes[0]
        sell_index = price_indexes[1] if len(price_indexes) > 1 else None
        unit_index = _find_unit_index(row, before=buy_index)
        product_parts = [
            cell for index, cell in enumerate(row[:buy_index])
            if index != unit_index and cell
        ]
        product = " ".join(product_parts).strip()
        unit = _clean_unit(_cell(row, unit_index) or _infer_unit(row))
        buy = _cell(row, buy_index)
        sell = _cell(row, sell_index)

    if not product or not _looks_like_price(buy):
        return None

    return {
        "product": product,
        "unit": unit or "VND",
        "buy": buy,
        "sell": sell if _looks_like_price(sell) else None,
    }


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return row[index].strip()


def _clean_cell_text(text: str) -> str:
    return " ".join((text or "").replace("\xa0", " ").split())


def _normalize_text(text: str) -> str:
    value = (text or "").lower()
    replacements = {
        "đ": "d",
        "á": "a", "à": "a", "ả": "a", "ã": "a", "ạ": "a",
        "ă": "a", "ắ": "a", "ằ": "a", "ẳ": "a", "ẵ": "a", "ặ": "a",
        "â": "a", "ấ": "a", "ầ": "a", "ẩ": "a", "ẫ": "a", "ậ": "a",
        "é": "e", "è": "e", "ẻ": "e", "ẽ": "e", "ẹ": "e",
        "ê": "e", "ế": "e", "ề": "e", "ể": "e", "ễ": "e", "ệ": "e",
        "í": "i", "ì": "i", "ỉ": "i", "ĩ": "i", "ị": "i",
        "ó": "o", "ò": "o", "ỏ": "o", "õ": "o", "ọ": "o",
        "ô": "o", "ố": "o", "ồ": "o", "ổ": "o", "ỗ": "o", "ộ": "o",
        "ơ": "o", "ớ": "o", "ờ": "o", "ở": "o", "ỡ": "o", "ợ": "o",
        "ú": "u", "ù": "u", "ủ": "u", "ũ": "u", "ụ": "u",
        "ư": "u", "ứ": "u", "ừ": "u", "ử": "u", "ữ": "u", "ự": "u",
        "ý": "y", "ỳ": "y", "ỷ": "y", "ỹ": "y", "ỵ": "y",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _looks_like_price(value: str | None) -> bool:
    if not value:
        return False
    digits = re.sub(r"\D", "", value)
    return len(digits) >= 4


def _find_unit_index(row: list[str], before: int) -> int | None:
    for index, cell in enumerate(row[:before]):
        lower = _normalize_text(cell)
        if "vnd" in lower or "vn" in lower or "/" in lower or "luong" in lower or "/kg" in lower or "kilo" in lower:
            return index
    return None


def _infer_unit(row: list[str]) -> str:
    joined = " ".join(row)
    lower = _normalize_text(joined)
    if "kg" in lower or "kilo" in lower:
        return "VND/kg"
    if "luong" in lower:
        return "VND/lượng"
    return "VND"


def _clean_unit(unit: str) -> str:
    lower = _normalize_text(unit)
    if "kg" in lower or "kilo" in lower:
        return "VND/kg"
    if "luong" in lower or ("/" in unit and "vn" in lower):
        return "VND/lượng"
    return unit or "VND"


def get_silver_provider() -> SilverPriceProvider:
    """Return the configured silver-price provider."""
    if config.SILVER_PROVIDER == "phuquy":
        return PhuQuySilverProvider(
            url=config.PHUQUY_SILVER_URL,
            timeout=config.PHUQUY_SILVER_TIMEOUT,
        )
    return MockSilverProvider()
