"""
Startup news service with provider adapter and database cache.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

import config
from database.db import get_session
from database.models import StartupCache
from services.startup_provider import (
    SUPPORTED_TOPICS,
    get_startup_provider,
    normalize_startup_topic,
)
from services.unicorn_service import search_unicorns


class StartupNewsError(Exception):
    """Base error for startup news service."""


class UnsupportedTopicError(StartupNewsError):
    """Raised when a startup topic is not supported."""


@dataclass(frozen=True)
class StartupNewsResult:
    items: list[dict]
    from_cache: bool
    stale_cache: bool
    source_note: str


async def get_startup_news(topic: str | None = None, limit: int = 5) -> StartupNewsResult:
    normalized_topic = normalize_startup_topic(topic)
    if normalized_topic not in SUPPORTED_TOPICS:
        raise UnsupportedTopicError(f"Unsupported topic: {normalized_topic}")

    cached = await _get_cached_news(normalized_topic, limit, fresh_only=True)
    if cached:
        return StartupNewsResult(cached, True, False, "startup_cache")

    provider = get_startup_provider()
    try:
        items = await provider.get_news(normalized_topic, limit)
        if items:
            await _store_news(normalized_topic, items)
            return StartupNewsResult(items, False, False, items[0].get("source", "provider"))
    except Exception:
        stale = await _get_cached_news(normalized_topic, limit, fresh_only=False)
        if stale:
            return StartupNewsResult(stale, True, True, "startup_cache stale fallback")
        raise

    stale = await _get_cached_news(normalized_topic, limit, fresh_only=False)
    if stale:
        return StartupNewsResult(stale, True, True, "startup_cache stale fallback")
    return StartupNewsResult([], False, False, "no data")


async def get_funding(topic: str | None = None, limit: int = 5) -> list[dict]:
    normalized_topic = normalize_startup_topic(topic)
    if normalized_topic not in SUPPORTED_TOPICS:
        raise UnsupportedTopicError(f"Unsupported topic: {normalized_topic}")
    return await get_startup_provider().get_funding(normalized_topic, limit)


async def build_startup_digest(topic: str | None = None) -> dict:
    normalized_topic = normalize_startup_topic(topic)
    news_result = await get_startup_news(normalized_topic, limit=5)
    funding_items = await get_funding(normalized_topic, limit=3)
    unicorns = await search_unicorns(
        query=None if normalized_topic in {"all", "vn", "global"} else normalized_topic,
        country="Vietnam" if normalized_topic == "vn" else None,
        limit=3,
    )
    if normalized_topic == "global" and not unicorns:
        unicorns = await search_unicorns(limit=3)

    trend = _infer_trend(news_result.items, funding_items)
    return {
        "topic": normalized_topic,
        "news": news_result.items[:5],
        "funding": funding_items[:3],
        "companies": unicorns[:3],
        "trend": trend,
        "source_note": news_result.source_note,
        "from_cache": news_result.from_cache,
        "stale_cache": news_result.stale_cache,
    }


async def _get_cached_news(topic: str, limit: int, fresh_only: bool) -> list[dict]:
    cutoff = datetime.utcnow() - timedelta(minutes=config.STARTUP_CACHE_TTL_MINUTES)
    async with get_session() as session:
        stmt = (
            select(StartupCache)
            .where(StartupCache.topic == topic)
            .order_by(StartupCache.created_at.desc())
            .limit(limit)
        )
        if fresh_only:
            stmt = stmt.where(StartupCache.created_at >= cutoff)
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    return [
        {
            "title": row.title,
            "summary": row.summary,
            "topic": row.sector or row.topic,
            "region": row.country,
            "published_at": row.published_at.date().isoformat() if row.published_at else "chưa có dữ liệu",
            "source": row.source,
            "url": row.url,
        }
        for row in rows
    ]


async def _store_news(topic: str, items: list[dict]) -> None:
    async with get_session() as session:
        for item in items:
            session.add(
                StartupCache(
                    topic=topic,
                    title=item.get("title"),
                    summary=item.get("summary"),
                    url=item.get("url"),
                    source=item.get("source"),
                    country=item.get("region"),
                    sector=item.get("topic"),
                    published_at=_parse_date(item.get("published_at")),
                )
            )


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _infer_trend(news_items: list[dict], funding_items: list[dict]) -> str:
    topics = [item.get("topic") for item in news_items if item.get("topic")]
    industries = [item.get("industry") for item in funding_items if item.get("industry")]
    combined = [str(item).lower() for item in topics + industries]
    if not combined:
        return "chưa có dữ liệu"
    for candidate in ["ai", "fintech", "saas", "ecommerce", "healthtech", "edtech"]:
        if any(candidate in item for item in combined):
            return f"Sample trend: nhiều tín hiệu xoay quanh {candidate}."
    return "Sample trend: dữ liệu mẫu cho thấy hoạt động startup phân tán theo nhiều ngành."
