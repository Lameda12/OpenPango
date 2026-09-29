"""TrackingFacts: the only source of claims a customer email may make."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .clock import days_between, fmt_date, parse

_STATUS = {
    "LABEL_CREATED": "label_created",
    "PICKED_UP": "in_transit",
    "IN_TRANSIT": "in_transit",
    "ARRIVED_HUB": "in_transit",
    "OUT_FOR_DELIVERY": "in_transit",
    "DELAY": "delayed",
    "CUSTOMS_HOLD": "customs",
    "CUSTOMS_DELAY": "customs",
    "CUSTOMS_CLEARED": "in_transit",
    "DELIVERED": "delivered",
    "REFUSED": "refused",
    "RETURN_TO_SENDER": "returning",
    "ADDRESS_ISSUE": "address_issue",
}


@dataclass(frozen=True)
class TrackingFacts:
    order_number: str
    carrier: str
    tracking_number: str
    status: str
    last_code: str | None
    last_desc: str | None
    last_location: str | None
    last_ts: str | None
    days_since_scan: int
    customs_since: str | None
    customs_days: int | None
    carrier_eta: str | None
    delivered_ts: str | None
    delivered_days: int | None
    refused_ts: str | None
    address_issue_ts: str | None
    label_created_ts: str | None
    out_for_delivery: bool
    texts: tuple[str, ...]       # every carrier description/location, for quote matching
    dates: tuple[str, ...]       # every formatted date the carrier gave us

    @property
    def last_date(self) -> str | None:
        return fmt_date(self.last_ts) if self.last_ts else None


def build(view: dict, now: datetime) -> TrackingFacts:
    order, ship, events = view["order"], view["shipment"], view["events"]
    events = sorted(events, key=lambda e: (e["ts"], e["id"]))
    last = events[-1] if events else None

    def first_ts(*codes: str) -> str | None:
        return next((e["ts"] for e in events if e["code"] in codes), None)

    status = _STATUS.get(last["code"], "in_transit") if last else "no_data"
    customs_since = first_ts("CUSTOMS_HOLD", "CUSTOMS_DELAY") if status == "customs" else None
    eta = next((e["eta"] for e in reversed(events) if e["eta"]), None) or (ship or {}).get("carrier_eta")
    delivered_ts = first_ts("DELIVERED")
    texts = tuple(sorted({t for e in events for t in (e["description"], e["location"]) if t}))
    dates = {fmt_date(e["ts"]) for e in events}
    if eta:
        dates.add(fmt_date(eta))
    if ship:
        dates.add(fmt_date(ship["shipped_at"]))
    return TrackingFacts(
        order_number=order["number"],
        carrier=ship["carrier"] if ship else "the carrier",
        tracking_number=ship["tracking_number"] if ship else "",
        status=status,
        last_code=last["code"] if last else None,
        last_desc=last["description"] if last else None,
        last_location=last["location"] if last else None,
        last_ts=last["ts"] if last else None,
        days_since_scan=days_between(last["ts"], now) if last else 0,
        customs_since=customs_since,
        customs_days=days_between(customs_since, now) if customs_since else None,
        carrier_eta=eta,
        delivered_ts=delivered_ts,
        delivered_days=days_between(delivered_ts, now) if delivered_ts else None,
        refused_ts=first_ts("REFUSED"),
        address_issue_ts=first_ts("ADDRESS_ISSUE"),
        label_created_ts=first_ts("LABEL_CREATED"),
        out_for_delivery=any(e["code"] == "OUT_FOR_DELIVERY" for e in events),
        texts=texts,
        dates=tuple(sorted(dates)),
    )


def eta_passed(f: TrackingFacts, now: datetime) -> bool:
    return bool(f.carrier_eta) and parse(f.carrier_eta) < now and f.status != "delivered"
