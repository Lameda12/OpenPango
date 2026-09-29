"""returns agent: eligibility window, then refund (subject to approval gates) or human review."""
from __future__ import annotations

from .. import facts, policy
from ..context import Ctx
from .exceptions import Finding


def run(ctx: Ctx, view: dict, finding: Finding) -> dict:
    """Returns {'outcome': refund_issued|pending_approval|in_review|none, 'amount_cents', 'result'|'ticket'}."""
    ctx = ctx.as_actor("returns")
    order = view["order"]
    ret = next((r for r in view["returns"] if r["status"] == "requested"), None)
    lost = finding.type == "lost"
    if ret is None and not lost:
        return {"outcome": "none", "amount_cents": 0}
    amount = ret["amount_cents"] if ret else order["total_cents"]

    if not lost:
        f = facts.build(view, ctx.now)
        if f.delivered_days is not None and f.delivered_days > policy.RETURN_WINDOW_DAYS:
            ticket = ctx.tool("open_ticket", order_id=order["id"], kind="return_review",
                              subject=f"Return outside {policy.RETURN_WINDOW_DAYS}-day window",
                              body=f"delivered {f.delivered_days} days ago; requested {amount} cents")
            return {"outcome": "in_review", "amount_cents": amount, "ticket": ticket}

    result = ctx.tool("approve_refund", order_id=order["id"], amount_cents=amount,
                      reason_code="lost_package" if lost else (ret["reason"] if ret else "other"),
                      return_id=ret["id"] if ret else None)
    return {"outcome": result["status"], "amount_cents": amount, "result": result}
