"""
Database migration helpers.

Provides a lightweight ``init_db`` coroutine that creates all
tables declared on the ORM ``Base`` metadata.  Intended for
first-run bootstrapping; production deployments should consider
Alembic for incremental migrations.
"""

import logging

from sqlalchemy import inspect, text

from database.db import engine
from database.models import Base

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_expense_export_columns(conn)
    logger.info("Database tables created/verified successfully.")


async def _ensure_expense_export_columns(conn) -> None:
    """Add nullable export-related columns for existing SQLite deployments."""
    columns = await conn.run_sync(
        lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("expenses")}
    )
    if "category" not in columns:
        await conn.execute(text("ALTER TABLE expenses ADD COLUMN category VARCHAR"))
        logger.info("Added expenses.category column.")
    if "transaction_date" not in columns:
        await conn.execute(text("ALTER TABLE expenses ADD COLUMN transaction_date DATE"))
        await conn.execute(
            text("UPDATE expenses SET transaction_date = DATE(created_at) WHERE transaction_date IS NULL")
        )
        logger.info("Added expenses.transaction_date column with created_at fallback.")
