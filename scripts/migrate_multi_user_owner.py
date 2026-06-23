"""Backfill legacy single-owner rows to internal users.id.

This script is intentionally conservative:
- only supports SQLite DATABASE_URL values used by this project;
- creates a timestamped DB backup before writes;
- requires OWNER_TELEGRAM_USER_ID;
- updates rows whose user_id still equals the owner's Telegram ID.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


PERSONAL_TABLES = [
    "monthly_income",
    "budget_jars",
    "expenses",
    "watchlist",
    "price_alerts",
    "portfolio",
    "user_settings",
    "automation_log",
    "jars_settings",
    "monthly_closures",
    "month_close_settings",
    "settings",
]


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.replace("sqlite:///", "", 1)).resolve()
    if database_url.startswith("sqlite+aiosqlite:///"):
        return Path(database_url.replace("sqlite+aiosqlite:///", "", 1)).resolve()
    raise SystemExit("Only sqlite:/// DATABASE_URL is supported by this migration script.")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_owner(conn: sqlite3.Connection, telegram_user_id: int) -> int:
    if not _table_exists(conn, "users"):
        raise SystemExit("Table users does not exist. Run normal DB init first.")
    columns = _columns(conn, "users")
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN updated_at DATETIME")
        columns = _columns(conn, "users")
    row = conn.execute(
        "SELECT id FROM users WHERE telegram_user_id=?",
        (telegram_user_id,),
    ).fetchone()
    if row:
        return int(row[0])

    now = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    if "updated_at" in columns:
        conn.execute(
            "INSERT INTO users (telegram_user_id, username, full_name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (telegram_user_id, None, "Legacy owner", now, now),
        )
    else:
        conn.execute(
            "INSERT INTO users (telegram_user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
            (telegram_user_id, None, "Legacy owner", now),
        )
    return int(conn.execute("SELECT id FROM users WHERE telegram_user_id=?", (telegram_user_id,)).fetchone()[0])


def main() -> None:
    _load_dotenv()
    owner_raw = os.getenv("OWNER_TELEGRAM_USER_ID", "").strip()
    if not owner_raw:
        raise SystemExit("OWNER_TELEGRAM_USER_ID is required. Refusing to guess owner.")
    try:
        owner_telegram_id = int(owner_raw)
    except ValueError as exc:
        raise SystemExit("OWNER_TELEGRAM_USER_ID must be an integer Telegram user id.") from exc

    db_path = _sqlite_path(os.getenv("DATABASE_URL", "sqlite:///bot.db"))
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir / f"{db_path.stem}_multi_user_backup_{datetime.utcnow():%Y%m%d_%H%M%S}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")
        owner_internal_id = _ensure_owner(conn, owner_telegram_id)
        print(f"Owner telegram_user_id={owner_telegram_id} internal users.id={owner_internal_id}")

        for table in PERSONAL_TABLES:
            if not _table_exists(conn, table) or "user_id" not in _columns(conn, table):
                continue
            updated = conn.execute(
                f"UPDATE {table} SET user_id=? WHERE user_id=?",
                (owner_internal_id, owner_telegram_id),
            ).rowcount
            print(f"{table}: backfilled {updated} row(s)")

        conn.commit()
        print("Multi-user owner migration completed.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
