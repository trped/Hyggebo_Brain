"""Background scheduler for periodic maintenance tasks.

Runs partition cleanup daily, activity patterns every 30 min,
and ML analysis every 6 hours.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger("hyggebo_brain.scheduler")


def start_scheduler(db: "Database", activity_tracker=None, ml_engine=None) -> list[asyncio.Task]:
    """Start the background maintenance schedulers."""
    tasks = [
        asyncio.create_task(_maintenance_loop(db)),
        asyncio.create_task(_pattern_loop(activity_tracker)),
        asyncio.create_task(_ml_loop(ml_engine)),
    ]
    return tasks


async def _maintenance_loop(db: "Database") -> None:
    """Run partition maintenance every 6 hours."""
    await asyncio.sleep(60)
    while True:
        try:
            await _run_maintenance(db)
        except Exception:
            logger.exception("Scheduler maintenance error")
        await asyncio.sleep(6 * 3600)


async def _pattern_loop(activity_tracker=None) -> None:
    """Update activity patterns every 30 minutes."""
    if not activity_tracker:
        return
    await asyncio.sleep(30)  # Quick first run after 30s
    while True:
        try:
            count = await activity_tracker.update_patterns()
            if count:
                logger.info("Activity patterns updated (%d rows)", count)
        except Exception:
            logger.exception("Activity pattern update error")
        await asyncio.sleep(30 * 60)  # Every 30 minutes


async def _ml_loop(ml_engine=None) -> None:
    """Run ML analysis every 6 hours."""
    if not ml_engine:
        return
    await asyncio.sleep(120)  # First run after 2 minutes
    while True:
        try:
            count = await ml_engine.create_suggestion_rules()
            if count:
                logger.info("ML engine created %d new suggestions", count)
        except Exception:
            logger.exception("ML analysis error")
        await asyncio.sleep(6 * 3600)


async def _run_maintenance(db: "Database") -> None:
    """Execute all maintenance tasks."""
    from schema.init_schema import (
        ensure_partitions,
        ensure_event_partitions,
        drop_old_partitions,
    )

    logger.info("Running scheduled maintenance...")

    # Ensure future partitions exist
    await ensure_partitions(db, months_ahead=2)
    await ensure_event_partitions(db, weeks_ahead=4)

    # Drop old partitions (sensor_data: 90 days, events: 365 days)
    await drop_old_partitions(db)

    logger.info("Scheduled maintenance complete")
