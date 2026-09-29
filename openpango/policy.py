"""Business rules in one place. Tools enforce these; agents cannot bypass them."""
from __future__ import annotations

REFUND_APPROVAL_CENTS = 7500   # refunds strictly above $75.00 need a human
RETURN_WINDOW_DAYS = 30
LOST_DAYS = 10                 # no carrier scan for this long while not delivered => lost
CUSTOMS_STUCK_DAYS = 3
PICKUP_DAYS = 3

CARRIER_TICKET_KINDS = {"carrier_inquiry", "carrier_claim", "pickup_chase", "rts_followup"}
FOLLOWUP_DAYS = {
    "carrier_inquiry": 2,
    "carrier_claim": 5,
    "pickup_chase": 1,
    "rts_followup": 3,
    "return_review": 2,
}

# Which tools each actor may call. Ctx.tool() enforces this.
AGENT_TOOLS: dict[str, frozenset[str]] = {
    "ops_lead": frozenset({"lookup_order"}),
    "exceptions": frozenset({"lookup_order"}),
    "carrier_chaser": frozenset({"open_ticket", "rerate_shipment", "issue_label"}),
    "returns": frozenset({"approve_refund", "open_ticket"}),
    "support_writer": frozenset({"draft_customer_email"}),
    "human": frozenset({"lookup_order", "decide_approval", "send_draft"}),
}


def approval_gate(amount_cents: int, reason_code: str) -> str | None:
    """Return why a refund needs human approval, or None if it can auto-issue."""
    if reason_code == "lost_package":
        return "lost_package"
    if amount_cents > REFUND_APPROVAL_CENTS:
        return "over_threshold"
    return None
