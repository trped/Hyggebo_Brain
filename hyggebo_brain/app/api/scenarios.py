"""REST API endpoints for scenario engine."""
from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/scenarios")
async def list_scenarios(request: Request) -> list[dict[str, Any]]:
    """List all scenario rules with status."""
    engine = getattr(request.app.state, "scenario_engine", None)
    cmd = getattr(request.app.state, "cmd_handler", None)
    if not engine:
        raise HTTPException(503, "Scenario engine not running")

    rules = engine.get_rules_summary()
    # Enrich with disabled status from command handler
    if cmd:
        for rule in rules:
            rule["enabled"] = not cmd.is_rule_disabled(rule["id"])
    return rules


@router.post("/scenarios/{rule_id}/trigger")
async def trigger_scenario(request: Request, rule_id: str) -> dict:
    """Manually trigger a scenario rule (resets cooldown)."""
    engine = getattr(request.app.state, "scenario_engine", None)
    if not engine:
        raise HTTPException(503, "Scenario engine not running")

    # Check rule exists
    rule_ids = [r["id"] for r in engine.get_rules_summary()]
    if rule_id not in rule_ids:
        raise HTTPException(404, f"Rule '{rule_id}' not found")

    # Reset cooldown to allow immediate trigger
    engine._last_triggered.pop(rule_id, None)
    return {"status": "ok", "message": f"Cooldown reset for {rule_id}, will trigger on next eval cycle"}


@router.post("/scenarios/{rule_id}/enable")
async def enable_scenario(request: Request, rule_id: str) -> dict:
    """Enable a disabled scenario rule."""
    cmd = getattr(request.app.state, "cmd_handler", None)
    if not cmd:
        raise HTTPException(503, "Command handler not running")
    cmd._disabled_rules.discard(rule_id)
    return {"status": "ok", "rule_id": rule_id, "enabled": True}


@router.post("/scenarios/{rule_id}/disable")
async def disable_scenario(request: Request, rule_id: str) -> dict:
    """Disable a scenario rule."""
    cmd = getattr(request.app.state, "cmd_handler", None)
    if not cmd:
        raise HTTPException(503, "Command handler not running")
    cmd._disabled_rules.add(rule_id)
    return {"status": "ok", "rule_id": rule_id, "enabled": False}


@router.get("/overrides")
async def list_overrides(request: Request) -> dict:
    """List active room overrides."""
    cmd = getattr(request.app.state, "cmd_handler", None)
    if not cmd:
        return {"overrides": {}, "disabled_rules": []}
    return {
        "overrides": cmd.active_overrides,
        "disabled_rules": list(cmd.disabled_rules),
    }
