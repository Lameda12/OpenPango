"""carrier_chaser: opens carrier-facing cases and fixes address problems."""
from __future__ import annotations

import re

from .. import policy
from ..context import Ctx
from .exceptions import Finding

TICKET_FOR = {
    "stuck_customs": "carrier_inquiry",
    "late": "carrier_inquiry",
    "lost": "carrier_claim",
    "delivered_dispute": "carrier_claim",
    "not_picked_up": "pickup_chase",
    "refused": "rts_followup",
}
SUBJECT = {
    "carrier_inquiry": "Carrier inquiry: {carrier} {tn}",
    "carrier_claim": "Carrier claim: {carrier} {tn}",
    "pickup_chase": "Chase pickup: {carrier} {tn}",
    "rts_followup": "Track return-to-sender: {carrier} {tn}",
}


def run(ctx: Ctx, view: dict, finding: Finding) -> dict:
    """Returns {'ticket': dict|None, 'label': dict|None, 'rerate': dict|None}."""
    ctx = ctx.as_actor("carrier_chaser")
    ship, order = view["shipment"], view["order"]
    out: dict = {"ticket": None, "label": None, "rerate": None}

    if finding.type == "address_issue":
        # A real deployment would have the writer LLM extract this; the mock ticket body is structured.
        body = next((t["body"] for t in view["tickets"] if t["kind"] == "address_update" and t["status"] == "open"), "")
        m = re.search(r"Corrected address:\s*(.+)", body)
        if not m:
            raise ValueError("address_issue without a corrected address on file; needs a human")
        out["rerate"] = ctx.tool("rerate_shipment", shipment_id=ship["id"], address=m.group(1).strip())
        out["label"] = ctx.tool("issue_label", shipment_id=ship["id"], reason="address_correction")
        return out

    kind = TICKET_FOR[finding.type]
    existing = next((t for t in view["tickets"] if t["kind"] == kind and t["status"] == "open"), None)
    if existing:                      # do not double-file with the carrier
        out["ticket"] = {"ticket_id": existing["id"], "kind": kind, "due_at": existing["due_at"],
                         "carrier_ref": existing["carrier_ref"], "reused": True}
        return out
    out["ticket"] = ctx.tool(
        "open_ticket", order_id=order["id"], kind=kind,
        subject=SUBJECT[kind].format(carrier=ship["carrier"], tn=ship["tracking_number"]),
        body=f"{finding.type}: {finding.detail}")
    return out
