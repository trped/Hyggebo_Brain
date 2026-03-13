"""REST API for automation rules CRUD and ML suggestions."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class RuleCreate(BaseModel):
    name: str
    description: str = ""
    conditions: list = []
    actions: list = []
    cooldown: int = 300
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list | None = None
    actions: list | None = None
    cooldown: int | None = None
    enabled: bool | None = None


@router.get("/rules")
async def list_rules(request: Request, source: str | None = None):
    """List all automation rules."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    return await rm.list_rules(source=source)


@router.get("/rules/{rule_id}")
async def get_rule(request: Request, rule_id: int):
    """Get a single rule."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    rule = await rm.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


@router.post("/rules", status_code=201)
async def create_rule(request: Request, body: RuleCreate):
    """Create a new automation rule."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    return await rm.create_rule(
        name=body.name,
        description=body.description,
        conditions=body.conditions,
        actions=body.actions,
        cooldown=body.cooldown,
        enabled=body.enabled,
        source="user",
    )


@router.put("/rules/{rule_id}")
async def update_rule(request: Request, rule_id: int, body: RuleUpdate):
    """Update an existing rule."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "No fields to update")
    result = await rm.update_rule(rule_id, **fields)
    if not result:
        raise HTTPException(404, "Rule not found")
    return result


@router.delete("/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: int):
    """Delete an automation rule."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    if not await rm.delete_rule(rule_id):
        raise HTTPException(404, "Rule not found")
    return {"ok": True}


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(request: Request, rule_id: int, enabled: bool = True):
    """Enable or disable a rule."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    result = await rm.toggle_rule(rule_id, enabled)
    if not result:
        raise HTTPException(404, "Rule not found")
    return result


@router.get("/ml/suggestions")
async def ml_suggestions(request: Request):
    """Get ML-suggested rules (not yet approved)."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    return await rm.get_ml_suggestions()


@router.post("/ml/suggestions/{rule_id}/approve")
async def approve_suggestion(request: Request, rule_id: int):
    """Approve an ML suggestion (enables it)."""
    rm = getattr(request.app.state, "rule_manager", None)
    if not rm:
        raise HTTPException(503, "Rule manager not available")
    rule = await rm.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, "Suggestion not found")
    if rule["source"] != "ml_suggested":
        raise HTTPException(400, "Not an ML suggestion")
    result = await rm.update_rule(rule_id, enabled=True, source="ml_approved")
    return result


@router.post("/ml/analyze")
async def run_analysis(request: Request):
    """Trigger ML analysis and generate new suggestions."""
    ml = getattr(request.app.state, "ml_engine", None)
    if not ml:
        raise HTTPException(503, "ML engine not available")
    count = await ml.create_suggestion_rules()
    return {"suggestions_created": count}


@router.get("/debug/rules")
async def debug_rules(request: Request):
    """Debug: test rules table directly."""
    db = getattr(request.app.state, "db", None)
    rm = getattr(request.app.state, "rule_manager", None)
    result = {
        "db_connected": bool(db and db.is_connected),
        "rule_manager_exists": rm is not None,
    }
    if db and db.is_connected:
        try:
            count = await db.fetchval("SELECT COUNT(*) FROM automation_rules")
            result["rules_count"] = count
            if count and count > 0:
                first = await db.fetchrow(
                    "SELECT id, name, source, enabled FROM automation_rules LIMIT 1"
                )
                result["first_rule"] = dict(first) if first else None
        except Exception as e:
            result["db_error"] = str(e)
    return result


@router.get("/patterns/{room_id}")
async def room_patterns(request: Request, room_id: str):
    """Get activity patterns for a room."""
    tracker = getattr(request.app.state, "activity_tracker", None)
    if not tracker:
        raise HTTPException(503, "Activity tracker not available")
    return await tracker.get_patterns(room_id)


@router.get("/patterns")
async def all_expected(request: Request):
    """Get current expected occupancy for all rooms."""
    tracker = getattr(request.app.state, "activity_tracker", None)
    if not tracker:
        raise HTTPException(503, "Activity tracker not available")
    return await tracker.get_all_expected()


@router.get("/learning/details")
async def learning_details(request: Request):
    """Full learning status — what the system has learned, from what data, how."""
    db = getattr(request.app.state, "db", None)
    tracker = getattr(request.app.state, "activity_tracker", None)
    ml = getattr(request.app.state, "ml_engine", None)
    rm = getattr(request.app.state, "rule_manager", None)

    result = {
        "how_it_works": {
            "data_source": "occupancy_change events fra sensor fusion (EPL mmWave, BLE, composite sensorer)",
            "aggregation": "Hvert 30. minut aggregeres events til moenstre per rum, ugedag og time",
            "learning_method": "Eksponentielt vaegtet gennemsnit (70% gammel vaerdi + 30% ny observation)",
            "ml_thresholds": {
                "min_samples": 10,
                "min_occupancy_pct": 60.0,
                "suggestion_threshold": 0.7,
                "description": "ML kraever mindst 10 datapunkter og >60% belaegsning foer den foreslaar en regel. Score >70% = forslag genereres."
            },
            "score_calculation": "Score = belaegningsprocent (50%) + antal datapunkter (30%) + sammenhaegende timer (20%)",
            "schedule": "Moenstre opdateres hvert 30. minut. ML analyse koerer hver 6. time.",
        },
        "rooms": {},
        "data_stats": {},
        "ml_status": {},
    }

    if not db or not db.is_connected:
        return result

    try:
        # Total occupancy events
        total_events = await db.fetchval(
            "SELECT COUNT(*) FROM events WHERE event_type = 'occupancy_change'"
        )
        events_24h = await db.fetchval(
            "SELECT COUNT(*) FROM events WHERE event_type = 'occupancy_change' AND ts > now() - interval '24 hours'"
        )
        events_7d = await db.fetchval(
            "SELECT COUNT(*) FROM events WHERE event_type = 'occupancy_change' AND ts > now() - interval '7 days'"
        )
        oldest_event = await db.fetchval(
            "SELECT MIN(ts) FROM events WHERE event_type = 'occupancy_change'"
        )
        newest_event = await db.fetchval(
            "SELECT MAX(ts) FROM events WHERE event_type = 'occupancy_change'"
        )

        result["data_stats"] = {
            "total_occupancy_events": total_events or 0,
            "events_last_24h": events_24h or 0,
            "events_last_7d": events_7d or 0,
            "oldest_event": oldest_event.isoformat() if oldest_event else None,
            "newest_event": newest_event.isoformat() if newest_event else None,
        }

        # Per-room details
        room_events = await db.fetch("""
            SELECT
                room_id,
                COUNT(*) AS total_events,
                COUNT(*) FILTER (WHERE data->>'occupancy' = 'occupied') AS occupied_events,
                COUNT(*) FILTER (WHERE data->>'occupancy' = 'clear') AS clear_events,
                MIN(ts) AS first_seen,
                MAX(ts) AS last_seen
            FROM events
            WHERE event_type = 'occupancy_change' AND room_id IS NOT NULL
            GROUP BY room_id
            ORDER BY total_events DESC
        """)

        # Per-room pattern stats
        pattern_stats = await db.fetch("""
            SELECT
                room_id,
                COUNT(*) AS pattern_slots,
                SUM(sample_count) AS total_samples,
                AVG(occupancy_pct) AS avg_occupancy,
                MAX(occupancy_pct) AS max_occupancy,
                MIN(occupancy_pct) AS min_occupancy,
                COUNT(*) FILTER (WHERE occupancy_pct >= 60) AS strong_occupied_slots,
                COUNT(*) FILTER (WHERE occupancy_pct <= 40) AS strong_empty_slots,
                MAX(updated_at) AS last_updated
            FROM activity_patterns
            GROUP BY room_id
            ORDER BY room_id
        """)
        pattern_map = {r["room_id"]: dict(r) for r in pattern_stats}

        # Room names
        room_names = await db.fetch("SELECT room_id, name_da FROM rooms")
        name_map = {r["room_id"]: r["name_da"] for r in room_names}

        for r in room_events:
            rid = r["room_id"]
            ps = pattern_map.get(rid, {})
            total = r["total_events"]
            occ = r["occupied_events"]

            room_data = {
                "name": name_map.get(rid, rid),
                "events": {
                    "total": total,
                    "occupied": occ,
                    "clear": r["clear_events"],
                    "occupied_pct": round(occ / total * 100, 1) if total > 0 else 0,
                    "first_seen": r["first_seen"].isoformat() if r["first_seen"] else None,
                    "last_seen": r["last_seen"].isoformat() if r["last_seen"] else None,
                },
                "patterns": {
                    "slots_learned": ps.get("pattern_slots", 0),
                    "total_slots": 168,  # 7 days x 24 hours
                    "coverage_pct": round(ps.get("pattern_slots", 0) / 168 * 100, 1),
                    "total_samples": ps.get("total_samples", 0),
                    "avg_occupancy": round(ps.get("avg_occupancy", 0) or 0, 1),
                    "max_occupancy": round(ps.get("max_occupancy", 0) or 0, 1),
                    "strong_occupied_slots": ps.get("strong_occupied_slots", 0),
                    "strong_empty_slots": ps.get("strong_empty_slots", 0),
                    "last_updated": ps["last_updated"].isoformat() if ps.get("last_updated") else None,
                },
            }

            # Get top patterns for this room (strongest signals)
            if tracker:
                patterns = await tracker.get_patterns(rid)
                top_occupied = sorted(
                    [p for p in patterns if p["occupancy_pct"] >= 50 and p["sample_count"] >= 3],
                    key=lambda x: x["occupancy_pct"],
                    reverse=True,
                )[:5]
                top_empty = sorted(
                    [p for p in patterns if p["occupancy_pct"] <= 30 and p["sample_count"] >= 3],
                    key=lambda x: x["occupancy_pct"],
                )[:5]

                DAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Loer", "Soen"]
                room_data["top_signals"] = {
                    "most_occupied": [
                        {
                            "day": DAYS[p["day_of_week"]],
                            "hour": p["hour"],
                            "occupancy_pct": round(p["occupancy_pct"], 1),
                            "samples": p["sample_count"],
                            "description": f"{DAYS[p['day_of_week']]} kl. {p['hour']}:00 — {p['occupancy_pct']:.0f}% optaget ({p['sample_count']} observationer)",
                        }
                        for p in top_occupied
                    ],
                    "most_empty": [
                        {
                            "day": DAYS[p["day_of_week"]],
                            "hour": p["hour"],
                            "occupancy_pct": round(p["occupancy_pct"], 1),
                            "samples": p["sample_count"],
                            "description": f"{DAYS[p['day_of_week']]} kl. {p['hour']}:00 — {p['occupancy_pct']:.0f}% optaget ({p['sample_count']} observationer)",
                        }
                        for p in top_empty
                    ],
                }

            result["rooms"][rid] = room_data

        # ML status
        if ml:
            last_analysis = await ml.load_state("last_analysis")
            result["ml_status"]["last_analysis"] = last_analysis

        if rm:
            suggestions = await rm.get_ml_suggestions()
            approved = await rm.list_rules(source="ml_approved")
            result["ml_status"]["pending_suggestions"] = len(suggestions)
            result["ml_status"]["approved_rules"] = len(approved)
            result["ml_status"]["suggestions"] = [
                {
                    "name": s["name"],
                    "description": s["description"],
                    "score": s.get("ml_score", 0),
                }
                for s in suggestions
            ]

    except Exception as e:
        result["error"] = str(e)

    return result
