"""Persistence helpers for user-specific finance parser aliases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from database.db import get_session
from database.models import UserParserAlias


async def upsert_user_parser_alias(
    user_id: int,
    phrase: str,
    jar_code: str,
    category: str,
) -> UserParserAlias:
    normalized_phrase = " ".join((phrase or "").strip().lower().split())
    normalized_jar = (jar_code or "").strip().upper()
    normalized_category = (category or "").strip()
    if not normalized_phrase or not normalized_jar or not normalized_category:
        raise ValueError("phrase, jar_code and category are required")

    async with get_session() as session:
        result = await session.execute(
            select(UserParserAlias).where(
                UserParserAlias.user_id == user_id,
                UserParserAlias.phrase == normalized_phrase,
            )
        )
        alias = result.scalar_one_or_none()
        if alias is None:
            alias = UserParserAlias(
                user_id=user_id,
                phrase=normalized_phrase,
                jar_code=normalized_jar,
                category=normalized_category,
            )
            session.add(alias)
        else:
            alias.jar_code = normalized_jar
            alias.category = normalized_category
            alias.created_at = datetime.utcnow()
        return alias


async def list_user_parser_aliases(user_id: int) -> list[dict]:
    async with get_session() as session:
        result = await session.execute(
            select(UserParserAlias).where(UserParserAlias.user_id == user_id)
        )
        aliases = result.scalars().all()
        return [
            {
                "phrase": alias.phrase,
                "jar_code": alias.jar_code,
                "category": alias.category,
            }
            for alias in aliases
        ]
