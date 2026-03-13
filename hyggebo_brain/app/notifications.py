"""Notification system — send persistent_notification via HA.

Sends notifications when important scenarios trigger or system
events occur. Uses HA's persistent_notification service which
shows in the HA frontend sidebar.
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ha_client import HAClient

logger = logging.getLogger("hyggebo_brain.notifications")

# Which scenario rules should send notifications
NOTIFY_RULES = {
    "alle_ude_lys_fra": "Alle er ude — lys slukket",
    "ferie_mode": "Ferie-tilstand aktiveret — energisparing",
    "kun_hunde_gang_lys": "Kun hunde hjemme — natlys i gang tændt",
}

# System events that send notifications
NOTIFY_SYSTEM_EVENTS = {
    "system_started": "Hyggebo Brain er startet",
    "system_error": "Hyggebo Brain fejl",
}


class NotificationService:
    """Sends HA persistent notifications and mobile push."""

    def __init__(self, ha: "HAClient") -> None:
        self._ha = ha

    async def notify_scenario(self, rule_id: str, rule_name: str) -> None:
        """Send notification for a triggered scenario."""
        if rule_id not in NOTIFY_RULES:
            return

        message = NOTIFY_RULES[rule_id]
        now = datetime.now(timezone.utc).strftime("%H:%M")
        await self._send_persistent(
            title=f"Brain: {rule_name}",
            message=f"{message} (kl. {now})",
            notification_id=f"brain_scenario_{rule_id}",
        )

    async def notify_system(self, event: str, details: str = "") -> None:
        """Send notification for a system event."""
        title = NOTIFY_SYSTEM_EVENTS.get(event, f"Brain: {event}")
        message = details or title
        await self._send_persistent(
            title=f"Brain System",
            message=message,
            notification_id=f"brain_system_{event}",
        )

    async def notify_mobile(
        self,
        message: str,
        title: str = "Hyggebo Brain",
        target: str = "notify.mobile_app_troels",
    ) -> None:
        """Send push notification to mobile device."""
        try:
            # Extract domain and service from target (notify.mobile_app_troels)
            parts = target.split(".", 1)
            if len(parts) == 2:
                await self._ha.call_service(
                    domain=parts[0],
                    service=parts[1],
                    data={"title": title, "message": message},
                )
                logger.info("Mobile notification sent: %s", title)
        except Exception:
            logger.exception("Failed to send mobile notification")

    async def _send_persistent(
        self,
        title: str,
        message: str,
        notification_id: str,
    ) -> None:
        """Create a persistent notification in HA."""
        try:
            await self._ha.call_service(
                domain="persistent_notification",
                service="create",
                data={
                    "title": title,
                    "message": message,
                    "notification_id": notification_id,
                },
            )
            logger.debug("Persistent notification: %s", title)
        except Exception:
            logger.exception("Failed to send persistent notification")
