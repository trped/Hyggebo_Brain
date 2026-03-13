"""Sensor Fusion v1 – EPL + person + BLE per room.

Subscribes to HA state_changed events and combines:
  1. EPL mmWave occupancy (primary signal for 6/7 rooms)
  2. Person entities (home/not_home)
  3. BLE proximity (Bermuda integration)

Publishes fused room occupancy to MQTT so HA auto-discovery
picks it up via discovery.py topics.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_logger import EventLogger
    from ha_client import HAClient
    from mqtt_client import MQTTClient

logger = logging.getLogger("hyggebo_brain.fusion")

# ── Room mapping (mirrors HA entity landscape) ────────────────

ROOM_MAPPING: dict[str, dict[str, Any]] = {
    "alrum": {
        "epl_device": "epl_opholdsrum",
        "main_occupancy": "binary_sensor.epl_opholdsrum_occupancy",
        "zones": {
            "sofa": "binary_sensor.epl_zone_1_occupancy",
            "koekken": "binary_sensor.epl_opholdsrum_zone_2_occupancy",
            "gang": "binary_sensor.epl_opholdsrum_zone_3_occupancy",
        },
        "composite": "binary_sensor.alrum_presence",
    },
    "koekken": {
        "epl_device": "epl_kokken",
        "main_occupancy": "binary_sensor.epl_kokken_occupancy",
        "zones": {
            "koekken": "binary_sensor.epl_gang_zone_1_occupancy",
        },
        "composite": "binary_sensor.kokken_presence",
    },
    "gang": {
        "epl_device": "epl_gang",
        "main_occupancy": "binary_sensor.epl_gang_occupancy",
        "zones": {
            "gang": "binary_sensor.epl_gangen_zone_1_occupancy",
            "alrum": "binary_sensor.epl_gangen_zone_2_occupancy",
        },
        "composite": "binary_sensor.gang_presence",
    },
    "badevaerelse": {
        "epl_device": "epl_bad",
        "main_occupancy": "binary_sensor.epl_bad_occupancy",
        "zones": {
            "bad": "binary_sensor.epl_bad_zone_1_occupancy",
        },
        "composite": "binary_sensor.bad_presence",
    },
    "udestue": {
        "epl_device": "epl_udestuen",
        "main_occupancy": "binary_sensor.epl_udestuen_occupancy",
        "zones": {
            "sofa": "binary_sensor.epl_udestuen_zone_1_occupancy",
            "laenestol": "binary_sensor.epl_udestuen_zone_2_occupancy",
            "bord": "binary_sensor.epl_udestuen_zone_3_occupancy",
            "indgang": "binary_sensor.epl_udestuen_zone_4_occupancy",
        },
        "target_counts": {
            "sofa": "sensor.epl_udestuen_zone_1_target_count",
            "laenestol": "sensor.epl_udestuen_zone_2_target_count",
            "bord": "sensor.epl_udestuen_zone_3_target_count",
            "indgang": "sensor.epl_udestuen_zone_4_target_count",
        },
        "zone_priority": ["bord", "laenestol", "sofa", "indgang"],
    },
    "sovevaerelse": {
        "epl_device": None,  # NO EPL SENSOR
        "fallback_signals": [
            "climate.sovevarelse",
            "light.sovevarelse",
            "person.*",
        ],
    },
    "darwins_vaerelse": {
        "epl_device": "epl_darwin",
        "main_occupancy": "binary_sensor.epl_darwin_occupancy",
        "zones": {
            "seng": "binary_sensor.epl_darwin_zone_1_occupancy",
            "skrivebord": "binary_sensor.epl_darwin_zone_2_occupancy",
        },
        "assumed_present": "binary_sensor.epl_darwin_assumed_present",
    },
}

# Person entities tracked for BLE / home-status
PERSON_ENTITIES = [
    "person.troels",
    "person.hanne",
    "person.darwin",
    "person.maria",
]

# Build reverse lookup: entity_id → room_id
_ENTITY_TO_ROOM: dict[str, str] = {}


def _build_entity_index() -> None:
    """Build a reverse index mapping entity_ids to room_ids."""
    for room_id, cfg in ROOM_MAPPING.items():
        if cfg.get("main_occupancy"):
            _ENTITY_TO_ROOM[cfg["main_occupancy"]] = room_id
        for entity in cfg.get("zones", {}).values():
            _ENTITY_TO_ROOM[entity] = room_id
        if cfg.get("composite"):
            _ENTITY_TO_ROOM[cfg["composite"]] = room_id
        if cfg.get("assumed_present"):
            _ENTITY_TO_ROOM[cfg["assumed_present"]] = room_id
        for entity in cfg.get("target_counts", {}).values():
            _ENTITY_TO_ROOM[entity] = room_id
        for sig in cfg.get("fallback_signals", []):
            if not sig.endswith(".*"):
                _ENTITY_TO_ROOM[sig] = room_id


_build_entity_index()


class SensorFusion:
    """Fuses EPL mmWave, person, and BLE signals into room occupancy."""

    def __init__(
        self,
        ha: "HAClient",
        mqtt: "MQTTClient",
        event_logger: "EventLogger | None" = None,
    ) -> None:
        self._ha = ha
        self._mqtt = mqtt
        self._event_logger = event_logger
        # Per-room state cache
        self._room_states: dict[str, dict[str, Any]] = {
            room: {"occupancy": "clear", "source": "init", "zones": {}}
            for room in ROOM_MAPPING
        }
        self._person_states: dict[str, str] = {}  # person.x → home/not_home
        self._running = False

    async def start(self) -> None:
        """Subscribe to HA events and do initial state pull."""
        self._running = True

        # Pull initial states for all tracked entities
        await self._pull_initial_states()

        # Subscribe to state_changed events
        await self._ha.subscribe("state_changed", self._on_state_changed)

        logger.info(
            "Sensor fusion started – tracking %d entities across %d rooms",
            len(_ENTITY_TO_ROOM) + len(PERSON_ENTITIES),
            len(ROOM_MAPPING),
        )

    async def stop(self) -> None:
        """Stop fusion processing."""
        self._running = False
        logger.info("Sensor fusion stopped")

    # ── Initial state pull ───────────────────────────────────

    async def _pull_initial_states(self) -> None:
        """Fetch current states from HA for all tracked entities."""
        try:
            all_states = await self._ha.get_states()
            if not all_states:
                logger.warning("No states received from HA")
                return

            state_map = {s["entity_id"]: s for s in all_states}

            # Person states
            for person_id in PERSON_ENTITIES:
                if person_id in state_map:
                    self._person_states[person_id] = state_map[person_id]["state"]

            # Room entities
            for entity_id, room_id in _ENTITY_TO_ROOM.items():
                if entity_id in state_map:
                    self._process_entity_state(
                        entity_id, state_map[entity_id]["state"], room_id
                    )

            # Compute and publish all rooms
            for room_id in ROOM_MAPPING:
                self._compute_and_publish(room_id)

            logger.info("Initial state pull complete – %d states loaded",
                        len(state_map))
        except Exception as e:
            logger.error("Failed to pull initial states: %s", e)

    # ── Event handler ────────────────────────────────────────

    async def _on_state_changed(self, event_data: dict) -> None:
        """Handle HA state_changed events."""
        if not self._running:
            return

        entity_id = event_data.get("entity_id", "")
        new_state_obj = event_data.get("new_state")
        if not new_state_obj:
            return

        new_state = new_state_obj.get("state", "")

        # Person entity?
        if entity_id in PERSON_ENTITIES:
            old = self._person_states.get(entity_id)
            self._person_states[entity_id] = new_state
            if old != new_state:
                logger.debug("Person %s: %s → %s", entity_id, old, new_state)
                # Re-evaluate all rooms (person state affects sovevaerelse)
                for room_id in ROOM_MAPPING:
                    self._compute_and_publish(room_id)
            return

        # Room-related entity?
        room_id = _ENTITY_TO_ROOM.get(entity_id)
        if room_id:
            self._process_entity_state(entity_id, new_state, room_id)
            self._compute_and_publish(room_id)

    # ── State processing ─────────────────────────────────────

    def _process_entity_state(
        self, entity_id: str, state: str, room_id: str
    ) -> None:
        """Update internal room state cache from an entity state."""
        cfg = ROOM_MAPPING[room_id]
        room = self._room_states[room_id]

        # Main occupancy sensor
        if entity_id == cfg.get("main_occupancy"):
            room["epl_main"] = state == "on"

        # Zone occupancy
        for zone_name, zone_entity in cfg.get("zones", {}).items():
            if entity_id == zone_entity:
                room["zones"][zone_name] = state == "on"

        # Composite presence
        if entity_id == cfg.get("composite"):
            room["composite"] = state == "on"

        # Assumed present (darwins_vaerelse)
        if entity_id == cfg.get("assumed_present"):
            room["assumed_present"] = state == "on"

        # Target counts (udestue)
        for zone_name, count_entity in cfg.get("target_counts", {}).items():
            if entity_id == count_entity:
                try:
                    room.setdefault("target_counts", {})[zone_name] = int(state)
                except (ValueError, TypeError):
                    room.setdefault("target_counts", {})[zone_name] = 0

    # ── Fusion logic ─────────────────────────────────────────

    def _compute_and_publish(self, room_id: str) -> None:
        """Run fusion logic for a room and publish result via MQTT."""
        cfg = ROOM_MAPPING[room_id]
        room = self._room_states[room_id]

        # Special case: sovevaerelse (no EPL)
        if cfg.get("epl_device") is None:
            occupied, source, attrs = self._fuse_sovevaerelse(room_id)
        else:
            occupied, source, attrs = self._fuse_standard(room_id, cfg, room)

        # Update cache
        old_occupancy = room["occupancy"]
        room["occupancy"] = "occupied" if occupied else "clear"
        room["source"] = source

        # Publish via MQTT (always, so attributes stay fresh)
        payload = {
            "occupancy": room["occupancy"],
            "attributes": {
                "source": source,
                "zones": room.get("zones", {}),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                **attrs,
            },
        }
        self._mqtt.publish_sensor(f"room_{room_id}", room["occupancy"], payload["attributes"])

        if old_occupancy != room["occupancy"]:
            logger.info(
                "Room %s: %s → %s (source: %s)",
                room_id, old_occupancy, room["occupancy"], source,
            )
            # Persist to database
            if self._event_logger:
                import asyncio
                asyncio.create_task(
                    self._event_logger.log_occupancy_change(
                        room_id=room_id,
                        old_state=old_occupancy,
                        new_state=room["occupancy"],
                        source=source,
                        attrs=attrs,
                    )
                )

    def _fuse_standard(
        self, room_id: str, cfg: dict, room: dict
    ) -> tuple[bool, str, dict]:
        """Standard fusion: EPL main + zones + composite."""
        epl_main = room.get("epl_main", False)
        composite = room.get("composite", False)
        any_zone = any(room.get("zones", {}).values())
        assumed = room.get("assumed_present", False)

        # Priority: EPL main > composite > zones > assumed_present
        if epl_main:
            source = "epl_main"
            occupied = True
        elif composite:
            source = "composite"
            occupied = True
        elif any_zone:
            source = "epl_zone"
            occupied = True
        elif assumed:
            source = "assumed_present"
            occupied = True
        else:
            source = "none"
            occupied = False

        attrs: dict[str, Any] = {}

        # Udestue special: add zone priority + target counts
        if room_id == "udestue":
            zone_priority = cfg.get("zone_priority", [])
            active_zones = [
                z for z in zone_priority
                if room.get("zones", {}).get(z, False)
            ]
            attrs["active_zones"] = active_zones
            attrs["primary_zone"] = active_zones[0] if active_zones else None
            attrs["target_counts"] = room.get("target_counts", {})

        return occupied, source, attrs

    def _fuse_sovevaerelse(self, room_id: str) -> tuple[bool, str, dict]:
        """Sovevaerelse fusion: no EPL, use person + fallback signals."""
        room = self._room_states[room_id]

        # Check if any person is home
        anyone_home = any(
            s == "home" for s in self._person_states.values()
        )

        # Check fallback signals (climate/light state changes as proxy)
        # For v1, we rely on person state + composite if available
        composite = room.get("composite", False)

        if composite:
            return True, "composite", {}
        elif anyone_home:
            # Sovevaerelse is "possible" when someone is home,
            # but we mark it clear unless we have stronger signal
            return False, "person_home_no_signal", {"anyone_home": True}
        else:
            return False, "none", {"anyone_home": False}

    # ── Public accessors ─────────────────────────────────────

    def get_room_state(self, room_id: str) -> dict[str, Any] | None:
        """Get current fused state for a room."""
        return self._room_states.get(room_id)

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        """Get all room states."""
        return dict(self._room_states)

    def get_person_states(self) -> dict[str, str]:
        """Get current person states."""
        return dict(self._person_states)
