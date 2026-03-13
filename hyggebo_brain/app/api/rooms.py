"""REST API endpoints for room occupancy and fusion data."""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("/rooms")
async def list_rooms(request: Request) -> list[dict[str, Any]]:
    """List all rooms with current occupancy state."""
    fusion = request.app.state.fusion
    if not fusion:
        raise HTTPException(503, "Sensor fusion not running")

    states = fusion.get_all_states()
    return [
        {"room_id": room_id, **state}
        for room_id, state in states.items()
    ]


@router.get("/rooms/{room_id}")
async def get_room(request: Request, room_id: str) -> dict[str, Any]:
    """Get detailed occupancy state for a single room."""
    fusion = request.app.state.fusion
    if not fusion:
        raise HTTPException(503, "Sensor fusion not running")

    state = fusion.get_room_state(room_id)
    if state is None:
        raise HTTPException(404, f"Room '{room_id}' not found")

    return {"room_id": room_id, **state}


@router.get("/rooms/{room_id}/history")
async def get_room_history(
    request: Request,
    room_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Get recent sensor data history for a room."""
    db = request.app.state.db
    if not db.is_connected:
        raise HTTPException(503, "Database not connected")

    rows = await db.fetch(
        """
        SELECT ts, entity_id, state, value, attrs
        FROM sensor_data
        WHERE room_id = $1
          AND ts > now() - make_interval(hours => $2)
        ORDER BY ts DESC
        LIMIT $3
        """,
        room_id, hours, limit,
    )
    return [
        {
            "ts": row["ts"].isoformat(),
            "entity_id": row["entity_id"],
            "state": row["state"],
            "value": row["value"],
            "attrs": row["attrs"],
        }
        for row in rows
    ]


@router.get("/persons")
async def list_persons(request: Request) -> dict[str, str]:
    """Get current person states (home/not_home)."""
    fusion = request.app.state.fusion
    if not fusion:
        raise HTTPException(503, "Sensor fusion not running")

    return fusion.get_person_states()


@router.get("/state")
async def get_house_state(request: Request) -> dict[str, Any]:
    """Get current hus_tilstand and tid_pa_dagen."""
    tracker = request.app.state.ha_state_tracker
    if not tracker:
        raise HTTPException(503, "HA state tracker not running")

    return tracker.get_state_summary()
