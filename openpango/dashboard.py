"""Aging-exceptions dashboard and inbox queries. Read-only; logs nothing."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from . import clock, db
from .agents import exceptions

BUCKETS = ("late", "stuck_customs", "refused_delivery", "wismo", "other")
_BUCKET_OF = {"late": "late", "stuck_customs": "stuck_customs", "refused": "refused_delivery"}
_SKIP = {"none", "return_request", "wismo"}   # wismo is counted from tickets below


def aging(conn: sqlite3.Connection, now: datetime) -> dict:
    buckets: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for o in db.many(conn, "SELECT number FROM orders ORDER BY id"):
        view = db.load_view(conn, number=o["number"])
        fnd = exceptions.classify(view, now)
        if fnd.type in _SKIP:
            continue
        buckets[_BUCKET_OF.get(fnd.type, "other")].append({
            "order": o["number"], "type": fnd.type, "age_days": fnd.age_days, "detail": fnd.detail,
            "customer": view["order"]["customer_name"], "carrier": view["shipment"]["carrier"]})
    for t in db.many(conn, "SELECT t.*, o.number, o.customer_name FROM tickets t JOIN orders o ON o.id = t.order_id "
                           "WHERE t.kind = 'wismo' AND t.status = 'open'"):
        buckets["wismo"].append({"order": t["number"], "type": "wismo", "age_days": clock.days_between(t["opened_at"], now),
                                 "detail": t["subject"], "customer": t["customer_name"], "carrier": None})
    for items in buckets.values():
        items.sort(key=lambda i: -i["age_days"])
    return {"now": clock.iso(now),
            "buckets": {b: {"count": len(v), "oldest_days": v[0]["age_days"] if v else 0, "items": v}
                        for b, v in buckets.items()}}


def inbox(conn: sqlite3.Connection) -> dict:
    drafts = db.many(conn, "SELECT d.*, o.number, o.email, o.customer_name FROM drafts d "
                           "JOIN orders o ON o.id = d.order_id ORDER BY d.id DESC")
    approvals = db.many(conn, "SELECT a.*, o.number, o.customer_name FROM approvals a "
                              "JOIN orders o ON o.id = a.order_id ORDER BY a.status = 'pending' DESC, a.id DESC")
    tickets = db.many(conn, "SELECT t.*, o.number FROM tickets t JOIN orders o ON o.id = t.order_id "
                            "WHERE t.status = 'open' AND t.kind NOT IN ('wismo','not_received','address_update') ORDER BY t.due_at")
    return {"drafts": drafts, "approvals": approvals, "tickets": tickets}
