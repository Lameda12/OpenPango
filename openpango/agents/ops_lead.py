"""ops_lead: routes an order to the right specialists and returns one recommended action.

Policy (refund gates, no invented ETAs) lives in the tools, so even a wrong route here cannot bypass it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import policy
from ..context import Ctx
from . import carrier_chaser, exceptions, returns, support_writer

ACTION_FOR = {
    "stuck_customs": "carrier_inquiry",
    "late": "carrier_inquiry",
    "refused": "rts_followup",
    "delivered_dispute": "carrier_claim",
    "not_picked_up": "pickup_chase",
    "address_issue": "reissue_label",
    "wismo": "status_reply",
}
INBOUND_KINDS = ("wismo", "not_received", "address_update")


@dataclass
class Decision:
    order_number: str
    exception: str
    action: str
    approval: str = "none"            # none | pending | auto
    follow_up: str | None = None
    rationale: str = ""
    draft: dict | None = None
    calls: list = field(default_factory=list)


def _rationale(finding: exceptions.Finding, action: str) -> str:
    return f"{finding.type}: {finding.detail} -> {action}"


def handle(ctx: Ctx, number: str) -> Decision:
    start = len(ctx.trace)
    view = ctx.as_actor("ops_lead").tool("lookup_order", number=number)
    finding = exceptions.classify(view, ctx.now)
    order_id = view["order"]["id"]
    inbound = next((t for t in view["tickets"] if t["kind"] in INBOUND_KINDS and t["status"] == "open"), None)
    d = Decision(order_number=view["order"]["number"], exception=finding.type, action="no_action")
    situation, extras = finding.type, {}

    if finding.type == "none":
        d.rationale = "no exception found"
        return d

    if finding.type == "return_request":
        r = returns.run(ctx, view, finding)
        extras["amount_cents"] = r["amount_cents"]
        if r["outcome"] == "refund_issued":
            situation, d.action, d.approval = "refund_approved", "auto_refund", "auto"
        elif r["outcome"] == "pending_approval":
            situation, d.action, d.approval = "refund_pending", "escalate_for_approval", "pending"
        else:
            situation, d.action = "return_denied", "deny_return_escalate"
            extras["window_days"] = policy.RETURN_WINDOW_DAYS
            d.follow_up = r["ticket"]["due_at"]
    elif finding.type == "lost":
        chase = carrier_chaser.run(ctx, view, finding)
        r = returns.run(ctx, view, finding)
        d.action, d.approval = "escalate_for_approval", "pending"
        extras.update(amount_cents=r["amount_cents"], followup_date=chase["ticket"]["due_at"])
        d.follow_up = chase["ticket"]["due_at"]
    elif finding.type == "address_issue":
        chase = carrier_chaser.run(ctx, view, finding)
        d.action = ACTION_FOR["address_issue"]
        extras["previous_tracking"] = chase["label"]["previous_tracking"]
    elif finding.type == "wismo":
        d.action = ACTION_FOR["wismo"]
    else:
        chase = carrier_chaser.run(ctx, view, finding)
        d.action = ACTION_FOR[finding.type]
        d.follow_up = chase["ticket"]["due_at"]
        extras["followup_date"] = chase["ticket"]["due_at"]

    d.draft = support_writer.run(ctx, view, situation, extras, ticket_id=inbound["id"] if inbound else None)
    d.rationale = _rationale(finding, d.action)
    d.calls = [{"actor": c["actor"], "tool": c["tool"], "event_id": c["event_id"]} for c in ctx.trace[start:]]
    return d
