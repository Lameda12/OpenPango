"""exceptions agent: read-only triage. Turns an order view into a typed Finding with an age in days."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import facts, policy
from ..clock import days_between


@dataclass(frozen=True)
class Finding:
    type: str        # stuck_customs | late | refused | lost | address_issue | delivered_dispute
                     # | not_picked_up | return_request | wismo | none
    age_days: int
    detail: str = ""


def _open(view: dict, kind: str) -> dict | None:
    return next((t for t in view["tickets"] if t["kind"] == kind and t["status"] == "open"), None)


def classify(view: dict, now: datetime) -> Finding:
    f = facts.build(view, now)
    returns = [r for r in view["returns"] if r["status"] == "requested"]

    if f.status == "delivered":
        if t := _open(view, "not_received"):
            return Finding("delivered_dispute", days_between(t["opened_at"], now), "customer reports not received")
        if returns and returns[0]["reason"] != "not_received":
            return Finding("return_request", days_between(returns[0]["requested_at"], now), returns[0]["reason"])
        return Finding("none", 0)
    if f.refused_ts and f.status in ("refused", "returning"):
        return Finding("refused", days_between(f.refused_ts, now), "delivery refused")
    if f.status == "address_issue":
        return Finding("address_issue", days_between(f.address_issue_ts, now), f.last_desc or "")
    if f.status != "no_data" and f.days_since_scan >= policy.LOST_DAYS:
        return Finding("lost", f.days_since_scan, f"no scan for {f.days_since_scan} days")
    if f.status == "customs" and (f.customs_days or 0) >= policy.CUSTOMS_STUCK_DAYS:
        return Finding("stuck_customs", f.customs_days or 0, f"in customs {f.customs_days} days")
    if f.status == "label_created" and f.days_since_scan >= policy.PICKUP_DAYS:
        return Finding("not_picked_up", f.days_since_scan, "label created, never scanned")
    if facts.eta_passed(f, now):
        return Finding("late", days_between(f.carrier_eta, now), "carrier ETA passed")
    if f.status == "delayed":
        return Finding("late", f.days_since_scan, f.last_desc or "carrier delay")
    if t := _open(view, "wismo"):
        return Finding("wismo", days_between(t["opened_at"], now), "customer asking for status")
    return Finding("none", 0)
