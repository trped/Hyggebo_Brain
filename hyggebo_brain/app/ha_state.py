"""Read hus_tilstand and tid_pa_dagen from Home Assistant.

Subscribes to state changes for input_select.hus_tilstand and
input_select.tid_pa_dagen, publishing the current values over MQTT
so Home Assistant auto-discovers them as Hyggebo Brain sensors.
"""
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ha_client import HAClient
    from mqtt_client import MQTTClient

logger = logging.getLogger("hyggebo_brain.ha_state")

# HA entity IDs we track
HUS_TILSTAND_ENTITY = "input_select.hus_tilstand"
TID_PA_DAGEN_ENTITY = "input_select.tid_pa_dagen"

# Valid states for validation
VALID_HUS_TILSTAND = {"hjemme", "nat", "ude", "kun_hunde", "ferie"}
VALID_TID_PA_DAGEN = {"morgen", "dag", "aften", "nat"}


class HAStateTracker:
    """Track hus_tilstand and tid_pa_dagen from Home Assistant.

    Subscribes to HA state_changed events and publishes the values
    to MQTT topics that match discovery.py declarations:
      - hyggebo_brain/sensor/hus_tilstand/state
      - hyggebo_brain/sensor/tid_pa_dagen/state
    """

    def __init__(self, ha: "HAClient", mqtt: "MQTTClient") -> None:
        self._ha = ha
        self._mqtt = mqtt

        # Current tracked values
        self._hus_tilstand: str = "unknown"
        self._tid_pa_dagen: str = "unknown"

        # Attributes for hus_tilstand
        self._hus_attributes: dict[str, Any] = {}

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Subscribe to HA events and pull initial states."""
        await self._ha.subscribe("state_changed", self._on_state_changed)
        await self._pull_initial_states()
        logger.info(
            "HAStateTracker started: hus_tilstand=%s, tid_pa_dagen=%s",
            self._hus_tilstand,
            self._tid_pa_dagen,
        )

    async def stop(self) -> None:
        """Clean up (HA unsubscribe handled by ha_client.close)."""
        logger.info("HAStateTracker stopped")

    # ── Initial state pull ───────────────────────────────────────

    async def _pull_initial_states(self) -> None:
        """Fetch current hus_tilstand and tid_pa_dagen from HA."""
        try:
            hus_state = await self._ha.get_state(HUS_TILSTAND_ENTITY)
            if hus_state:
                self._update_hus_tilstand(hus_state)
            else:
                logger.warning("Could not fetch initial hus_tilstand")

            tid_state = await self._ha.get_state(TID_PA_DAGEN_ENTITY)
            if tid_state:
                self._update_tid_pa_dagen(tid_state)
            else:
                logger.warning("Could not fetch initial tid_pa_dagen")

        except Exception:
            logger.exception("Failed to pull initial HA states")

    # ── Event handling ───────────────────────────────────────────

    async def _on_state_changed(self, event_data: dict) -> None:
        """Handle state_changed events from HA WebSocket."""
        entity_id = event_data.get("entity_id", "")

        if entity_id == HUS_TILSTAND_ENTITY:
            new_state = event_data.get("new_state")
            if new_state:
                self._update_hus_tilstand(new_state)

        elif entity_id == TID_PA_DAGEN_ENTITY:
            new_state = event_data.get("new_state")
            if new_state:
                self._update_tid_pa_dagen(new_state)

    # ── State updates ────────────────────────────────────────────

    def _update_hus_tilstand(self, state_obj: dict) -> None:
        """Update hus_tilstand from HA state object and publish."""
        new_value = state_obj.get("state", "unknown")
        attributes = state_obj.get("attributes", {})

        if new_value not in VALID_HUS_TILSTAND:
            logger.warning(
                "Unexpected hus_tilstand value: %s (valid: %s)",
                new_value,
                VALID_HUS_TILSTAND,
            )

        old_value = self._hus_tilstand
        self._hus_tilstand = new_value

        # Build attributes to publish
        self._hus_attributes = {
            "options": attributes.get("options", []),
            "friendly_name": attributes.get("friendly_name", "Hus Tilstand"),
            "previous_state": old_value,
        }

        self._publish_hus_tilstand()

        if old_value != new_value:
            logger.info(
                "hus_tilstand changed: %s → %s", old_value, new_value
            )

    def _update_tid_pa_dagen(self, state_obj: dict) -> None:
        """Update tid_pa_dagen from HA state object and publish."""
        new_value = state_obj.get("state", "unknown")

        if new_value not in VALID_TID_PA_DAGEN:
            logger.warning(
                "Unexpected tid_pa_dagen value: %s (valid: %s)",
                new_value,
                VALID_TID_PA_DAGEN,
            )

        old_value = self._tid_pa_dagen
        self._tid_pa_dagen = new_value

        self._publish_tid_pa_dagen()

        if old_value != new_value:
            logger.info(
                "tid_pa_dagen changed: %s → %s", old_value, new_value
            )

    # ── MQTT publishing ──────────────────────────────────────────

    def _publish_hus_tilstand(self) -> None:
        """Publish hus_tilstand to MQTT (matches discovery.py topic)."""
        self._mqtt.publish_sensor(
            "hus_tilstand",
            self._hus_tilstand,
            self._hus_attributes,
        )

    def _publish_tid_pa_dagen(self) -> None:
        """Publish tid_pa_dagen to MQTT (matches discovery.py topic)."""
        self._mqtt.publish_sensor(
            "tid_pa_dagen",
            self._tid_pa_dagen,
        )

    # ── Public accessors ─────────────────────────────────────────

    @property
    def hus_tilstand(self) -> str:
        """Current hus_tilstand value."""
        return self._hus_tilstand

    @property
    def tid_pa_dagen(self) -> str:
        """Current tid_pa_dagen value."""
        return self._tid_pa_dagen

    def get_state_summary(self) -> dict:
        """Return summary of tracked HA states."""
        return {
            "hus_tilstand": self._hus_tilstand,
            "tid_pa_dagen": self._tid_pa_dagen,
            "hus_attributes": self._hus_attributes,
        }
