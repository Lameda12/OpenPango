"""Draft writers. The default is deterministic; ClaudeDrafter is opt-in and goes through the same guard."""
from __future__ import annotations

import json
import os
from typing import Protocol

from . import templates
from .facts import TrackingFacts


class Drafter(Protocol):
    def draft(self, template: str, order: dict, facts: TrackingFacts, extras: dict) -> tuple[str, str]: ...


class TemplateDrafter:
    def draft(self, template, order, facts, extras):
        return templates.render(template, order, facts, extras)


class ClaudeDrafter:
    """Rewrites the template draft in a warmer voice. Output is NOT trusted: tools.draft_customer_email
    runs guard.check on it and blocks the draft if it asserts anything the facts do not support."""

    SYSTEM = (
        "You write customer support emails for a small online store. Use ONLY the facts in the JSON. "
        "Never state or imply a delivery date, ETA, or timeframe unless 'carrier_eta' is present. "
        "Cite the tracking number and the latest carrier scan. Keep it under 120 words. Output the body only."
    )

    def __init__(self, client=None, model: str | None = None):
        if client is None:
            import anthropic  # optional dependency: pip install openpango[llm]
            client = anthropic.Anthropic()
        self.client = client
        self.model = model or os.environ.get("OPENPANGO_MODEL", "claude-sonnet-5-5")

    def draft(self, template, order, facts, extras):
        subject, base = templates.render(template, order, facts, extras)
        payload = {"facts": facts.__dict__, "extras": extras, "customer_first_name": order["customer_name"].split()[0],
                   "reference_draft": base}
        msg = self.client.messages.create(
            model=self.model, max_tokens=500, system=self.SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}],
        )
        return subject, "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
