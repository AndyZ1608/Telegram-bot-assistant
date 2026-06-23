"""Two-user isolation smoke test.

Run after installing requirements:
    python scripts/security_isolation_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "isolation.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
        os.environ.setdefault("TIMEZONE", "Asia/Ho_Chi_Minh")
        os.environ.setdefault("DEFAULT_TIMEZONE", "Asia/Ho_Chi_Minh")

        from database.migrations import init_db
        from services.accounting_service import (
            ExpenseNotFoundError,
            delete_expense,
            ensure_user,
            export_expenses_csv,
            list_expenses,
        )
        from services.jars_service import add_jars_expense, allocate_income, get_jars_overview
        from services.reminder_service import due_daily_reminder, get_or_create_user_settings, update_daily_reminder

        await init_db()
        user_a = await ensure_user(111111, "user_a", "User A")
        user_b = await ensure_user(222222, "user_b", "User B")

        await allocate_income(user_a.id, 20_000_000)
        await allocate_income(user_b.id, 30_000_000)
        await add_jars_expense(user_a.id, "NEC", 100_000, "A breakfast")
        await add_jars_expense(user_b.id, "PLAY", 500_000, "B play")

        overview_a = await get_jars_overview(user_a.id)
        overview_b = await get_jars_overview(user_b.id)
        assert overview_a.income == 20_000_000
        assert overview_b.income == 30_000_000
        assert next(j for j in overview_a.jars if j.code == "NEC").spent == 100_000
        assert next(j for j in overview_a.jars if j.code == "PLAY").spent == 0
        assert next(j for j in overview_b.jars if j.code == "PLAY").spent == 500_000
        assert next(j for j in overview_b.jars if j.code == "NEC").spent == 0

        expense_a = (await list_expenses(user_a.id))[0]
        try:
            await delete_expense(user_b.id, expense_a.id)
        except ExpenseNotFoundError:
            pass
        else:
            raise AssertionError("User B deleted User A expense")

        _, export_a = await export_expenses_csv(user_a.id, 111111)
        export_text = export_a.decode("utf-8")
        assert "A breakfast" in export_text
        assert "B play" not in export_text

        await get_or_create_user_settings(user_a.id)
        await update_daily_reminder(user_a.id, enabled=True, time_value="21:00")
        local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).replace(hour=21, minute=0, second=0, microsecond=0)
        message = await due_daily_reminder(
            await get_or_create_user_settings(user_a.id),
            local.astimezone(ZoneInfo("UTC")),
        )
        assert message is not None
        assert message.user_id == user_a.id
        assert message.telegram_user_id == 111111

        print("PASS: multi-user isolation smoke test")


if __name__ == "__main__":
    asyncio.run(main())
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
