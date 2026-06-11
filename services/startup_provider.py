"""
Startup news/funding provider adapters.

The default provider is mock/sample data. RSS and NewsAPI providers are
placeholders that fall back to mock data until real integrations are added.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import config


SUPPORTED_TOPICS = {
    "all",
    "vn",
    "vietnam",
    "global",
    "ai",
    "fintech",
    "saas",
    "ecommerce",
    "healthtech",
    "edtech",
}

TOPIC_ALIASES = {
    "viet nam": "vn",
    "việt nam": "vn",
    "vietnam": "vn",
    "world": "global",
    "commerce": "ecommerce",
    "e-commerce": "ecommerce",
    "health": "healthtech",
    "education": "edtech",
}


def normalize_startup_topic(topic: str | None) -> str:
    if not topic:
        return "all"
    normalized = " ".join(topic.lower().strip().split())
    return TOPIC_ALIASES.get(normalized, normalized)


class StartupProvider(ABC):
    """Base interface for startup data providers."""

    @abstractmethod
    async def get_news(self, topic: str = "all", limit: int = 5) -> list[dict]:
        """Return startup news items for a topic."""

    @abstractmethod
    async def get_funding(self, topic: str = "all", limit: int = 5) -> list[dict]:
        """Return funding round items for a topic."""


class MockStartupProvider(StartupProvider):
    """Mock provider with explicit sample startup data."""

    _NEWS: list[dict] = [
        {
            "title": "Sample: Vietnam AI tooling startups expand into enterprise pilots",
            "summary": "A sample item about Vietnamese AI startups testing workflow automation with local enterprises.",
            "topic": "ai",
            "region": "vn",
            "published_at": "2026-06-01",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: Fintech teams focus on embedded payments for SMEs",
            "summary": "A sample item about payment infrastructure and SME finance use cases.",
            "topic": "fintech",
            "region": "global",
            "published_at": "2026-06-02",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: SaaS founders bundle AI copilots into vertical software",
            "summary": "A sample item covering vertical SaaS products adding AI assistants for operators.",
            "topic": "saas",
            "region": "global",
            "published_at": "2026-06-03",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: Ecommerce logistics startups test faster merchant onboarding",
            "summary": "A sample item on tools for sellers, fulfillment, and marketplace operations.",
            "topic": "ecommerce",
            "region": "global",
            "published_at": "2026-06-04",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: Healthtech teams build remote patient workflow software",
            "summary": "A sample item about clinical workflow, telehealth, and patient engagement tools.",
            "topic": "healthtech",
            "region": "global",
            "published_at": "2026-06-05",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: Edtech startups use AI tutors for exam preparation",
            "summary": "A sample item about adaptive learning and tutoring products.",
            "topic": "edtech",
            "region": "global",
            "published_at": "2026-06-06",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "title": "Sample: Vietnam fintech startups explore merchant credit scoring",
            "summary": "A sample Vietnam-focused fintech item about small business credit workflows.",
            "topic": "fintech",
            "region": "vn",
            "published_at": "2026-06-07",
            "source": "MockStartupProvider",
            "url": "",
        },
    ]

    _FUNDING: list[dict] = [
        {
            "startup_name": "SampleAI Labs",
            "round": "Seed",
            "amount": "$2M",
            "industry": "AI",
            "region": "vn",
            "date": "2026-06-01",
            "investor": "Sample Ventures",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "startup_name": "PayFlow Sample",
            "round": "Series A",
            "amount": "$8M",
            "industry": "Fintech",
            "region": "global",
            "date": "2026-06-02",
            "investor": "Mock Capital",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "startup_name": "CareOps Sample",
            "round": "Seed",
            "amount": "chưa có dữ liệu",
            "industry": "Healthtech",
            "region": "global",
            "date": "2026-06-03",
            "investor": "chưa có dữ liệu",
            "source": "MockStartupProvider",
            "url": "",
        },
        {
            "startup_name": "MerchantStack Sample",
            "round": "Pre-seed",
            "amount": "$750K",
            "industry": "Ecommerce",
            "region": "vn",
            "date": "2026-06-04",
            "investor": "Angel syndicate sample",
            "source": "MockStartupProvider",
            "url": "",
        },
    ]

    async def get_news(self, topic: str = "all", limit: int = 5) -> list[dict]:
        topic = normalize_startup_topic(topic)
        return _filter_items(self._NEWS, topic, limit)

    async def get_funding(self, topic: str = "all", limit: int = 5) -> list[dict]:
        topic = normalize_startup_topic(topic)
        return _filter_items(self._FUNDING, topic, limit)


class RSSStartupProvider(StartupProvider):
    """Placeholder RSS provider; falls back to mock/sample data."""

    async def get_news(self, topic: str = "all", limit: int = 5) -> list[dict]:
        items = await MockStartupProvider().get_news(topic, limit)
        for item in items:
            item["source"] = f"{item.get('source')} (RSS placeholder)"
        return items

    async def get_funding(self, topic: str = "all", limit: int = 5) -> list[dict]:
        return await MockStartupProvider().get_funding(topic, limit)


class NewsAPIStartupProvider(StartupProvider):
    """Placeholder NewsAPI provider; falls back to mock/sample data."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    async def get_news(self, topic: str = "all", limit: int = 5) -> list[dict]:
        items = await MockStartupProvider().get_news(topic, limit)
        for item in items:
            item["source"] = f"{item.get('source')} (NewsAPI placeholder)"
        return items

    async def get_funding(self, topic: str = "all", limit: int = 5) -> list[dict]:
        return await MockStartupProvider().get_funding(topic, limit)


def get_startup_provider() -> StartupProvider:
    provider = config.STARTUP_NEWS_PROVIDER
    if provider == "rss":
        return RSSStartupProvider()
    if provider == "newsapi":
        return NewsAPIStartupProvider(config.NEWS_API_KEY)
    return MockStartupProvider()


def _filter_items(items: list[dict], topic: str, limit: int) -> list[dict]:
    if topic not in SUPPORTED_TOPICS:
        return []
    results: list[dict] = []
    for item in items:
        item_topic = (item.get("topic") or item.get("industry") or "").lower()
        item_region = (item.get("region") or "").lower()
        if topic in {"all", item_topic, item_region}:
            results.append(dict(item))
        if len(results) >= limit:
            break
    return results


def now_iso_date() -> str:
    return datetime.utcnow().date().isoformat()
