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
    rm = request.app.state.rule_manager
    return await rm.list_rules(source=source)


@router.get("/rules/{rule_id}")
async def get_rule(request: Request, rule_id: int):
    """Get a single rule."""
    rm = request.app.state.rule_manager
    rule = await rm.get_rule(rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    return rule


@router.post("/rules", status_code=201)
async def create_rule(request: Request, body: RuleCreate):
    """Create a new automation rule."""
    rm = request.app.state.rule_manager
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
    rm = request.app.state.rule_manager
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
    rm = request.app.state.rule_manager
    if not await rm.delete_rule(rule_id):
        raise HTTPException(404, "Rule not found")
    return {"ok": True}


@router.post("/rules/{rule_id}/toggle")
async def toggle_rule(request: Request, rule_id: int, enabled: bool = True):
    """Enable or disable a rule."""
    rm = request.app.state.rule_manager
    result = await rm.toggle_rule(rule_id, enabled)
    if not result:
        raise HTTPException(404, "Rule not found")
    return result


@router.get("/ml/suggestions")
async def ml_suggestions(request: Request):
    """Get ML-suggested rules (not yet approved)."""
    rm = request.app.state.rule_manager
    return await rm.get_ml_suggestions()


@router.post("/ml/suggestions/{rule_id}/approve")
async def approve_suggestion(request: Request, rule_id: int):
    """Approve an ML suggestion (enables it)."""
    rm = request.app.state.rule_manager
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
