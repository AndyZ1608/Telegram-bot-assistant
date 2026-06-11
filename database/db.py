"""
Async database engine and session management.

Provides a shared async SQLAlchemy engine and a context-managed
session factory with automatic commit/rollback semantics.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

import config

engine = create_async_engine(config.DATABASE_URL, echo=False)
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session with auto commit/rollback.

    Usage::

        async with get_session() as session:
            session.add(obj)
            # commits automatically on clean exit
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
