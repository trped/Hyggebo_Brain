"""Health check endpoint."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check - returns component status."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "components": {
            "database": "not_connected",
            "mqtt": "not_connected",
            "ha_websocket": "not_connected",
        },
    }
