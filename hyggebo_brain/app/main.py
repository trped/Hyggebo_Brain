"""Hyggebo Brain - Smart home intelligence engine."""
import asyncio
import logging
import os
import signal
import sys

import uvicorn
from fastapi import FastAPI

from config import Settings
from api.health import router as health_router
from database import Database
from ha_client import HAClient
from mqtt_client import MQTTClient
from schema.init_schema import init_schema, ensure_partitions, ensure_event_partitions

settings = Settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hyggebo_brain")

app = FastAPI(
    title="Hyggebo Brain",
    version="0.1.0",
    description="Smart home intelligence engine",
)

app.include_router(health_router, prefix="/api")

# Shared service instances
db = Database(settings)
ha = HAClient(supervisor_token=settings.supervisor_token)
mqtt = MQTTClient(
    host=settings.mqtt_host,
    port=settings.mqtt_port,
    username=settings.mqtt_user,
    password=settings.mqtt_password,
)


@app.on_event("startup")
async def startup():
    """Initialize all connections on startup."""
    logger.info("Hyggebo Brain v0.1.0 starting...")

    # 1. Database
    try:
        await db.connect()
        await init_schema(db)
        await ensure_partitions(db)
        await ensure_event_partitions(db)
        logger.info("Database initialized with schema and partitions")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    # 2. MQTT (EMQX)
    try:
        await mqtt.connect()
        mqtt.publish_sensor("system", "starting", {"version": "0.1.0"})
        logger.info("MQTT connected to EMQX")
    except Exception as e:
        logger.error(f"MQTT connection failed: {e}")
        # Non-fatal: continue without MQTT, retry later

    # 3. Home Assistant WebSocket
    if settings.supervisor_token:
        try:
            await ha.connect()
            logger.info("Connected to Home Assistant WebSocket API")
        except Exception as e:
            logger.error(f"HA WebSocket connection failed: {e}")
            # Non-fatal: continue without HA, retry later
    else:
        logger.warning(
            "No SUPERVISOR_TOKEN - HA WebSocket disabled "
            "(normal when running outside HA addon)"
        )

    # Make services available to API routes
    app.state.db = db
    app.state.ha = ha
    app.state.mqtt = mqtt

    logger.info("Startup complete.")


@app.on_event("shutdown")
async def shutdown():
    """Clean up all connections on shutdown."""
    logger.info("Shutting down Hyggebo Brain...")

    if mqtt.connected:
        mqtt.publish_sensor("system", "offline")
        await mqtt.close()

    if ha.connected:
        await ha.close()

    await db.close()

    logger.info("Shutdown complete.")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8100,
        log_level=settings.log_level,
    )
