"""ML engine for learning patterns and suggesting automation rules."""
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from activity_tracker import ActivityTracker
    from database import Database
    from rule_manager import RuleManager

logger = logging.getLogger(__name__)

# Minimum samples before ML considers a pattern reliable
MIN_SAMPLES = 10
# Minimum occupancy percentage to consider a pattern significant
MIN_OCCUPANCY_PCT = 60.0
# Score threshold for auto-suggesting a rule
SUGGESTION_THRESHOLD = 0.7


class MLEngine:
    """Learns from activity patterns and suggests automation rules."""

    def __init__(
        self,
        db: "Database",
        rule_manager: "RuleManager",
        activity_tracker: "ActivityTracker",
    ) -> None:
        self.db = db
        self.rule_manager = rule_manager
        self.activity_tracker = activity_tracker

    async def save_state(self, key: str, value: dict) -> None:
        """Persist ML state to database."""
        await self.db.execute(
            """
            INSERT INTO ml_state (key, value, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (key) DO UPDATE
            SET value = $2::jsonb, updated_at = now()
            """,
            key,
            json.dumps(value),
        )

    async def load_state(self, key: str) -> Optional[dict]:
        """Load ML state from database."""
        row = await self.db.fetchrow(
            "SELECT value FROM ml_state WHERE key = $1", key
        )
        return dict(row["value"]) if row else None

    async def analyze_patterns(self) -> list[dict]:
        """Analyze activity patterns and generate rule suggestions.

        Looks for strong occupancy patterns that could become automations:
        - Room consistently occupied at certain times → pre-heat/light
        - Room consistently empty at certain times → auto-off
        - Transition patterns between rooms → anticipatory actions
        """
        suggestions = []

        # Get all rooms
        rooms = await self.db.fetch("SELECT room_id, name_da FROM rooms")

        for room in rooms:
            room_id = room["room_id"]
            room_name = room["name_da"]
            patterns = await self.activity_tracker.get_patterns(room_id)

            if not patterns:
                continue

            # Find strong "always occupied" patterns
            occupied_slots = [
                p for p in patterns
                if p["occupancy_pct"] >= MIN_OCCUPANCY_PCT
                and p["sample_count"] >= MIN_SAMPLES
            ]

            # Find strong "always empty" patterns
            empty_slots = [
                p for p in patterns
                if p["occupancy_pct"] <= (100 - MIN_OCCUPANCY_PCT)
                and p["sample_count"] >= MIN_SAMPLES
            ]

            # Group consecutive occupied hours into blocks
            for block in self._group_consecutive(occupied_slots):
                score = self._calculate_score(block)
                if score >= SUGGESTION_THRESHOLD:
                    start_hour = block[0]["hour"]
                    end_hour = (block[-1]["hour"] + 1) % 24
                    dow = block[0]["day_of_week"]
                    day_name = _day_name_da(dow)

                    suggestions.append({
                        "type": "pre_activate",
                        "room_id": room_id,
                        "room_name": room_name,
                        "day_of_week": dow,
                        "start_hour": start_hour,
                        "end_hour": end_hour,
                        "score": score,
                        "name": f"Tænd {room_name} {day_name} kl. {start_hour}",
                        "description": (
                            f"{room_name} er typisk optaget {day_name} "
                            f"kl. {start_hour}-{end_hour} "
                            f"({score:.0%} sikkerhed)"
                        ),
                        "conditions": [
                            {"type": "time", "hour": start_hour, "day_of_week": dow},
                            {"type": "room_empty", "room_id": room_id},
                        ],
                        "actions": [
                            {"type": "notify", "message": f"{room_name} bruges snart"},
                        ],
                    })

            # Suggest auto-off for empty patterns
            for block in self._group_consecutive(empty_slots):
                score = self._calculate_score(block)
                if score >= SUGGESTION_THRESHOLD:
                    start_hour = block[0]["hour"]
                    end_hour = (block[-1]["hour"] + 1) % 24
                    dow = block[0]["day_of_week"]
                    day_name = _day_name_da(dow)

                    suggestions.append({
                        "type": "auto_off",
                        "room_id": room_id,
                        "room_name": room_name,
                        "day_of_week": dow,
                        "start_hour": start_hour,
                        "end_hour": end_hour,
                        "score": score,
                        "name": f"Sluk {room_name} {day_name} kl. {start_hour}",
                        "description": (
                            f"{room_name} er typisk tom {day_name} "
                            f"kl. {start_hour}-{end_hour} "
                            f"({score:.0%} sikkerhed)"
                        ),
                        "conditions": [
                            {"type": "time", "hour": start_hour, "day_of_week": dow},
                            {"type": "room_occupied", "room_id": room_id},
                        ],
                        "actions": [
                            {"type": "notify", "message": f"{room_name} er normalt tom nu"},
                        ],
                    })

        # Sort by score descending
        suggestions.sort(key=lambda s: s["score"], reverse=True)

        # Save analysis state
        await self.save_state("last_analysis", {
            "timestamp": datetime.now().isoformat(),
            "suggestion_count": len(suggestions),
        })

        return suggestions

    async def create_suggestion_rules(self) -> int:
        """Run analysis and create ML-suggested rules in DB.

        Returns number of new suggestions created.
        """
        suggestions = await self.analyze_patterns()
        created = 0

        # Check existing ML suggestions to avoid duplicates
        existing = await self.rule_manager.get_ml_suggestions()
        existing_names = {r["name"] for r in existing}

        for s in suggestions:
            if s["name"] in existing_names:
                continue

            await self.rule_manager.create_rule(
                name=s["name"],
                description=s["description"],
                conditions=s["conditions"],
                actions=s["actions"],
                cooldown=600,
                source="ml_suggested",
                ml_score=s["score"],
                enabled=False,  # User must approve
            )
            created += 1

        if created:
            logger.info("ML engine created %d new suggestions", created)

        return created

    def _group_consecutive(self, slots: list[dict]) -> list[list[dict]]:
        """Group pattern slots into consecutive hour blocks per day."""
        if not slots:
            return []

        by_day: dict[int, list[dict]] = {}
        for s in slots:
            by_day.setdefault(s["day_of_week"], []).append(s)

        groups = []
        for _dow, day_slots in by_day.items():
            day_slots.sort(key=lambda x: x["hour"])
            current = [day_slots[0]]
            for s in day_slots[1:]:
                if s["hour"] == current[-1]["hour"] + 1:
                    current.append(s)
                else:
                    groups.append(current)
                    current = [s]
            groups.append(current)

        return groups

    def _calculate_score(self, block: list[dict]) -> float:
        """Calculate confidence score for a pattern block."""
        if not block:
            return 0.0

        avg_pct = sum(p["occupancy_pct"] for p in block) / len(block)
        avg_samples = sum(p["sample_count"] for p in block) / len(block)

        # Score based on consistency and sample size
        pct_score = min(avg_pct / 100.0, 1.0)
        sample_score = min(avg_samples / 50.0, 1.0)  # Cap at 50 samples
        length_bonus = min(len(block) / 4.0, 1.0)  # Bonus for longer blocks

        return pct_score * 0.5 + sample_score * 0.3 + length_bonus * 0.2


def _day_name_da(dow: int) -> str:
    """Return Danish day name for day_of_week (0=Monday)."""
    names = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
    return names[dow] if 0 <= dow <= 6 else "ukendt"
