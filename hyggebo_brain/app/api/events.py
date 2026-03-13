"""REST API endpoints for event log queries."""
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("/events")
async def list_events(
    request: Request,
    event_type: str | None = Query(default=None),
    room_id: str | None = Query(default=None),
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Query logged events with optional filters."""
    db = request.app.state.db
    if not db.is_connected:
        raise HTTPException(503, "Database not connected")

    conditions = ["ts > now() - make_interval(hours => $1)"]
    params: list = [hours]
    idx = 2

    if event_type:
        conditions.append(f"event_type = ${idx}")
        params.append(event_type)
        idx += 1

    if room_id:
        conditions.append(f"room_id = ${idx}")
        params.append(room_id)
        idx += 1

    where = " AND ".join(conditions)
    params.append(limit)

    rows = await db.fetch(
        f"""
        SELECT ts, event_type, source, data, room_id
        FROM events
        WHERE {where}
        ORDER BY ts DESC
        LIMIT ${idx}
        """,
        *params,
    )
    return [
        {
            "ts": row["ts"].isoformat(),
            "event_type": row["event_type"],
            "source": row["source"],
            "data": row["data"],
            "room_id": row["room_id"],
        }
        for row in rows
    ]
