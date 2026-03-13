"""MQTT Auto Discovery for Home Assistant.

Publishes discovery configs so Hyggebo Brain sensors
automatically appear in Home Assistant.
"""
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mqtt_client import MQTTClient

logger = logging.getLogger("hyggebo_brain.discovery")

DISCOVERY_PREFIX = "homeassistant"

# Shared device definition — all sensors belong to this device
DEVICE_INFO = {
    "identifiers": ["hyggebo_brain"],
    "name": "Hyggebo Brain",
    "manufacturer": "Hyggebo",
    "model": "Brain v0.6",
    "sw_version": "0.6.0",
}

# Rooms that get occupancy sensors
DISCOVERY_ROOMS = [
    "alrum",
    "koekken",
    "gang",
    "badevaerelse",
    "udestue",
    "sovevaerelse",
    "darwins_vaerelse",
]


def publish_discovery(mqtt: "MQTTClient") -> None:
    """Publish all MQTT discovery configs to Home Assistant.

    Called once at startup. All messages are retained so HA
    picks them up even after restart.
    """
    _publish_room_occupancy_sensors(mqtt)
    _publish_house_state_sensor(mqtt)
    _publish_time_of_day_sensor(mqtt)
    _publish_system_sensor(mqtt)
    logger.info("MQTT discovery configs published for %d rooms + 3 system sensors",
                len(DISCOVERY_ROOMS))


def remove_discovery(mqtt: "MQTTClient") -> None:
    """Remove all discovery configs (publish empty retained messages)."""
    for room in DISCOVERY_ROOMS:
        topic = f"{DISCOVERY_PREFIX}/binary_sensor/hyggebo_brain/room_{room}/config"
        mqtt.publish(topic, "", retain=True)

    for sensor_id in ["hus_tilstand", "tid_pa_dagen", "system"]:
        topic = f"{DISCOVERY_PREFIX}/sensor/hyggebo_brain/{sensor_id}/config"
        mqtt.publish(topic, "", retain=True)

    logger.info("MQTT discovery configs removed")


# ── Room occupancy sensors (binary_sensor) ────────────────────

def _publish_room_occupancy_sensors(mqtt: "MQTTClient") -> None:
    """Publish binary_sensor discovery for each room."""
    for room in DISCOVERY_ROOMS:
        unique_id = f"hyggebo_brain_room_{room}"
        config = {
            "name": f"Brain {_room_display_name(room)} belægning",
            "unique_id": unique_id,
            "object_id": f"brain_{room}_occupancy",
            "state_topic": f"hyggebo_brain/sensor/room_{room}",
            "value_template": "{{ value_json.occupancy }}",
            "payload_on": "occupied",
            "payload_off": "clear",
            "device_class": "occupancy",
            "json_attributes_topic": f"hyggebo_brain/sensor/room_{room}",
            "json_attributes_template": "{{ value_json.attributes | tojson }}",
            "availability": {
                "topic": "hyggebo_brain/sensor/system",
                "value_template": "{{ value_json.state }}",
                "payload_available": "online",
                "payload_not_available": "offline",
            },
            "device": DEVICE_INFO,
        }
        topic = f"{DISCOVERY_PREFIX}/binary_sensor/hyggebo_brain/room_{room}/config"
        mqtt.publish(topic, json.dumps(config), retain=True)


# ── House state sensor ────────────────────────────────────────

def _publish_house_state_sensor(mqtt: "MQTTClient") -> None:
    """Publish sensor discovery for hus_tilstand."""
    config = {
        "name": "Brain Hus Tilstand",
        "unique_id": "hyggebo_brain_hus_tilstand",
        "object_id": "brain_hus_tilstand",
        "state_topic": "hyggebo_brain/sensor/hus_tilstand",
        "value_template": "{{ value_json.state }}",
        "json_attributes_topic": "hyggebo_brain/sensor/hus_tilstand",
        "json_attributes_template": "{{ value_json.attributes | tojson }}",
        "icon": "mdi:home-heart",
        "availability": {
            "topic": "hyggebo_brain/sensor/system",
            "value_template": "{{ value_json.state }}",
            "payload_available": "online",
            "payload_not_available": "offline",
        },
        "device": DEVICE_INFO,
    }
    topic = f"{DISCOVERY_PREFIX}/sensor/hyggebo_brain/hus_tilstand/config"
    mqtt.publish(topic, json.dumps(config), retain=True)


# ── Time-of-day sensor ───────────────────────────────────────

def _publish_time_of_day_sensor(mqtt: "MQTTClient") -> None:
    """Publish sensor discovery for tid_pa_dagen."""
    config = {
        "name": "Brain Tid på Dagen",
        "unique_id": "hyggebo_brain_tid_pa_dagen",
        "object_id": "brain_tid_pa_dagen",
        "state_topic": "hyggebo_brain/sensor/tid_pa_dagen",
        "value_template": "{{ value_json.state }}",
        "icon": "mdi:clock-outline",
        "availability": {
            "topic": "hyggebo_brain/sensor/system",
            "value_template": "{{ value_json.state }}",
            "payload_available": "online",
            "payload_not_available": "offline",
        },
        "device": DEVICE_INFO,
    }
    topic = f"{DISCOVERY_PREFIX}/sensor/hyggebo_brain/tid_pa_dagen/config"
    mqtt.publish(topic, json.dumps(config), retain=True)


# ── System sensor ─────────────────────────────────────────────

def _publish_system_sensor(mqtt: "MQTTClient") -> None:
    """Publish sensor discovery for system status."""
    config = {
        "name": "Brain System",
        "unique_id": "hyggebo_brain_system",
        "object_id": "brain_system",
        "state_topic": "hyggebo_brain/sensor/system",
        "value_template": "{{ value_json.state }}",
        "json_attributes_topic": "hyggebo_brain/sensor/system",
        "json_attributes_template": "{{ value_json.attributes | tojson }}",
        "icon": "mdi:brain",
        "device": DEVICE_INFO,
    }
    topic = f"{DISCOVERY_PREFIX}/sensor/hyggebo_brain/system/config"
    mqtt.publish(topic, json.dumps(config), retain=True)


# ── Helpers ───────────────────────────────────────────────────

def _room_display_name(room_id: str) -> str:
    """Convert room_id to Danish display name."""
    names = {
        "alrum": "Alrum",
        "koekken": "Køkken",
        "gang": "Gang",
        "badevaerelse": "Badeværelse",
        "udestue": "Udestue",
        "sovevaerelse": "Soveværelse",
        "darwins_vaerelse": "Darwins Værelse",
    }
    return names.get(room_id, room_id.replace("_", " ").title())
