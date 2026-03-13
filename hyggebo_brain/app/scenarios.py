"""Scenario detection engine — occupancy-based autonomous actions.

Evaluates rules based on:
  - Room occupancy (from SensorFusion)
  - House state: hus_tilstand (hjemme/nat/ude/kun_hunde/ferie)
  - Time of day: tid_pa_dagen (morgen/dag/aften/nat)

Rules are loaded from the database (automation_rules table).
On first startup, seeds 7 default rules if the table is empty.

When a scenario matches, triggers HA service calls via HAClient.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cmd_handler import CommandHandler
    from event_logger import EventLogger
    from fusion import SensorFusion
    from ha_client import HAClient
    from ha_state import HAStateTracker
    from mqtt_client import MQTTClient
    from notifications import NotificationService
    from rule_manager import RuleManager

logger = logging.getLogger("hyggebo_brain.scenarios")

# ── Default rules (seeded to DB on first run) ────────────────
DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "Alle ude — sluk lys",
        "description": "Slukker alt lys naar huset er tomt og alle er ude",
        "conditions": [
            {"type": "state", "value": "ude"},
            {"type": "all_rooms_clear"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_off",
             "data": {"entity_id": "all"}},
        ],
        "cooldown": 300,
    },
    {
        "name": "Nat — alrum tomt, sluk lys",
        "description": "Slukker alrum lys om natten naar rummet er tomt",
        "conditions": [
            {"type": "time_of_day", "value": "nat"},
            {"type": "room_empty", "room_id": "alrum"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_off",
             "data": {"entity_id": "light.alrum"}},
        ],
        "cooldown": 600,
    },
    {
        "name": "Nat — koekken tomt, sluk lys",
        "description": "Slukker koekken lys om natten naar rummet er tomt",
        "conditions": [
            {"type": "time_of_day", "value": "nat"},
            {"type": "room_empty", "room_id": "koekken"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_off",
             "data": {"entity_id": "light.kokken"}},
        ],
        "cooldown": 600,
    },
    {
        "name": "Ferie — energisparing",
        "description": "Slukker alt lys og saetter klima til eco ved ferie",
        "conditions": [
            {"type": "state", "value": "ferie"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_off",
             "data": {"entity_id": "all"}},
            {"type": "ha_service", "service": "climate.set_preset_mode",
             "data": {"preset_mode": "eco", "entity_id": "climate.sovevarelse"}},
        ],
        "cooldown": 3600,
    },
    {
        "name": "Kun hunde — gang natlys",
        "description": "Taender svagt lys i gangen naar kun hundene er hjemme",
        "conditions": [
            {"type": "state", "value": "kun_hunde"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_on",
             "data": {"brightness_pct": 10, "entity_id": "light.gang"}},
        ],
        "cooldown": 1800,
    },
    {
        "name": "Morgen — koekken belaegning, taend lys",
        "description": "Taender koekken lys om morgenen naar der er nogen",
        "conditions": [
            {"type": "time_of_day", "value": "morgen"},
            {"type": "room_occupied", "room_id": "koekken"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_on",
             "data": {"entity_id": "light.kokken"}},
        ],
        "cooldown": 600,
    },
    {
        "name": "Aften — udestue hyggelys",
        "description": "Taender hyggeligt lys i udestuen om aftenen",
        "conditions": [
            {"type": "time_of_day", "value": "aften"},
            {"type": "room_occupied", "room_id": "udestue"},
        ],
        "actions": [
            {"type": "ha_service", "service": "light.turn_on",
             "data": {"brightness_pct": 40, "color_temp_kelvin": 2700,
                      "entity_id": "light.udestue"}},
        ],
        "cooldown": 900,
    },
]


class ScenarioEngine:
    """Evaluates scenario rules from DB and triggers HA actions."""

    def __init__(
        self,
        fusion: "SensorFusion",
        ha_state: "HAStateTracker",
        ha: "HAClient",
        mqtt: "MQTTClient",
        event_logger: "EventLogger | None" = None,
        cmd_handler: "CommandHandler | None" = None,
        notifier: "NotificationService | None" = None,
        rule_manager: "RuleManager | None" = None,
    ) -> None:
        self._fusion = fusion
        self._ha_state = ha_state
        self._ha = ha
        self._mqtt = mqtt
        self._event_logger = event_logger
        self._cmd_handler = cmd_handler
        self._notifier = notifier
        self._rule_manager = rule_manager
        self._running = False
        self._eval_task: asyncio.Task | None = None
        self._last_triggered: dict[int, float] = {}
        self._cached_rules: list[dict] = []
        self._rules_loaded_at: float = 0
        self._eval_count: int = 0
        self._trigger_count: int = 0

    async def start(self) -> None:
        """Seed default rules if needed, load rules, start eval loop."""
        if self._rule_manager:
            await self._seed_defaults()
            await self._reload_rules()

        self._running = True
        self._eval_task = asyncio.create_task(self._eval_loop())
        logger.info(
            "Scenario engine started with %d rules from DB",
            len(self._cached_rules),
        )

    async def stop(self) -> None:
        self._running = False
        if self._eval_task and not self._eval_task.done():
            self._eval_task.cancel()
            try:
                await self._eval_task
            except asyncio.CancelledError:
                pass
        logger.info("Scenario engine stopped")

    async def _seed_defaults(self) -> None:
        """Seed default rules into DB if automation_rules is empty."""
        existing = await self._rule_manager.list_rules()
        if existing:
            return

        logger.info("Seeding %d default automation rules...", len(DEFAULT_RULES))
        for rule in DEFAULT_RULES:
            await self._rule_manager.create_rule(
                name=rule["name"],
                description=rule["description"],
                conditions=rule["conditions"],
                actions=rule["actions"],
                cooldown=rule["cooldown"],
                source="default",
            )
        logger.info("Default rules seeded")

    async def _reload_rules(self) -> None:
        if self._rule_manager:
            self._cached_rules = await self._rule_manager.get_active_rules()
            self._rules_loaded_at = datetime.now(timezone.utc).timestamp()

    async def _eval_loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc).timestamp()
                if now - self._rules_loaded_at > 60:
                    await self._reload_rules()
                await self._evaluate_all()
            except Exception:
                logger.exception("Scenario evaluation error")
            await asyncio.sleep(10)

    async def _evaluate_all(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        self._eval_count += 1

        ctx = {
            "rooms": self._fusion.get_all_states(),
            "persons": self._fusion.get_person_states(),
            "hus_tilstand": self._ha_state.hus_tilstand,
            "tid_pa_dagen": self._ha_state.tid_pa_dagen,
        }

        for rule in self._cached_rules:
            rule_id = rule["id"]
            cooldown = rule.get("cooldown", 300)

            last = self._last_triggered.get(rule_id, 0)
            if now - last < cooldown:
                continue

            if self._cmd_handler and self._cmd_handler.is_rule_disabled(str(rule_id)):
                continue

            if not self._evaluate_conditions(rule.get("conditions", []), ctx):
                continue

            logger.info("Rule triggered: #%d %s", rule_id, rule["name"])
            self._last_triggered[rule_id] = now
            self._trigger_count += 1

            for action in rule.get("actions", []):
                await self._execute_action(rule_id, rule["name"], action)

            if self._rule_manager:
                await self._rule_manager.record_trigger(rule_id)

            if self._notifier:
                await self._notifier.notify_scenario(str(rule_id), rule["name"])

            if self._event_logger:
                await self._event_logger.log_event(
                    event_type="scenario_triggered",
                    source="scenarios",
                    data={
                        "rule_id": rule_id,
                        "name": rule["name"],
                        "hus_tilstand": ctx["hus_tilstand"],
                        "tid_pa_dagen": ctx["tid_pa_dagen"],
                    },
                )

            self._mqtt.publish_event("scenario_triggered", {
                "rule_id": rule_id,
                "name": rule["name"],
            })

    def _evaluate_conditions(self, conditions: list, ctx: dict) -> bool:
        """Evaluate all conditions (AND logic)."""
        if not conditions:
            return False

        for cond in conditions:
            ctype = cond.get("type", "")

            if ctype == "state":
                if ctx["hus_tilstand"] != cond.get("value"):
                    return False
            elif ctype == "time_of_day":
                if ctx["tid_pa_dagen"] != cond.get("value"):
                    return False
            elif ctype == "time":
                if datetime.now().hour != cond.get("hour"):
                    return False
                if "day_of_week" in cond:
                    if datetime.now().weekday() != cond["day_of_week"]:
                        return False
            elif ctype == "room_occupied":
                room = ctx["rooms"].get(cond.get("room_id", ""), {})
                if room.get("occupancy") != "occupied":
                    return False
            elif ctype == "room_empty":
                room = ctx["rooms"].get(cond.get("room_id", ""), {})
                if room.get("occupancy") != "clear":
                    return False
            elif ctype == "all_rooms_clear":
                if any(r.get("occupancy") == "occupied"
                       for r in ctx["rooms"].values()):
                    return False
            elif ctype == "person_home":
                if ctx["persons"].get(cond.get("person_id", "")) != "home":
                    return False
            elif ctype == "person_away":
                if ctx["persons"].get(cond.get("person_id", "")) != "not_home":
                    return False
            else:
                return False

        return True

    async def _execute_action(self, rule_id: int, rule_name: str, action: dict) -> None:
        atype = action.get("type", "")

        if atype == "ha_service":
            service_str = action.get("service", "")
            data = dict(action.get("data", {}))

            if "." in service_str:
                domain, service = service_str.split(".", 1)
            else:
                logger.warning("Invalid service format: %s", service_str)
                return

            target = None
            if "entity_id" in data:
                target = {"entity_id": data.pop("entity_id")}

            try:
                await self._ha.call_service(domain, service, data=data or None, target=target)
                logger.info("Action: %s.%s (rule #%d)", domain, service, rule_id)
            except Exception:
                logger.exception("Action failed: %s.%s (rule #%d)", domain, service, rule_id)

        elif atype == "notify":
            if self._notifier:
                await self._notifier.notify_scenario(
                    str(rule_id), action.get("message", rule_name)
                )

        elif atype == "mqtt_publish":
            topic = action.get("topic", "")
            payload = action.get("payload", "")
            if topic:
                self._mqtt.publish_event(topic, {"payload": payload})

    # ── Public accessors ──────────────────────────────────────

    def get_rules_summary(self) -> list[dict]:
        return [
            {
                "id": rule["id"],
                "name": rule["name"],
                "cooldown": rule.get("cooldown", 300),
                "last_triggered": self._last_triggered.get(rule["id"]),
                "enabled": rule.get("enabled", True),
                "source": rule.get("source", "user"),
            }
            for rule in self._cached_rules
        ]

    def get_stats(self) -> dict:
        return {
            "eval_count": self._eval_count,
            "trigger_count": self._trigger_count,
            "cached_rules": len(self._cached_rules),
            "rules_loaded_at": self._rules_loaded_at,
        }
