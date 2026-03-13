"""CRUD manager for database-driven automation rules."""
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)


class RuleManager:
    """Manages automation rules stored in PostgreSQL."""

    def __init__(self, db: "Database") -> None:
        self.db = db

    async def list_rules(
        self, enabled_only: bool = False, source: Optional[str] = None
    ) -> list[dict]:
        """List all automation rules, optionally filtered."""
        conditions = []
        args = []
        idx = 1

        if enabled_only:
            conditions.append(f"enabled = ${idx}")
            args.append(True)
            idx += 1
        if source:
            conditions.append(f"source = ${idx}")
            args.append(source)
            idx += 1

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = await self.db.fetch(
            f"SELECT * FROM automation_rules{where} ORDER BY created_at DESC", *args
        )
        return [dict(r) for r in rows]

    async def get_rule(self, rule_id: int) -> Optional[dict]:
        """Get a single rule by ID."""
        row = await self.db.fetchrow(
            "SELECT * FROM automation_rules WHERE id = $1", rule_id
        )
        return dict(row) if row else None

    async def create_rule(
        self,
        name: str,
        conditions: list,
        actions: list,
        description: str = "",
        cooldown: int = 300,
        source: str = "user",
        ml_score: float = 0.0,
        enabled: bool = True,
    ) -> dict:
        """Create a new automation rule."""
        import json

        row = await self.db.fetchrow(
            """
            INSERT INTO automation_rules
                (name, description, enabled, conditions, actions, cooldown, ml_score, source)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8)
            RETURNING *
            """,
            name,
            description,
            enabled,
            json.dumps(conditions),
            json.dumps(actions),
            cooldown,
            ml_score,
            source,
        )
        logger.info("Created rule #%d: %s (source=%s)", row["id"], name, source)
        return dict(row)

    async def update_rule(self, rule_id: int, **fields) -> Optional[dict]:
        """Update specific fields of a rule."""
        import json

        allowed = {
            "name", "description", "enabled", "conditions", "actions",
            "cooldown", "ml_score", "source",
        }
        updates = []
        args = []
        idx = 1

        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in ("conditions", "actions"):
                updates.append(f"{key} = ${idx}::jsonb")
                args.append(json.dumps(value))
            else:
                updates.append(f"{key} = ${idx}")
                args.append(value)
            idx += 1

        if not updates:
            return await self.get_rule(rule_id)

        updates.append(f"updated_at = ${idx}")
        args.append(datetime.now())
        idx += 1

        args.append(rule_id)
        set_clause = ", ".join(updates)

        row = await self.db.fetchrow(
            f"UPDATE automation_rules SET {set_clause} WHERE id = ${idx} RETURNING *",
            *args,
        )
        if row:
            logger.info("Updated rule #%d", rule_id)
        return dict(row) if row else None

    async def delete_rule(self, rule_id: int) -> bool:
        """Delete a rule by ID."""
        result = await self.db.execute(
            "DELETE FROM automation_rules WHERE id = $1", rule_id
        )
        deleted = result == "DELETE 1"
        if deleted:
            logger.info("Deleted rule #%d", rule_id)
        return deleted

    async def toggle_rule(self, rule_id: int, enabled: bool) -> Optional[dict]:
        """Enable or disable a rule."""
        return await self.update_rule(rule_id, enabled=enabled)

    async def record_trigger(self, rule_id: int) -> None:
        """Increment trigger count and update last_triggered."""
        await self.db.execute(
            """
            UPDATE automation_rules
            SET trigger_count = trigger_count + 1,
                last_triggered = now()
            WHERE id = $1
            """,
            rule_id,
        )

    async def get_active_rules(self) -> list[dict]:
        """Get all enabled rules for evaluation."""
        return await self.list_rules(enabled_only=True)

    async def get_ml_suggestions(self) -> list[dict]:
        """Get ML-suggested rules that haven't been approved yet."""
        rows = await self.db.fetch(
            """
            SELECT * FROM automation_rules
            WHERE source = 'ml_suggested' AND enabled = FALSE
            ORDER BY ml_score DESC
            """
        )
        return [dict(r) for r in rows]
