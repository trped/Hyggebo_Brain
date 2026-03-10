"""Home Assistant WebSocket API client."""
import asyncio
import json
import logging
from typing import Any, Callable, Optional

import aiohttp

logger = logging.getLogger("hyggebo_brain.ha_client")

# HA WebSocket API message types
AUTH_REQUIRED = "auth_required"
AUTH_OK = "auth_ok"
AUTH_INVALID = "auth_invalid"
RESULT = "result"
EVENT = "event"


class HAClient:
    """Async Home Assistant WebSocket API client.

    Uses SUPERVISOR_TOKEN for authentication when running as HA addon.
    Connects to ws://supervisor/core/websocket for WebSocket API.
    """

    def __init__(self, supervisor_token: str):
        self._token = supervisor_token
        self._ws_url = "ws://supervisor/core/websocket"
        self._api_url = "http://supervisor/core/api"
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._event_handlers: dict[str, list[Callable]] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._connected = False
        self._reconnect_delay = 5

    # ── Connection lifecycle ──────────────────────────────────

    async def connect(self) -> None:
        """Connect and authenticate to HA WebSocket API."""
        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(
                self._ws_url, heartbeat=30
            )
            # Wait for auth_required
            msg = await self._ws.receive_json()
            if msg.get("type") != AUTH_REQUIRED:
                raise ConnectionError(f"Expected auth_required, got {msg}")

            # Send auth
            await self._ws.send_json({
                "type": "auth",
                "access_token": self._token,
            })

            # Wait for auth result
            msg = await self._ws.receive_json()
            if msg.get("type") == AUTH_INVALID:
                raise PermissionError(f"Auth failed: {msg.get('message')}")
            if msg.get("type") != AUTH_OK:
                raise ConnectionError(f"Expected auth_ok, got {msg}")

            self._connected = True
            self._listen_task = asyncio.create_task(self._listener())
            logger.info("Connected to Home Assistant WebSocket API")

        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """Close WebSocket connection."""
        self._connected = False
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        # Cancel pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()
        logger.info("Disconnected from Home Assistant")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        await self.close()
        delay = self._reconnect_delay
        while True:
            try:
                logger.info(f"Reconnecting in {delay}s...")
                await asyncio.sleep(delay)
                await self.connect()
                # Re-subscribe to events
                for event_type in self._event_handlers:
                    await self._subscribe_events(event_type)
                return
            except Exception as e:
                logger.error(f"Reconnect failed: {e}")
                delay = min(delay * 2, 60)

    # ── Message handling ──────────────────────────────────────

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def _send(self, msg: dict) -> dict:
        """Send message and wait for response."""
        msg_id = self._next_id()
        msg["id"] = msg_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        await self._ws.send_json(msg)
        try:
            return await asyncio.wait_for(fut, timeout=30)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"No response for message {msg_id}")

    async def _listener(self) -> None:
        """Background task: listen for incoming WebSocket messages."""
        try:
            async for raw in self._ws:
                if raw.type == aiohttp.WSMsgType.TEXT:
                    msg = json.loads(raw.data)
                    msg_type = msg.get("type")

                    if msg_type == RESULT:
                        msg_id = msg.get("id")
                        fut = self._pending.pop(msg_id, None)
                        if fut and not fut.done():
                            fut.set_result(msg)

                    elif msg_type == EVENT:
                        event = msg.get("event", {})
                        event_type = event.get("event_type", "")
                        handlers = self._event_handlers.get(event_type, [])
                        for handler in handlers:
                            try:
                                await handler(event)
                            except Exception as e:
                                logger.error(f"Event handler error: {e}")

                elif raw.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}")
        finally:
            if self._connected:
                logger.warning("WebSocket connection lost, reconnecting...")
                asyncio.create_task(self.reconnect())

    # ── Public API ────────────────────────────────────────────

    async def get_states(self) -> list[dict]:
        """Get all entity states."""
        result = await self._send({"type": "get_states"})
        if result.get("success"):
            return result.get("result", [])
        raise RuntimeError(f"get_states failed: {result}")

    async def get_state(self, entity_id: str) -> Optional[dict]:
        """Get state for a single entity."""
        states = await self.get_states()
        for state in states:
            if state.get("entity_id") == entity_id:
                return state
        return None

    async def call_service(
        self,
        domain: str,
        service: str,
        data: Optional[dict] = None,
        target: Optional[dict] = None,
    ) -> dict:
        """Call a Home Assistant service."""
        msg: dict[str, Any] = {
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if data:
            msg["service_data"] = data
        if target:
            msg["target"] = target
        return await self._send(msg)

    async def _subscribe_events(self, event_type: str) -> None:
        """Subscribe to a specific event type."""
        await self._send({
            "type": "subscribe_events",
            "event_type": event_type,
        })

    async def subscribe(
        self, event_type: str, handler: Callable
    ) -> None:
        """Subscribe to events with a handler callback."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
            if self._connected:
                await self._subscribe_events(event_type)
        self._event_handlers[event_type].append(handler)
        logger.info(f"Subscribed to {event_type}")

    # ── REST API helpers ──────────────────────────────────────

    async def rest_get(self, path: str) -> dict:
        """GET request to HA REST API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._session.get(
            f"{self._api_url}{path}", headers=headers
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def rest_post(self, path: str, data: dict = None) -> dict:
        """POST request to HA REST API."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with self._session.post(
            f"{self._api_url}{path}", headers=headers, json=data or {}
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    @property
    def connected(self) -> bool:
        return self._connected
