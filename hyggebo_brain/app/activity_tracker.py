"""Track and aggregate occupancy patterns per room/day/hour."""
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)


class ActivityTracker:
    """Aggregates sensor data into activity_patterns for ML learning."""

    def __init__(self, db: "Database") -> None:
        self.db = db

    async def update_patterns(self, lookback_hours: int = 168) -> int:
        """Aggregate recent sensor/event data into activity_patterns.

        Looks at events with event_type 'occupancy_change' from the
        last `lookback_hours` (default 7 days) and builds per-room,
        per-day-of-week, per-hour statistics.

        Returns number of pattern rows upserted.
        """
        cutoff = datetime.now() - timedelta(hours=lookback_hours)

        # Get occupancy events grouped by room, day_of_week, hour
        rows = await self.db.fetch(
            """
            SELECT
                room_id,
                EXTRACT(DOW FROM ts)::int AS dow,
                EXTRACT(HOUR FROM ts)::int AS hour,
                COUNT(*) AS event_count,
                COUNT(*) FILTER (
                    WHERE data->>'occupancy' = 'occupied'
                ) AS occupied_count
            FROM events
            WHERE event_type = 'occupancy_change'
              AND ts >= $1
              AND room_id IS NOT NULL
            GROUP BY room_id, dow, hour
            ORDER BY room_id, dow, hour
            """,
            cutoff,
        )

        upserted = 0
        for row in rows:
            room_id = row["room_id"]
            # Convert PostgreSQL DOW (0=Sunday) to our format (0=Monday)
            pg_dow = row["dow"]
            dow = (pg_dow - 1) % 7  # 0=Monday, 6=Sunday
            hour = row["hour"]
            total = row["event_count"]
            occupied = row["occupied_count"]
            pct = (occupied / total * 100) if total > 0 else 0.0

            await self.db.execute(
                """
                INSERT INTO activity_patterns
                    (room_id, day_of_week, hour, occupancy_pct, sample_count, updated_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (room_id, day_of_week, hour)
                DO UPDATE SET
                    occupancy_pct = (
                        activity_patterns.occupancy_pct * 0.7 + EXCLUDED.occupancy_pct * 0.3
                    ),
                    sample_count = activity_patterns.sample_count + EXCLUDED.sample_count,
                    updated_at = now()
                """,
                room_id,
                dow,
                hour,
                pct,
                total,
            )
            upserted += 1

        if upserted:
            logger.info("Updated %d activity pattern rows", upserted)
        return upserted

    async def get_patterns(self, room_id: str) -> list[dict]:
        """Get all activity patterns for a room."""
        rows = await self.db.fetch(
            """
            SELECT * FROM activity_patterns
            WHERE room_id = $1
            ORDER BY day_of_week, hour
            """,
            room_id,
        )
        return [dict(r) for r in rows]

    async def get_current_expected(self, room_id: str) -> dict:
        """Get expected occupancy for a room right now."""
        now = datetime.now()
        dow = now.weekday()  # 0=Monday
        hour = now.hour

        row = await self.db.fetchrow(
            """
            SELECT occupancy_pct, avg_duration, sample_count
            FROM activity_patterns
            WHERE room_id = $1 AND day_of_week = $2 AND hour = $3
            """,
            room_id,
            dow,
            hour,
        )
        if row:
            return {
                "room_id": room_id,
                "day_of_week": dow,
                "hour": hour,
                "occupancy_pct": row["occupancy_pct"],
                "avg_duration": row["avg_duration"],
                "sample_count": row["sample_count"],
            }
        return {
            "room_id": room_id,
            "day_of_week": dow,
            "hour": hour,
            "occupancy_pct": 0.0,
            "avg_duration": 0.0,
            "sample_count": 0,
        }

    async def get_all_expected(self) -> list[dict]:
        """Get current expected occupancy for all rooms."""
        now = datetime.now()
        dow = now.weekday()
        hour = now.hour

        rows = await self.db.fetch(
            """
            SELECT room_id, occupancy_pct, avg_duration, sample_count
            FROM activity_patterns
            WHERE day_of_week = $1 AND hour = $2
            ORDER BY room_id
            """,
            dow,
            hour,
        )
        return [dict(r) for r in rows]
