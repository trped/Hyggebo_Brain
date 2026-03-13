"""System observability API — DB stats, sensor sources, ML status, fusion details."""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/system/stats")
async def system_stats(request: Request):
    """Full system observability: DB usage, sensor sources, ML status, engine stats."""
    db = getattr(request.app.state, "db", None)
    fusion = getattr(request.app.state, "fusion", None)
    ha_state = getattr(request.app.state, "ha_state_tracker", None)
    scenario_engine = getattr(request.app.state, "scenario_engine", None)
    rule_manager = getattr(request.app.state, "rule_manager", None)
    activity_tracker = getattr(request.app.state, "activity_tracker", None)
    ml_engine = getattr(request.app.state, "ml_engine", None)

    result = {}

    # ── Database stats ──
    if db and db.is_connected:
        try:
            # Table sizes
            sizes = await db.fetch("""
                SELECT
                    relname AS table_name,
                    pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
                    pg_total_relation_size(c.oid) AS size_bytes,
                    reltuples::bigint AS estimated_rows
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND relname NOT LIKE 'pg_%'
                ORDER BY pg_total_relation_size(c.oid) DESC
            """)
            result["database"] = {
                "tables": [
                    {
                        "name": r["table_name"],
                        "size": r["total_size"],
                        "size_bytes": r["size_bytes"],
                        "estimated_rows": r["estimated_rows"],
                    }
                    for r in sizes
                ],
            }

            # Total DB size
            total = await db.fetchval(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            result["database"]["total_size"] = total

            # Partition count
            partitions = await db.fetch("""
                SELECT
                    parent.relname AS parent_table,
                    COUNT(*) AS partition_count
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                GROUP BY parent.relname
            """)
            result["database"]["partitions"] = {
                r["parent_table"]: r["partition_count"] for r in partitions
            }

            # Event counts by type (last 24h)
            event_counts = await db.fetch("""
                SELECT event_type, COUNT(*) AS count
                FROM events
                WHERE ts > now() - interval '24 hours'
                GROUP BY event_type
                ORDER BY count DESC
            """)
            result["database"]["events_24h"] = {
                r["event_type"]: r["count"] for r in event_counts
            }

            # Sensor data count (last 24h)
            sensor_count = await db.fetchval("""
                SELECT COUNT(*) FROM sensor_data
                WHERE ts > now() - interval '24 hours'
            """)
            result["database"]["sensor_readings_24h"] = sensor_count or 0

            # Automation rules count
            rule_counts = await db.fetch("""
                SELECT source, COUNT(*) AS count, SUM(trigger_count) AS total_triggers
                FROM automation_rules
                GROUP BY source
            """)
            result["database"]["rules_by_source"] = {
                r["source"]: {"count": r["count"], "total_triggers": r["total_triggers"] or 0}
                for r in rule_counts
            }

        except Exception as e:
            result["database"] = {"error": str(e)}

    # ── Sensor fusion details ──
    if fusion:
        rooms = fusion.get_all_states()
        persons = fusion.get_person_states()
        result["fusion"] = {
            "rooms": {
                room_id: {
                    "occupancy": state.get("occupancy", "unknown"),
                    "source": state.get("source", "unknown"),
                    "epl_main": state.get("epl_main", None),
                    "composite": state.get("composite", None),
                    "zones": state.get("zones", {}),
                    "assumed_present": state.get("assumed_present", None),
                    "target_counts": state.get("target_counts", {}),
                }
                for room_id, state in rooms.items()
            },
            "persons": persons,
            "ble_distances": {
                f"{p}@{r}": round(d, 2)
                for (p, r), d in fusion._ble_distances.items()
            },
        }

    # ── House state ──
    if ha_state:
        result["house_state"] = {
            "hus_tilstand": ha_state.hus_tilstand,
            "tid_pa_dagen": ha_state.tid_pa_dagen,
        }

    # ── Scenario engine stats ──
    if scenario_engine:
        result["scenario_engine"] = scenario_engine.get_stats()
        result["scenario_engine"]["rules"] = scenario_engine.get_rules_summary()

    # ── ML status ──
    if ml_engine:
        try:
            last_analysis = await ml_engine.load_state("last_analysis")
            result["ml"] = {
                "last_analysis": last_analysis,
            }
        except Exception:
            result["ml"] = {"last_analysis": None}

    if rule_manager:
        try:
            suggestions = await rule_manager.get_ml_suggestions()
            result["ml"] = result.get("ml", {})
            result["ml"]["pending_suggestions"] = len(suggestions)
        except Exception:
            pass

    # ── Activity patterns summary ──
    if activity_tracker and db and db.is_connected:
        try:
            pattern_count = await db.fetchval(
                "SELECT COUNT(*) FROM activity_patterns"
            )
            rooms_with_patterns = await db.fetchval(
                "SELECT COUNT(DISTINCT room_id) FROM activity_patterns WHERE sample_count > 0"
            )
            result["activity"] = {
                "total_patterns": pattern_count or 0,
                "rooms_with_data": rooms_with_patterns or 0,
            }
        except Exception:
            result["activity"] = {"total_patterns": 0, "rooms_with_data": 0}

    return result


@router.get("/system/connections")
async def system_connections(request: Request):
    """Live connection status for all external services."""
    db = getattr(request.app.state, "db", None)
    mqtt = getattr(request.app.state, "mqtt", None)
    ha = getattr(request.app.state, "ha", None)

    result = {}

    # Database
    if db:
        pool = db._pool
        result["database"] = {
            "connected": db.is_connected,
            "pool_size": pool.get_size() if pool else 0,
            "pool_free": pool.get_idle_size() if pool else 0,
            "pool_min": pool.get_min_size() if pool else 0,
            "pool_max": pool.get_max_size() if pool else 0,
        }

    # MQTT
    if mqtt:
        result["mqtt"] = {
            "connected": mqtt.connected,
            "host": mqtt._host if hasattr(mqtt, '_host') else "unknown",
            "port": mqtt._port if hasattr(mqtt, '_port') else 0,
        }

    # HA WebSocket
    if ha:
        result["ha_websocket"] = {
            "connected": ha.connected,
        }

    return result
