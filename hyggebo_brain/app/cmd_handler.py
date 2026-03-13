"""MQTT command handler — accept control commands via MQTT.

Subscribes to hyggebo_brain/cmd/# and dispatches commands:
  - cmd/scenario/enable   — enable/disable a scenario rule
  - cmd/scenario/trigger  — force-trigger a scenario rule
  - cmd/room/override     — override room occupancy for N minutes
  - cmd/system/reload     — reload fusion states from HA

Commands are JSON payloads published by HA automations, Node-RED,
or other MQTT clients.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_logger import EventLogger
    from fusion import SensorFusion
    from mqtt_client import MQTTClient
    from scenarios import ScenarioEngine

logger = logging.getLogger("hyggebo_brain.cmd_handler")

CMD_TOPIC = "hyggebo_brain/cmd/#"


class CommandHandler:
    """Dispatches MQTT commands to the appropriate module."""

    def __init__(
        self,
        mqtt: "MQTTClient",
        fusion: "SensorFusion | None" = None,
        scenario_engine: "ScenarioEngine | None" = None,
        event_logger: "EventLogger | None" = None,
    ) -> None:
        self._mqtt = mqtt
        self._fusion = fusion
        self._scenario_engine = scenario_engine
        self._event_logger = event_logger
        # Room overrides: room_id → {"occupancy": str, "expires": float}
        self._room_overrides: dict[str, dict[str, Any]] = {}
        # Disabled scenario rules
        self._disabled_rules: set[str] = set()

    async def start(self) -> None:
        """Subscribe to command topics."""
        await self._mqtt.subscribe(CMD_TOPIC, self._on_command)
        logger.info("Command handler listening on %s", CMD_TOPIC)

    async def _on_command(self, topic: str, payload: Any) -> None:
        """Route incoming commands."""
        # topic format: hyggebo_brain/cmd/<category>/<action>
        parts = topic.split("/")
        if len(parts) < 4:
            logger.warning("Invalid command topic: %s", topic)
            return

        category = parts[2]
        action = parts[3]

        if not isinstance(payload, dict):
            logger.warning("Command payload must be JSON object: %s", topic)
            return

        logger.info("Command received: %s/%s", category, action)

        try:
            if category == "scenario":
                await self._handle_scenario_cmd(action, payload)
            elif category == "room":
                await self._handle_room_cmd(action, payload)
            elif category == "system":
                await self._handle_system_cmd(action, payload)
            else:
                logger.warning("Unknown command category: %s", category)
        except Exception:
            logger.exception("Error handling command %s/%s", category, action)

        # Log command event
        if self._event_logger:
            await self._event_logger.log_event(
                event_type="command_received",
                source="mqtt_cmd",
                data={"topic": topic, "category": category, "action": action, **payload},
            )

    # ── Scenario commands ─────────────────────────────────────

    async def _handle_scenario_cmd(self, action: str, payload: dict) -> None:
        """Handle scenario enable/disable/trigger commands."""
        rule_id = payload.get("rule_id")
        if not rule_id:
            logger.warning("Scenario command missing rule_id")
            return

        if action == "enable":
            self._disabled_rules.discard(rule_id)
            logger.info("Scenario rule enabled: %s", rule_id)
            self._mqtt.publish_event("scenario_enabled", {"rule_id": rule_id})

        elif action == "disable":
            self._disabled_rules.add(rule_id)
            logger.info("Scenario rule disabled: %s", rule_id)
            self._mqtt.publish_event("scenario_disabled", {"rule_id": rule_id})

        elif action == "trigger":
            if self._scenario_engine:
                # Force-trigger by resetting cooldown and running eval
                self._scenario_engine._last_triggered.pop(rule_id, None)
                logger.info("Scenario force-trigger requested: %s", rule_id)
                self._mqtt.publish_event("scenario_force_trigger", {"rule_id": rule_id})

    # ── Room commands ─────────────────────────────────────────

    async def _handle_room_cmd(self, action: str, payload: dict) -> None:
        """Handle room override commands."""
        room_id = payload.get("room_id")
        if not room_id:
            logger.warning("Room command missing room_id")
            return

        if action == "override":
            occupancy = payload.get("occupancy", "occupied")
            minutes = payload.get("minutes", 30)
            expires = time.time() + (minutes * 60)

            self._room_overrides[room_id] = {
                "occupancy": occupancy,
                "expires": expires,
            }
            logger.info(
                "Room %s overridden to '%s' for %d min",
                room_id, occupancy, minutes,
            )
            self._mqtt.publish_event("room_override", {
                "room_id": room_id,
                "occupancy": occupancy,
                "minutes": minutes,
            })

        elif action == "clear_override":
            removed = self._room_overrides.pop(room_id, None)
            if removed:
                logger.info("Room %s override cleared", room_id)
                self._mqtt.publish_event("room_override_cleared", {"room_id": room_id})

    # ── System commands ───────────────────────────────────────

    async def _handle_system_cmd(self, action: str, payload: dict) -> None:
        """Handle system-level commands."""
        if action == "reload":
            if self._fusion:
                await self._fusion._pull_initial_states()
                logger.info("Fusion states reloaded from HA")
                self._mqtt.publish_event("system_reloaded", {})

    # ── Public accessors ──────────────────────────────────────

    def is_rule_disabled(self, rule_id: str) -> bool:
        """Check if a scenario rule is disabled via command."""
        return rule_id in self._disabled_rules

    def get_room_override(self, room_id: str) -> dict | None:
        """Get active room override, or None if expired/absent."""
        override = self._room_overrides.get(room_id)
        if override and override["expires"] > time.time():
            return override
        # Clean up expired
        self._room_overrides.pop(room_id, None)
        return None

    @property
    def disabled_rules(self) -> set[str]:
        return set(self._disabled_rules)

    @property
    def active_overrides(self) -> dict[str, dict]:
        """Return all non-expired overrides."""
        now = time.time()
        active = {}
        expired = []
        for room_id, ov in self._room_overrides.items():
            if ov["expires"] > now:
                active[room_id] = ov
            else:
                expired.append(room_id)
        for room_id in expired:
            self._room_overrides.pop(room_id)
        return active
