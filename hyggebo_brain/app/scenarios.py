"""Scenario detection engine — occupancy-based autonomous actions.

Evaluates rules based on:
  - Room occupancy (from SensorFusion)
  - House state: hus_tilstand (hjemme/nat/ude/kun_hunde/ferie)
  - Time of day: tid_pa_dagen (morgen/dag/aften/nat)

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

logger = logging.getLogger("hyggebo_brain.scenarios")

# ── Scenario rules ────────────────────────────────────────────
# Each rule: condition function → list of actions
# Actions are HA service calls: (domain, service, data, target)

SCENARIO_RULES: list[dict[str, Any]] = [
    # 1. Alle ude → sluk alt lys
    {
        "id": "alle_ude_lys_fra",
        "name": "Alle ude — sluk lys",
        "condition": lambda ctx: (
            ctx["hus_tilstand"] == "ude"
            and not any(
                r["occupancy"] == "occupied"
                for r in ctx["rooms"].values()
            )
        ),
        "actions": [
            {
                "domain": "light",
                "service": "turn_off",
                "target": {"entity_id": "all"},
            },
        ],
        "cooldown": 300,  # seconds between re-triggers
    },
    # 2. Nat + ingen i alrum → sluk alrum lys
    {
        "id": "nat_alrum_lys_fra",
        "name": "Nat — alrum tomt, sluk lys",
        "condition": lambda ctx: (
            ctx["tid_pa_dagen"] == "nat"
            and ctx["rooms"].get("alrum", {}).get("occupancy") == "clear"
        ),
        "actions": [
            {
                "domain": "light",
                "service": "turn_off",
                "target": {"entity_id": "light.alrum"},
            },
        ],
        "cooldown": 600,
    },
    # 3. Nat + ingen i køkken → sluk køkken lys
    {
        "id": "nat_koekken_lys_fra",
        "name": "Nat — køkken tomt, sluk lys",
        "condition": lambda ctx: (
            ctx["tid_pa_dagen"] == "nat"
            and ctx["rooms"].get("koekken", {}).get("occupancy") == "clear"
        ),
        "actions": [
            {
                "domain": "light",
                "service": "turn_off",
                "target": {"entity_id": "light.kokken"},
            },
        ],
        "cooldown": 600,
    },
    # 4. Ferie → sluk alt og sæt klimaanlæg til eco
    {
        "id": "ferie_mode",
        "name": "Ferie — energisparing",
        "condition": lambda ctx: ctx["hus_tilstand"] == "ferie",
        "actions": [
            {
                "domain": "light",
                "service": "turn_off",
                "target": {"entity_id": "all"},
            },
            {
                "domain": "climate",
                "service": "set_preset_mode",
                "data": {"preset_mode": "eco"},
                "target": {"entity_id": "climate.sovevarelse"},
            },
        ],
        "cooldown": 3600,
    },
    # 5. Kun hunde → lys i gang tændt (natlys)
    {
        "id": "kun_hunde_gang_lys",
        "name": "Kun hunde — gang natlys",
        "condition": lambda ctx: ctx["hus_tilstand"] == "kun_hunde",
        "actions": [
            {
                "domain": "light",
                "service": "turn_on",
                "data": {"brightness_pct": 10},
                "target": {"entity_id": "light.gang"},
            },
        ],
        "cooldown": 1800,
    },
    # 6. Morgen + nogen i køkken → tænd køkken lys
    {
        "id": "morgen_koekken_lys",
        "name": "Morgen — køkken belægning, tænd lys",
        "condition": lambda ctx: (
            ctx["tid_pa_dagen"] == "morgen"
            and ctx["rooms"].get("koekken", {}).get("occupancy") == "occupied"
        ),
        "actions": [
            {
                "domain": "light",
                "service": "turn_on",
                "target": {"entity_id": "light.kokken"},
            },
        ],
        "cooldown": 600,
    },
    # 7. Aften + nogen i udestue → tænd hyggelig belysning
    {
        "id": "aften_udestue_hygge",
        "name": "Aften — udestue hyggelys",
        "condition": lambda ctx: (
            ctx["tid_pa_dagen"] == "aften"
            and ctx["rooms"].get("udestue", {}).get("occupancy") == "occupied"
        ),
        "actions": [
            {
                "domain": "light",
                "service": "turn_on",
                "data": {"brightness_pct": 40, "color_temp_kelvin": 2700},
                "target": {"entity_id": "light.udestue"},
            },
        ],
        "cooldown": 900,
    },
]


class ScenarioEngine:
    """Evaluates scenario rules and triggers HA actions."""

    def __init__(
        self,
        fusion: "SensorFusion",
        ha_state: "HAStateTracker",
        ha: "HAClient",
        mqtt: "MQTTClient",
        event_logger: "EventLogger | None" = None,
        cmd_handler: "CommandHandler | None" = None,
        notifier: "NotificationService | None" = None,
    ) -> None:
        self._fusion = fusion
        self._ha_state = ha_state
        self._ha = ha
        self._mqtt = mqtt
        self._event_logger = event_logger
        self._cmd_handler = cmd_handler
        self._notifier = notifier
        self._running = False
        self._eval_task: asyncio.Task | None = None
        # Track cooldowns: rule_id → last trigger time
        self._last_triggered: dict[str, float] = {}

    async def start(self) -> None:
        """Start periodic scenario evaluation."""
        self._running = True
        self._eval_task = asyncio.create_task(self._eval_loop())
        logger.info(
            "Scenario engine started with %d rules", len(SCENARIO_RULES)
        )

    async def stop(self) -> None:
        """Stop scenario evaluation."""
        self._running = False
        if self._eval_task and not self._eval_task.done():
            self._eval_task.cancel()
            try:
                await self._eval_task
            except asyncio.CancelledError:
                pass
        logger.info("Scenario engine stopped")

    async def _eval_loop(self) -> None:
        """Evaluate all rules every 10 seconds."""
        while self._running:
            try:
                await self._evaluate_all()
            except Exception:
                logger.exception("Scenario evaluation error")
            await asyncio.sleep(10)

    async def _evaluate_all(self) -> None:
        """Build context and evaluate each rule."""
        now = datetime.now(timezone.utc).timestamp()

        ctx = {
            "rooms": self._fusion.get_all_states(),
            "persons": self._fusion.get_person_states(),
            "hus_tilstand": self._ha_state.hus_tilstand,
            "tid_pa_dagen": self._ha_state.tid_pa_dagen,
        }

        for rule in SCENARIO_RULES:
            rule_id = rule["id"]
            cooldown = rule.get("cooldown", 300)

            # Check cooldown
            last = self._last_triggered.get(rule_id, 0)
            if now - last < cooldown:
                continue

            # Evaluate condition
            try:
                if not rule["condition"](ctx):
                    continue
            except Exception:
                logger.exception("Error evaluating rule %s", rule_id)
                continue

            # Check if rule is disabled via command handler
            if self._cmd_handler and self._cmd_handler.is_rule_disabled(rule_id):
                continue

            # Condition matched — execute actions
            logger.info("Scenario triggered: %s (%s)", rule["name"], rule_id)
            self._last_triggered[rule_id] = now

            for action in rule["actions"]:
                await self._execute_action(rule_id, action)

            # Send notification
            if self._notifier:
                await self._notifier.notify_scenario(rule_id, rule["name"])

            # Log event
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

            # Publish to MQTT
            self._mqtt.publish_event("scenario_triggered", {
                "rule_id": rule_id,
                "name": rule["name"],
            })

    async def _execute_action(self, rule_id: str, action: dict) -> None:
        """Execute a single HA service call."""
        domain = action["domain"]
        service = action["service"]
        data = action.get("data")
        target = action.get("target")

        try:
            await self._ha.call_service(domain, service, data=data, target=target)
            logger.info(
                "Action executed: %s.%s (rule: %s)",
                domain, service, rule_id,
            )
        except Exception:
            logger.exception(
                "Action failed: %s.%s (rule: %s)",
                domain, service, rule_id,
            )

    # ── Public accessors ──────────────────────────────────────

    def get_rules_summary(self) -> list[dict]:
        """Return summary of all rules and their last trigger times."""
        return [
            {
                "id": rule["id"],
                "name": rule["name"],
                "cooldown": rule.get("cooldown", 300),
                "last_triggered": self._last_triggered.get(rule["id"]),
            }
            for rule in SCENARIO_RULES
        ]
