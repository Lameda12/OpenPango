"""Load an incident fixture into a fresh database, freeze the clock, and let ops_lead handle it."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import clock, db
from .agents import ops_lead
from .context import Ctx
from .models import CarrierEvent, Order, Return, Shipment, Ticket

INCIDENT_DIR = Path(__file__).parent / "incidents"


def list_incidents() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(INCIDENT_DIR.glob("*.json"))]


def load_fixture(key: str) -> dict:
    """Accepts an incident id ('1042-customs') or an order number ('1042' / '#1042')."""
    key = key.lstrip("#")
    for fx in list_incidents():
        if fx["id"] == key or fx["order"]["number"] == key:
            return fx
    raise KeyError(f"unknown incident {key!r}; run `python -m openpango list`")


def apply_fixture(conn: sqlite3.Connection, fx: dict) -> None:
    now = clock.parse(fx["clock"])
    o, s = fx["order"], fx["shipment"]
    with conn:
        oid = db.insert(conn, "orders", Order(
            number=o["number"], customer_name=o["customer_name"], email=o["email"], items=o["items"],
            total_cents=o["total_cents"], placed_at=clock.ago(now, o["placed_at_ago_days"]),
            country=o["country"], address=o["address"]))
        sid = db.insert(conn, "shipments", Shipment(
            order_id=oid, carrier=s["carrier"], service=s["service"], tracking_number=s["tracking_number"],
            shipped_at=clock.ago(now, s["shipped_at_ago_days"]), weight_g=s["weight_g"],
            address=o["address"], carrier_eta=s.get("carrier_eta")))
        for e in fx["events"]:
            db.insert(conn, "carrier_events", CarrierEvent(
                shipment_id=sid, ts=clock.ago(now, e["ago_days"]), code=e["code"],
                description=e["description"], location=e.get("location"), eta=e.get("eta")))
        if fx.get("return"):
            r = fx["return"]
            db.insert(conn, "returns", Return(order_id=oid, reason=r["reason"], amount_cents=r["amount_cents"],
                                              requested_at=clock.ago(now, r["ago_days"])))
        for t in fx.get("tickets", []):
            db.insert(conn, "tickets", Ticket(order_id=oid, kind=t["kind"], subject=t["subject"], body=t["body"],
                                              opened_at=clock.ago(now, t["ago_days"])))


@dataclass
class Replay:
    fixture: dict
    ctx: Ctx
    decision: ops_lead.Decision

    @property
    def conn(self) -> sqlite3.Connection:
        return self.ctx.conn


def run(key: str, *, drafter=None, db_path: str = ":memory:") -> Replay:
    fx = load_fixture(key)
    conn = db.connect(db_path)
    apply_fixture(conn, fx)
    ctx = Ctx(conn=conn, now=clock.parse(fx["clock"]))
    if drafter is not None:
        ctx.drafter = drafter
    return Replay(fx, ctx, ops_lead.handle(ctx, fx["order"]["number"]))


def seed_all(conn: sqlite3.Connection, *, drafter=None) -> list[ops_lead.Decision]:
    """Load every incident into one database and run ops_lead on each. Used by the inbox UI."""
    out = []
    for fx in list_incidents():
        apply_fixture(conn, fx)
        ctx = Ctx(conn=conn, now=clock.parse(fx["clock"]))
        if drafter is not None:
            ctx.drafter = drafter
        out.append(ops_lead.handle(ctx, fx["order"]["number"]))
    return out


def format_text(r: Replay) -> str:
    fx, d, conn = r.fixture, r.decision, r.conn
    view = db.load_view(conn, number=fx["order"]["number"])
    lines = [
        f"INCIDENT  {fx['title']}",
        f"clock     {fx['clock']} (frozen)",
        f"shipment  {view['shipment']['carrier']} {view['shipment']['tracking_number']}",
        "",
        "CARRIER EVENTS",
    ]
    for e in view["events"]:
        loc = f"  [{e['location']}]" if e["location"] else ""
        lines.append(f"  {e['ts'][:10]}  {e['code']:<16} {e['description']}{loc}")
    lines += ["", "DECISION",
              f"  exception  {d.exception}",
              f"  action     {d.action}",
              f"  approval   {d.approval}",
              f"  follow-up  {d.follow_up[:10] if d.follow_up else '-'}",
              f"  why        {d.rationale}", "", "TOOL CALLS (immutable event log)"]
    for c in d.calls:
        lines.append(f"  #{c['event_id']:<3} {c['actor']:<15} {c['tool']}")
    if d.draft:
        lines += ["", f"DRAFT EMAIL  (guard: {'PASS' if not d.draft['violations'] else 'BLOCKED'})",
                  f"  To: {view['order']['email']}", f"  Subject: {d.draft['subject']}", ""]
        lines += ["  " + ln if ln else "" for ln in d.draft["body"].splitlines()]
        for v in d.draft["violations"]:
            lines.append(f"  ! {v['kind']}: {v['text']}")
    return "\n".join(lines)


def to_json(r: Replay) -> dict:
    d = r.decision
    return {"incident": r.fixture["id"], "order": d.order_number, "exception": d.exception, "action": d.action,
            "approval": d.approval, "follow_up": d.follow_up, "rationale": d.rationale, "calls": d.calls,
            "draft": d.draft}
