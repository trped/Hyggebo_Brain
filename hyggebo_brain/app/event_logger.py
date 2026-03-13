"""Persist occupancy changes and sensor readings to PostgreSQL.

Hooks into SensorFusion and HAStateTracker to log state transitions
to the events and sensor_data tables.
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger("hyggebo_brain.event_logger")


class EventLogger:
    """Writes fusion events and sensor data to PostgreSQL."""

    def __init__(self, db: "Database") -> None:
        self._db = db

    # ── Sensor data ───────────────────────────────────────────

    async def log_sensor(
        self,
        entity_id: str,
        state: str,
        value: float | None = None,
        attrs: dict | None = None,
        room_id: str | None = None,
    ) -> None:
        """Insert a sensor reading into sensor_data."""
        try:
            await self._db.execute(
                """
                INSERT INTO sensor_data (ts, entity_id, state, value, attrs, room_id)
                VALUES (now(), $1, $2, $3, $4::jsonb, $5)
                """,
                entity_id, state, value, _to_json(attrs), room_id,
            )
        except Exception:
            logger.exception("Failed to log sensor data for %s", entity_id)

    # ── Events ────────────────────────────────────────────────

    async def log_event(
        self,
        event_type: str,
        source: str = "brain",
        data: dict | None = None,
        room_id: str | None = None,
    ) -> None:
        """Insert an event into the events table."""
        try:
            await self._db.execute(
                """
                INSERT INTO events (ts, event_type, source, data, room_id)
                VALUES (now(), $1, $2, $3::jsonb, $4)
                """,
                event_type, source, _to_json(data), room_id,
            )
        except Exception:
            logger.exception("Failed to log event %s", event_type)

    # ── Convenience: log occupancy change ─────────────────────

    async def log_occupancy_change(
        self,
        room_id: str,
        old_state: str,
        new_state: str,
        source: str,
        attrs: dict | None = None,
    ) -> None:
        """Log a room occupancy transition as both sensor data and event."""
        await self.log_sensor(
            entity_id=f"brain.room_{room_id}_occupancy",
            state=new_state,
            room_id=room_id,
            attrs={"source": source, **(attrs or {})},
        )
        await self.log_event(
            event_type="occupancy_change",
            source="fusion",
            data={
                "old": old_state,
                "new": new_state,
                "fusion_source": source,
                **(attrs or {}),
            },
            room_id=room_id,
        )

    async def log_house_state_change(
        self,
        entity: str,
        old_value: str,
        new_value: str,
    ) -> None:
        """Log a hus_tilstand or tid_pa_dagen transition."""
        await self.log_event(
            event_type="house_state_change",
            source="ha_state",
            data={"entity": entity, "old": old_value, "new": new_value},
        )


def _to_json(d: dict | None) -> str | None:
    """Convert dict to JSON string for asyncpg jsonb parameter."""
    if d is None:
        return None
    import json
    return json.dumps(d)
