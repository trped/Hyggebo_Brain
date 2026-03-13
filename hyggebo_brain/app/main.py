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
from api.rooms import router as rooms_router
from api.events import router as events_router
from database import Database
from discovery import publish_discovery, remove_discovery
from event_logger import EventLogger
from fusion import SensorFusion
from ha_client import HAClient
from ha_state import HAStateTracker
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
    version="0.2.0",
    description="Smart home intelligence engine",
)

app.include_router(health_router, prefix="/api")
app.include_router(rooms_router, prefix="/api")
app.include_router(events_router, prefix="/api")

# Shared service instances
db = Database(settings)
ha = HAClient(supervisor_token=settings.supervisor_token)
mqtt = MQTTClient(
    host=settings.mqtt_host,
    port=settings.mqtt_port,
    username=settings.mqtt_user,
    password=settings.mqtt_password,
)

# Intelligence modules (initialized after connections are up)
event_logger: EventLogger | None = None
fusion: SensorFusion | None = None
ha_state_tracker: HAStateTracker | None = None
scenario_engine = None  # initialized in startup


@app.on_event("startup")
async def startup():
    """Initialize all connections on startup."""
    global event_logger, fusion, ha_state_tracker, scenario_engine

    logger.info("Hyggebo Brain v0.2.0 starting...")

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

    # 2. Event logger (needs DB)
    event_logger = EventLogger(db)
    logger.info("Event logger initialized")

    # 3. MQTT (EMQX)
    try:
        await mqtt.connect()
        mqtt.publish_sensor("system", "starting", {"version": "0.2.0"})
        logger.info("MQTT connected to EMQX")
    except Exception as e:
        logger.error(f"MQTT connection failed: {e}")
        # Non-fatal: continue without MQTT, retry later

    # 4. MQTT auto discovery (publish sensor configs to HA)
    if mqtt.connected:
        try:
            publish_discovery(mqtt)
            logger.info("MQTT discovery configs published")
        except Exception as e:
            logger.error(f"MQTT discovery publish failed: {e}")

    # 5. Home Assistant WebSocket
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

    # 6. HA state tracker (hus_tilstand + tid_pa_dagen)
    if ha.connected and mqtt.connected:
        try:
            ha_state_tracker = HAStateTracker(ha, mqtt, event_logger)
            await ha_state_tracker.start()
            logger.info("HA state tracker started")
        except Exception as e:
            logger.error(f"HA state tracker failed: {e}")

    # 7. Sensor fusion (room occupancy)
    if ha.connected and mqtt.connected:
        try:
            fusion = SensorFusion(ha, mqtt, event_logger)
            await fusion.start()
            logger.info("Sensor fusion started")
        except Exception as e:
            logger.error(f"Sensor fusion failed: {e}")

    # 8. Scenario engine (autonomous actions)
    if fusion and ha_state_tracker and mqtt.connected:
        try:
            from scenarios import ScenarioEngine
            scenario_engine = ScenarioEngine(
                fusion=fusion,
                ha_state=ha_state_tracker,
                ha=ha,
                mqtt=mqtt,
                event_logger=event_logger,
            )
            await scenario_engine.start()
            logger.info("Scenario engine started")
        except Exception as e:
            logger.error(f"Scenario engine failed: {e}")

    # 9. Partition cleanup scheduler
    from scheduler import start_scheduler
    start_scheduler(db)
    logger.info("Partition cleanup scheduler started")

    # Make services available to API routes
    app.state.db = db
    app.state.ha = ha
    app.state.mqtt = mqtt
    app.state.event_logger = event_logger
    app.state.fusion = fusion
    app.state.ha_state_tracker = ha_state_tracker
    app.state.scenario_engine = scenario_engine

    # Mark system online
    if mqtt.connected:
        mqtt.publish_sensor("system", "online", {"version": "0.2.0"})

    logger.info("Startup complete.")


@app.on_event("shutdown")
async def shutdown():
    """Clean up all connections on shutdown."""
    global fusion, ha_state_tracker, scenario_engine

    logger.info("Shutting down Hyggebo Brain...")

    # Stop intelligence modules first
    if scenario_engine:
        await scenario_engine.stop()
        scenario_engine = None

    if fusion:
        await fusion.stop()
        fusion = None

    if ha_state_tracker:
        await ha_state_tracker.stop()
        ha_state_tracker = None

    # Clean up connections
    if mqtt.connected:
        mqtt.publish_sensor("system", "offline")
        remove_discovery(mqtt)
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
