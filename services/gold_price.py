"""
services/gold_price.py - Gold Price Data Service

Gold provider adapter for the Telegram Assistant Bot.
Supports VNAppMob Gold API v2 and a mock fallback provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import json
import logging
from typing import Any, Optional

import aiohttp

import config


AUTH_ERROR_MESSAGE = (
    "VNAppMob Gold API key đã hết hạn hoặc không hợp lệ. "
    "Hãy request key mới và cập nhật VNAPPMOB_GOLD_API_KEY trong .env."
)

logger = logging.getLogger(__name__)

SJC_LABELS = {
    "1l": "SJC 1L",
    "5c": "SJC 5C",
    "1c": "SJC 1C",
    "nhan1c": "Nhẫn 1C",
    "nutrang_75": "Nữ trang 75",
    "nutrang_99": "Nữ trang 99",
    "nutrang_9999": "Nữ trang 9999",
    "trangsuc49": "Trang sức 49",
}

REGION_LABELS = {
    "hcm": "HCM",
    "hn": "Hà Nội",
    "ha_noi": "Hà Nội",
    "hanoi": "Hà Nội",
    "danang": "Đà Nẵng",
    "da_nang": "Đà Nẵng",
}

DIRECT_BUY_KEYS = (
    "buy",
    "buy_price",
    "buyPrice",
    "buying",
    "buying_price",
    "buyValue",
    "price_buy",
    "mua_vao",
    "mua",
)
DIRECT_SELL_KEYS = (
    "sell",
    "sell_price",
    "sellPrice",
    "selling",
    "selling_price",
    "sellValue",
    "price_sell",
    "ban_ra",
    "ban",
)
PRODUCT_LABEL_KEYS = (
    "name",
    "type",
    "gold_type",
    "goldType",
    "product",
    "product_name",
    "productName",
    "brand",
    "title",
    "label",
)
REGION_LABEL_KEYS = (
    "location",
    "area",
    "city",
    "province",
    "branch",
    "region",
    "market",
)


class GoldProviderError(Exception):
    """Base exception for gold provider failures."""


class GoldAuthError(GoldProviderError):
    """Raised when the VNAppMob API key is missing, expired, or invalid."""


class GoldPriceProvider(ABC):
    """Base interface for gold-price data sources."""

    @abstractmethod
    async def get_gold_price(self, source: str | None = None) -> Optional[dict]:
        """Fetch latest domestic gold prices."""
        pass


class MockGoldProvider(GoldPriceProvider):
    """Mock provider with sample Vietnamese gold prices."""

    async def get_gold_price(self, source: str | None = None) -> Optional[dict]:
        groups = {
            "SJC": {
                "items": [
                    {"label": "SJC 1L", "buy": 92_500_000, "sell": 94_500_000},
                    {"label": "Nhẫn 1C", "buy": 78_000_000, "sell": 79_500_000},
                ],
            },
            "DOJI": {
                "items": [
                    {"label": "HCM", "buy": 92_300_000, "sell": 94_300_000},
                    {"label": "Hà Nội", "buy": 92_300_000, "sell": 94_300_000},
                ],
            },
            "PNJ": {
                "items": [
                    {"label": "HCM", "buy": 78_100_000, "sell": 79_400_000},
                    {"label": "Hà Nội", "buy": 78_100_000, "sell": 79_400_000},
                ],
            },
        }
        selected = _normalize_source(source)
        if selected:
            groups = {selected: groups[selected]}

        return {
            "provider": "mock",
            "groups": groups,
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "source": "Mock/sample data",
            "is_mock": True,
        }


class VNAppMobGoldProvider(GoldPriceProvider):
    """VNAppMob Gold API v2 provider."""

    ENDPOINTS = {
        "SJC": "/api/v2/gold/sjc",
        "DOJI": "/api/v2/gold/doji",
        "PNJ": "/api/v2/gold/pnj",
    }

    def __init__(self, api_key: str, base_url: str, timeout: float):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def get_gold_price(self, source: str | None = None) -> Optional[dict]:
        if not self.api_key:
            raise GoldAuthError(AUTH_ERROR_MESSAGE)

        selected = _normalize_source(source)
        sources = [selected] if selected else list(self.ENDPOINTS)
        groups: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        auth_error = False

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for name in sources:
                try:
                    items = await self._fetch_source(session, name)
                    if items:
                        groups[name] = {"items": items}
                    else:
                        errors[name] = "Không có dữ liệu từ API"
                except GoldAuthError:
                    auth_error = True
                    errors[name] = "API key hết hạn hoặc không hợp lệ"
                except Exception as exc:
                    errors[name] = str(exc) or "provider lỗi"

        if not groups and auth_error:
            raise GoldAuthError(AUTH_ERROR_MESSAGE)

        return {
            "provider": "vnappmob",
            "groups": groups,
            "errors": errors,
            "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "source": "VNAppMob Gold API",
            "is_mock": False,
        }

    async def _fetch_source(
        self,
        session: aiohttp.ClientSession,
        source_name: str,
    ) -> list[dict[str, Any]]:
        url = f"{self.base_url}{self.ENDPOINTS[source_name]}"
        async with session.get(url) as response:
            status = response.status
            text = await response.text()
            if status == 403 or _looks_like_expired_key(text):
                raise GoldAuthError(AUTH_ERROR_MESSAGE)
            if status >= 400:
                raise GoldProviderError(f"HTTP {status}")
            try:
                payload = json.loads(text)
            except Exception as exc:
                raise GoldProviderError("response JSON không hợp lệ") from exc

        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            logger.warning(
                "VNAppMob %s returned empty results; status=%s result_count=0 first_item_keys=[]",
                source_name,
                status,
            )
            return []

        records = results if isinstance(results, list) else [results]
        parsed: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            items = self._parse_price_pairs(record, source_name)
            if not items:
                direct_item = self._parse_direct_record(record, source_name, index)
                if direct_item:
                    items = [direct_item]
            if items:
                parsed.extend(items)

        if not parsed:
            logger.warning(
                "VNAppMob %s returned results but no price pairs could be parsed; status=%s result_count=%s first_item_keys=%s",
                source_name,
                status,
                len(records),
                list(records[0].keys()) if records and isinstance(records[0], dict) else [],
            )
        return parsed

    def _parse_price_pairs(
        self,
        record: dict[str, Any],
        source_name: str,
    ) -> list[dict[str, Any]]:
        generic_suffixes = {"price", "value", "amount", "datetime"}
        key_lookup = {str(key).lower(): key for key in record}
        suffixes = {
            ("prefix", lower_key[4:])
            for lower_key, original_key in key_lookup.items()
            if lower_key.startswith("buy_")
            and lower_key[4:] not in generic_suffixes
            and record.get(original_key) not in (None, "")
        }
        suffixes |= {
            ("prefix", lower_key[5:])
            for lower_key, original_key in key_lookup.items()
            if lower_key.startswith("sell_")
            and lower_key[5:] not in generic_suffixes
            and record.get(original_key) not in (None, "")
        }
        suffixes |= {
            ("suffix", lower_key[:-4])
            for lower_key, original_key in key_lookup.items()
            if lower_key.endswith("_buy")
            and lower_key[:-4] not in generic_suffixes
            and record.get(original_key) not in (None, "")
        }
        suffixes |= {
            ("suffix", lower_key[:-5])
            for lower_key, original_key in key_lookup.items()
            if lower_key.endswith("_sell")
            and lower_key[:-5] not in generic_suffixes
            and record.get(original_key) not in (None, "")
        }

        items: list[dict[str, Any]] = []
        region = _record_region(record)
        for direction, suffix in sorted(suffixes, key=lambda item: _gold_suffix_sort_key(item[1])):
            if direction == "prefix":
                buy = _get_case_insensitive(record, f"buy_{suffix}")
                sell = _get_case_insensitive(record, f"sell_{suffix}")
            else:
                buy = _get_case_insensitive(record, f"{suffix}_buy")
                sell = _get_case_insensitive(record, f"{suffix}_sell")
            if buy in (None, "") and sell in (None, ""):
                continue
            label = _gold_label(source_name, suffix)
            if region and region.lower() not in label.lower():
                label = f"{region} {label}"
            items.append({
                "label": label,
                "buy": buy,
                "sell": sell,
                "unit": _get_case_insensitive(record, "unit") or _get_case_insensitive(record, "price_unit") or "VND",
                "source_key": suffix,
            })

        return items

    def _parse_direct_record(
        self,
        record: dict[str, Any],
        source_name: str,
        index: int,
    ) -> dict[str, Any] | None:
        buy = _first_present(record, DIRECT_BUY_KEYS)
        sell = _first_present(record, DIRECT_SELL_KEYS)
        if buy in (None, "") and sell in (None, ""):
            return None

        return {
            "label": _record_label(record, source_name, index),
            "buy": buy,
            "sell": sell,
            "unit": _get_case_insensitive(record, "unit") or _get_case_insensitive(record, "price_unit") or "VND",
        }


def _first_present(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = _get_case_insensitive(record, key)
        if value not in (None, ""):
            return value
    return None


def _get_case_insensitive(record: dict[str, Any], key: str) -> Any:
    if key in record:
        return record.get(key)
    lowered = key.lower()
    for actual_key, value in record.items():
        if str(actual_key).lower() == lowered:
            return value
    return None


def _gold_label(source_name: str, suffix: str) -> str:
    normalized = suffix.lower()
    labels = SJC_LABELS if source_name.upper() == "SJC" else REGION_LABELS
    label = labels.get(normalized)
    if label:
        return label
    return suffix.replace("_", " ").strip().title()


def _record_region(record: dict[str, Any]) -> str:
    value = _first_present(record, REGION_LABEL_KEYS)
    return str(value).strip() if value not in (None, "") else ""


def _record_label(record: dict[str, Any], source_name: str, index: int) -> str:
    product = _first_present(record, PRODUCT_LABEL_KEYS)
    region = _record_region(record)
    parts = []
    if product not in (None, ""):
        parts.append(str(product).strip())
    if region and all(region.lower() not in part.lower() for part in parts):
        parts.append(region)
    if parts:
        return " ".join(parts)
    return f"{source_name} #{index}"


def _gold_suffix_sort_key(suffix: str) -> tuple[int, str]:
    order = {
        "1l": 10,
        "5c": 20,
        "1c": 30,
        "nhan1c": 40,
        "nutrang_75": 50,
        "nutrang_99": 60,
        "nutrang_9999": 70,
        "trangsuc49": 80,
    }
    return order.get(suffix, 999), suffix


def _looks_like_expired_key(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in (
            "expired",
            "invalid token",
            "invalid api key",
            "unauthorized",
            "forbidden",
            "api key",
            "token",
            "hết hạn",
            "không hợp lệ",
        )
    )


def _normalize_source(source: str | None) -> str | None:
    if not source:
        return None
    value = source.strip().upper()
    aliases = {
        "SJC": "SJC",
        "DOJI": "DOJI",
        "PNJ": "PNJ",
    }
    return aliases.get(value)


def get_gold_provider() -> GoldPriceProvider:
    """Return the configured gold-price provider."""
    provider = config.GOLD_PROVIDER.lower()
    if provider == "vnappmob":
        return VNAppMobGoldProvider(
            api_key=config.VNAPPMOB_GOLD_API_KEY,
            base_url=config.VNAPPMOB_GOLD_BASE_URL,
            timeout=config.VNAPPMOB_GOLD_TIMEOUT,
        )
    return MockGoldProvider()
