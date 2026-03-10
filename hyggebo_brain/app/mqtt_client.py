"""EMQX MQTT client for Hyggebo Brain."""
import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

logger = logging.getLogger("hyggebo_brain.mqtt_client")

# Topic prefixes
TOPIC_PREFIX = "hyggebo_brain"
STATE_TOPIC = f"{TOPIC_PREFIX}/state"
SENSOR_TOPIC = f"{TOPIC_PREFIX}/sensor"
EVENT_TOPIC = f"{TOPIC_PREFIX}/event"
CMD_TOPIC = f"{TOPIC_PREFIX}/cmd"
DISCOVERY_PREFIX = "homeassistant"


class MQTTClient:
    """Paho MQTT client wrapper for EMQX broker.

    Runs paho's network loop in a background thread while exposing
    async-friendly publish/subscribe methods.
    """

    def __init__(
        self,
        host: str = "a0d7b954-emqx",
        port: int = 1883,
        username: str = "admin",
        password: str = "",
        client_id: str = "hyggebo_brain",
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client_id = client_id

        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._subscriptions: dict[str, list[Callable]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ── Connection lifecycle ──────────────────────────────────

    async def connect(self) -> None:
        """Connect to EMQX broker."""
        self._loop = asyncio.get_event_loop()
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
        )
        self._client.username_pw_set(self._username, self._password)

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # Will message for availability
        self._client.will_set(
            f"{STATE_TOPIC}/availability",
            payload="offline",
            qos=1,
            retain=True,
        )

        try:
            self._client.connect(self._host, self._port, keepalive=60)
            self._client.loop_start()
            # Wait for connection with timeout
            for _ in range(50):  # 5 seconds
                if self._connected:
                    break
                await asyncio.sleep(0.1)
            if not self._connected:
                raise ConnectionError(
                    f"MQTT connect timeout to {self._host}:{self._port}"
                )
            logger.info(f"Connected to EMQX at {self._host}:{self._port}")
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Disconnect from EMQX broker."""
        if self._client:
            # Publish offline before disconnecting
            self._client.publish(
                f"{STATE_TOPIC}/availability",
                payload="offline",
                qos=1,
                retain=True,
            )
            self._client.loop_stop()
            self._client.disconnect()
        self._connected = False
        logger.info("Disconnected from EMQX")

    # ── Paho callbacks (run in paho thread) ───────────────────

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """Called when connected to broker."""
        if rc == 0:
            self._connected = True
            logger.info("MQTT connected successfully")
            # Publish online
            client.publish(
                f"{STATE_TOPIC}/availability",
                payload="online",
                qos=1,
                retain=True,
            )
            # Re-subscribe to all topics
            for topic in self._subscriptions:
                client.subscribe(topic, qos=1)
                logger.debug(f"Re-subscribed to {topic}")
        else:
            logger.error(f"MQTT connect failed with rc={rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        """Called when disconnected from broker."""
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnect (rc={rc}), auto-reconnecting...")

    def _on_message(self, client, userdata, msg):
        """Called when message received - dispatches to async handlers."""
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload.decode("utf-8", errors="replace")

        # Find matching subscriptions (support wildcards)
        for pattern, handlers in self._subscriptions.items():
            if mqtt.topic_matches_sub(pattern, topic):
                for handler in handlers:
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(
                            self._safe_call(handler, topic, payload),
                            self._loop,
                        )

    async def _safe_call(self, handler: Callable, topic: str, payload: Any):
        """Safely call an async handler."""
        try:
            await handler(topic, payload)
        except Exception as e:
            logger.error(f"MQTT handler error on {topic}: {e}")

    # ── Public API ────────────────────────────────────────────

    def publish(
        self,
        topic: str,
        payload: Any,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a message to MQTT topic."""
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=qos, retain=retain)

    def publish_sensor(
        self,
        sensor_id: str,
        state: Any,
        attributes: Optional[dict] = None,
    ) -> None:
        """Publish sensor state update."""
        payload = {
            "state": state,
            "attributes": attributes or {},
            "timestamp": time.time(),
        }
        self.publish(
            f"{SENSOR_TOPIC}/{sensor_id}",
            payload,
            retain=True,
        )

    def publish_event(
        self,
        event_type: str,
        data: Optional[dict] = None,
    ) -> None:
        """Publish an event."""
        payload = {
            "event_type": event_type,
            "data": data or {},
            "timestamp": time.time(),
        }
        self.publish(f"{EVENT_TOPIC}/{event_type}", payload)

    async def subscribe(
        self, topic: str, handler: Callable
    ) -> None:
        """Subscribe to a topic with an async handler."""
        if topic not in self._subscriptions:
            self._subscriptions[topic] = []
            if self._connected:
                self._client.subscribe(topic, qos=1)
        self._subscriptions[topic].append(handler)
        logger.info(f"Subscribed to MQTT topic: {topic}")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def topic_prefix(self) -> str:
        return TOPIC_PREFIX
