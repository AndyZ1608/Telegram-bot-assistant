"""
APScheduler integration for per-user automation jobs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from services.reminder_service import (
    AutomationMessage,
    due_daily_reminder,
    due_monthly_report,
    due_price_alerts,
    due_startup_digest,
    list_user_settings,
    mark_sent,
)
from services.month_close_service import due_auto_month_close, list_auto_month_close_settings

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # pragma: no cover - handled at runtime if dependency missing
    AsyncIOScheduler = None


logger = logging.getLogger(__name__)
_scheduler = None


def start_scheduler(application) -> None:
    """Start automation scheduler for the Telegram application."""
    global _scheduler
    if not config.ENABLE_SCHEDULER:
        logger.info("Scheduler disabled by ENABLE_SCHEDULER=false.")
        return
    if AsyncIOScheduler is None:
        logger.error("APScheduler is not installed; automation scheduler not started.")
        return
    if _scheduler and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler(timezone=ZoneInfo(config.DEFAULT_TIMEZONE))
    _scheduler.add_job(
        poll_automation_jobs,
        "interval",
        minutes=1,
        args=[application],
        id="automation_poll",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Automation scheduler started.")


def stop_scheduler() -> None:
    """Stop scheduler if it is running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Automation scheduler stopped.")
    _scheduler = None


async def poll_automation_jobs(application) -> None:
    """Poll all user settings and send due automation messages."""
    try:
        settings_rows = await list_user_settings()
        now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
        for settings in settings_rows:
            await _send_if_due(application, await due_daily_reminder(settings, now_utc))
            await _send_if_due(application, await due_monthly_report(settings, now_utc))
            await _send_if_due(application, await due_startup_digest(settings, now_utc))
            for message in await due_price_alerts(settings):
                await _send_if_due(application, message)
        for settings in await list_auto_month_close_settings():
            month_close_message = await due_auto_month_close(settings, now_utc)
            if month_close_message:
                user_id, telegram_user_id, text, job_type, period_key = month_close_message
                await _send_if_due(application, AutomationMessage(user_id, telegram_user_id, text, job_type, period_key))
    except Exception:
        logger.exception("Automation scheduler tick failed.")


async def _send_if_due(application, message: AutomationMessage | None) -> None:
    if message is None:
        return
    try:
        await application.bot.send_message(chat_id=message.telegram_user_id, text=message.text)
        await mark_sent(message.user_id, message.job_type, message.period_key)
    except Exception:
        logger.exception(
            "Failed to send automation message user_id=%s job=%s period=%s",
            message.user_id,
            message.job_type,
            message.period_key,
        )
