"""Generic (abstract) webhook handler.

Provides a single endpoint for any external system (VMs, monitoring,
custom CI, etc.) to send structured notifications to Pachca.
"""

from __future__ import annotations

import logging

from pachca_bot.models.messages import (
    GenericAlertMessage,
    GenericDeployMessage,
    StructuredMessage,
)
from pachca_bot.models.webhooks import GenericWebhookPayload

logger = logging.getLogger(__name__)


def handle_generic_event(payload: GenericWebhookPayload) -> StructuredMessage:
    """Build a structured message from a generic webhook payload.

    Uses ``event_type`` to pick the best template:
    - ``deploy`` → :class:`GenericDeployMessage`
    - everything else → :class:`GenericAlertMessage`
    """
    if payload.event_type == "deploy":
        return GenericDeployMessage(
            source=payload.source,
            environment=payload.environment or "unknown",
            version=payload.version or "unknown",
            status=payload.status or "started",  # type: ignore[arg-type]
            actor=payload.actor,
            url=payload.url,
            changelog=payload.changelog,
        ).to_structured()

    return GenericAlertMessage(
        source=payload.source,
        title=payload.title,
        severity=payload.severity,
        details=payload.details,
        fields=payload.fields,
        url=payload.url,
    ).to_structured()
