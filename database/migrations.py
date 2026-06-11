"""
Database migration helpers.

Provides a lightweight ``init_db`` coroutine that creates all
tables declared on the ORM ``Base`` metadata.  Intended for
first-run bootstrapping; production deployments should consider
Alembic for incremental migrations.
"""

import logging

from database.db import engine
from database.models import Base

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified successfully.")
