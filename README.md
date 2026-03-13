# Hyggebo Brain

Smart home intelligence engine for Home Assistant. Combines EPL mmWave occupancy sensors, BLE proximity (Bermuda), person entities, and climate/light signals into fused room occupancy — then triggers autonomous actions based on configurable scenario rules.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Home Assistant                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ EPL mmWave│  │ Bermuda  │  │ Person   │  ...sensors  │
│  │ Sensors   │  │ BLE Prox │  │ Entities │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       │              │              │                    │
│       └──────────────┼──────────────┘                    │
│                      │ WebSocket API                     │
└──────────────────────┼───────────────────────────────────┘
                       │
┌──────────────────────┼───────────────────────────────────┐
│              Hyggebo Brain (addon)                        │
│                      │                                    │
│  ┌───────────────────▼────────────────────┐              │
│  │           Sensor Fusion                 │              │
│  │  EPL main > composite > BLE > zones    │              │
│  │  Per-room occupancy with source attrs   │              │
│  └───────────────────┬────────────────────┘              │
│                      │                                    │
│  ┌───────────────────▼────────────────────┐              │
│  │         Scenario Engine                 │              │
│  │  7 rules: lys, klima, ferie, hunde     │              │
│  │  Cooldown management + notifications    │              │
│  └───────────────────┬────────────────────┘              │
│                      │                                    │
│  ┌──────────┐ ┌──────▼──────┐ ┌───────────────┐         │
│  │ REST API │ │ MQTT Publish│ │ HA Service     │         │
│  │ :8100    │ │ EMQX        │ │ Calls          │         │
│  └──────────┘ └─────────────┘ └───────────────┘         │
│                      │                                    │
│  ┌───────────────────▼────────────────────┐              │
│  │         PostgreSQL                      │              │
│  │  sensor_data (monthly partitions)       │              │
│  │  events (weekly partitions)             │              │
│  └────────────────────────────────────────┘              │
└──────────────────────────────────────────────────────────┘
```

## Components

| Module | Description |
|--------|-------------|
| `fusion.py` | Sensor fusion — EPL mmWave + BLE proximity + composite presence per room |
| `scenarios.py` | Rule-based scenario engine with cooldowns and HA service calls |
| `ha_state.py` | Tracks `hus_tilstand` and `tid_pa_dagen` from HA input_selects |
| `ha_client.py` | Async Home Assistant WebSocket API client |
| `mqtt_client.py` | EMQX MQTT client with auto-discovery publishing |
| `cmd_handler.py` | MQTT command handler for overrides and remote control |
| `notifications.py` | HA persistent notifications + mobile push |
| `event_logger.py` | Persists occupancy changes and events to PostgreSQL |
| `scheduler.py` | Background partition creation and cleanup |
| `discovery.py` | MQTT auto-discovery configs for HA integration |
| `database.py` | asyncpg connection pool manager |

## Rooms

| Room ID | Name | EPL Sensor | BLE |
|---------|------|-----------|-----|
| `alrum` | Alrum (Living Room) | epl_opholdsrum | Troels, Hanne |
| `koekken` | Køkken (Kitchen) | epl_kokken | Troels, Hanne |
| `gang` | Gang (Hallway) | epl_gang | — |
| `badevaerelse` | Badeværelse (Bathroom) | epl_bad | — |
| `udestue` | Udestue (Conservatory) | epl_udestuen | — |
| `sovevaerelse` | Soveværelse (Bedroom) | — (BLE only) | Troels, Hanne |
| `darwins_vaerelse` | Darwins Værelse | epl_darwin | — |

## Fusion Priority

```
EPL main > composite > BLE proximity > EPL zones > assumed_present
```

Room overrides (via MQTT cmd) take highest priority.

## Scenario Rules

| ID | Trigger | Action |
|----|---------|--------|
| `alle_ude_lys_fra` | hus_tilstand=ude + ingen belægning | Sluk alt lys |
| `nat_alrum_lys_fra` | Nat + alrum tomt | Sluk alrum lys |
| `nat_koekken_lys_fra` | Nat + køkken tomt | Sluk køkken lys |
| `ferie_mode` | hus_tilstand=ferie | Sluk lys + klima eco |
| `kun_hunde_gang_lys` | hus_tilstand=kun_hunde | Gang natlys 10% |
| `morgen_koekken_lys` | Morgen + køkken belægning | Tænd køkken lys |
| `aften_udestue_hygge` | Aften + udestue belægning | Hyggelys 40% 2700K |

## REST API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Live health check with component status |
| `/api/rooms` | GET | All rooms with current occupancy |
| `/api/rooms/{id}` | GET | Single room details |
| `/api/rooms/{id}/history` | GET | Sensor data history (default 24h) |
| `/api/persons` | GET | Person home/not_home states |
| `/api/state` | GET | hus_tilstand + tid_pa_dagen |
| `/api/events` | GET | Event log with filters |
| `/api/scenarios` | GET | All scenario rules with status |
| `/api/scenarios/{id}/trigger` | POST | Force-trigger a rule |
| `/api/scenarios/{id}/enable` | POST | Enable a rule |
| `/api/scenarios/{id}/disable` | POST | Disable a rule |
| `/api/overrides` | GET | Active room overrides |

## MQTT Commands

Publish JSON to `hyggebo_brain/cmd/<category>/<action>`:

```json
// Disable a scenario rule
// Topic: hyggebo_brain/cmd/scenario/disable
{"rule_id": "alle_ude_lys_fra"}

// Override room occupancy for 30 minutes
// Topic: hyggebo_brain/cmd/room/override
{"room_id": "sovevaerelse", "occupancy": "occupied", "minutes": 30}

// Clear room override
// Topic: hyggebo_brain/cmd/room/clear_override
{"room_id": "sovevaerelse"}

// Reload fusion states from HA
// Topic: hyggebo_brain/cmd/system/reload
{}
```

## Database

- **sensor_data** — Monthly partitioned, BRIN indexed, 90-day retention
- **events** — Weekly partitioned, BRIN indexed, 365-day retention
- **rooms** — 7 room definitions with Danish/English names
- **entity_map** — Entity → room mapping

Partition maintenance runs every 6 hours automatically.

## Setup

1. Add repository to Home Assistant
2. Install Hyggebo Brain addon
3. Configure MQTT and PostgreSQL connection in addon settings
4. Start the addon — auto-discovery creates HA entities

## Tech Stack

- Python 3.13 / FastAPI / Uvicorn
- PostgreSQL (asyncpg) with declarative partitioning
- EMQX MQTT (Paho)
- Home Assistant WebSocket + REST API
- Docker (Alpine Linux, aarch64 + amd64)
