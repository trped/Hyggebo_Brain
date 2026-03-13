"""Health check endpoint with live connection checks."""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    """Health check - returns live component status."""
    db = getattr(request.app.state, "db", None)
    mqtt = getattr(request.app.state, "mqtt", None)
    ha = getattr(request.app.state, "ha", None)
    fusion = getattr(request.app.state, "fusion", None)
    ha_state = getattr(request.app.state, "ha_state_tracker", None)
    event_logger = getattr(request.app.state, "event_logger", None)

    # Database: try a real query
    db_ok = False
    if db and db.is_connected:
        try:
            await db.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            pass

    mqtt_ok = bool(mqtt and mqtt.connected)
    ha_ok = bool(ha and ha.connected)
    fusion_ok = bool(fusion and fusion._running)
    ha_state_ok = bool(ha_state)
    logger_ok = bool(event_logger)

    all_ok = db_ok and mqtt_ok and ha_ok
    status = "ok" if all_ok else "degraded"

    return {
        "status": status,
        "version": "0.3.0",
        "components": {
            "database": "connected" if db_ok else "disconnected",
            "mqtt": "connected" if mqtt_ok else "disconnected",
            "ha_websocket": "connected" if ha_ok else "disconnected",
            "sensor_fusion": "running" if fusion_ok else "stopped",
            "ha_state_tracker": "running" if ha_state_ok else "stopped",
            "event_logger": "active" if logger_ok else "inactive",
        },
    }
