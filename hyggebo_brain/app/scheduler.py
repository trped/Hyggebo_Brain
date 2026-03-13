"""Background scheduler for periodic maintenance tasks.

Runs partition cleanup and partition creation on a daily schedule.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger("hyggebo_brain.scheduler")


def start_scheduler(db: "Database", activity_tracker=None, ml_engine=None) -> asyncio.Task:
    """Start the background maintenance scheduler."""
    return asyncio.create_task(_scheduler_loop(db, activity_tracker, ml_engine))


async def _scheduler_loop(db: "Database", activity_tracker=None, ml_engine=None) -> None:
    """Run maintenance tasks every 6 hours."""
    # Wait 60 seconds before first run (let system stabilize)
    await asyncio.sleep(60)

    while True:
        try:
            await _run_maintenance(db)
        except Exception:
            logger.exception("Scheduler maintenance error")

        # Update activity patterns and run ML analysis
        if activity_tracker:
            try:
                await activity_tracker.update_patterns()
                logger.info("Activity patterns updated")
            except Exception:
                logger.exception("Activity pattern update error")

        if ml_engine:
            try:
                count = await ml_engine.create_suggestion_rules()
                if count:
                    logger.info("ML engine created %d new suggestions", count)
            except Exception:
                logger.exception("ML analysis error")

        # Sleep 6 hours
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
