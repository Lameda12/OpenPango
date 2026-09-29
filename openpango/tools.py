"""The six agent tools plus two human-only ones. Each call writes state and one event in a single transaction."""
from __future__ import annotations

import json

from . import db, eventlog, facts, guard, policy
from .clock import fmt_money, iso
from .context import Ctx
from datetime import timedelta


def _log(ctx: Ctx, tool: str, etype: str, eid: int | None, payload: dict) -> int:
    return eventlog.append(ctx.conn, ts=iso(ctx.now), actor=ctx.actor, tool=tool,
                           entity_type=etype, entity_id=eid, payload=payload)


def lookup_order(ctx: Ctx, number: str) -> dict:
    view = db.load_view(ctx.conn, number=number)
    if view is None:
        raise LookupError(f"order {number} not found")
    with ctx.conn:
        eid = _log(ctx, "lookup_order", "order", view["order"]["id"], {"number": number})
    return {**view, "event_id": eid}


def rerate_shipment(ctx: Ctx, shipment_id: int, address: str) -> dict:
    ship = db.one(ctx.conn, "SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    order = db.one(ctx.conn, "SELECT * FROM orders WHERE id = ?", (ship["order_id"],))
    old = ctx.carrier.rate_cents(ship["weight_g"], order["country"], ship["service"])
    new = old + (ctx.carrier.ADDRESS_CORRECTION_CENTS if address != ship["address"] else 0)
    with ctx.conn:
        db.update(ctx.conn, "shipments", shipment_id, address=address)
        eid = _log(ctx, "rerate_shipment", "shipment", shipment_id,
                   {"old_cents": old, "new_cents": new, "address": address})
    return {"old_cents": old, "new_cents": new, "delta_cents": new - old, "event_id": eid}


def issue_label(ctx: Ctx, shipment_id: int, reason: str) -> dict:
    ship = db.one(ctx.conn, "SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    seed = f"{shipment_id}:{ship['tracking_number']}:{reason}"
    tracking, label = ctx.carrier.new_tracking(seed), ctx.carrier.new_label_id(seed)
    with ctx.conn:
        db.update(ctx.conn, "shipments", shipment_id, tracking_number=tracking, label_id=label, carrier_eta=None)
        db.insert(ctx.conn, "carrier_events", {
            "shipment_id": shipment_id, "ts": iso(ctx.now), "code": "LABEL_CREATED",
            "description": "Replacement shipping label created", "location": None, "eta": None})
        eid = _log(ctx, "issue_label", "shipment", shipment_id, {
            "reason": reason, "tracking_number": tracking, "previous_tracking": ship["tracking_number"], "label_id": label})
    return {"tracking_number": tracking, "previous_tracking": ship["tracking_number"], "label_id": label, "event_id": eid}


def approve_refund(ctx: Ctx, order_id: int, amount_cents: int, reason_code: str, return_id: int | None = None) -> dict:
    """Auto-issues small refunds. Above $75 or for lost packages it only files an approval request."""
    order = db.one(ctx.conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
    already = db.one(ctx.conn, "SELECT COALESCE(SUM(amount_cents),0) AS s FROM refunds WHERE order_id = ?", (order_id,))["s"]
    if amount_cents <= 0 or amount_cents + already > order["total_cents"]:
        raise ValueError(f"invalid refund {fmt_money(amount_cents)} for order total {fmt_money(order['total_cents'])}")
    gate = policy.approval_gate(amount_cents, reason_code)
    now = iso(ctx.now)
    with ctx.conn:
        if gate:
            aid = db.insert(ctx.conn, "approvals", {
                "order_id": order_id, "return_id": return_id, "kind": "refund", "amount_cents": amount_cents,
                "reason_code": reason_code, "status": "pending", "requested_by": ctx.actor, "requested_at": now})
            if return_id:
                db.update(ctx.conn, "returns", return_id, status="pending_approval")
            eid = _log(ctx, "approve_refund", "order", order_id, {
                "outcome": "pending_approval", "gate": gate, "amount_cents": amount_cents,
                "reason_code": reason_code, "approval_id": aid})
            return {"status": "pending_approval", "gate": gate, "approval_id": aid, "amount_cents": amount_cents, "event_id": eid}
        rid = db.insert(ctx.conn, "refunds", {"order_id": order_id, "amount_cents": amount_cents,
                                              "approval_id": None, "issued_at": now, "issued_by": ctx.actor})
        if return_id:
            db.update(ctx.conn, "returns", return_id, status="refund_issued")
        eid = _log(ctx, "approve_refund", "order", order_id, {
            "outcome": "refund_issued", "amount_cents": amount_cents, "reason_code": reason_code, "refund_id": rid})
    return {"status": "refund_issued", "refund_id": rid, "amount_cents": amount_cents, "event_id": eid}


def draft_customer_email(ctx: Ctx, order_id: int, template: str, extras: dict | None = None,
                         ticket_id: int | None = None) -> dict:
    extras = extras or {}
    view = db.load_view(ctx.conn, order_id=order_id)
    f = facts.build(view, ctx.now)
    subject, body = ctx.drafter.draft(template, view["order"], f, extras)
    violations = [v.as_dict() for v in guard.check(f"{subject}\n{body}", f, extras)]
    status = "blocked" if violations else "ready"
    with ctx.conn:
        did = db.insert(ctx.conn, "drafts", {
            "order_id": order_id, "ticket_id": ticket_id, "template": template, "subject": subject, "body": body,
            "extras_json": json.dumps(extras, sort_keys=True), "guard_ok": int(not violations),
            "violations_json": json.dumps(violations), "status": status, "created_by": ctx.actor,
            "created_at": iso(ctx.now)})
        eid = _log(ctx, "draft_customer_email", "order", order_id, {
            "draft_id": did, "template": template, "status": status, "violations": violations})
    return {"draft_id": did, "status": status, "violations": violations, "subject": subject, "body": body, "event_id": eid}


def open_ticket(ctx: Ctx, order_id: int, kind: str, subject: str, body: str = "") -> dict:
    ship = db.one(ctx.conn, "SELECT * FROM shipments WHERE order_id = ? ORDER BY id DESC LIMIT 1", (order_id,))
    ref = ctx.carrier.open_case(kind, ship["tracking_number"]) if ship and kind in policy.CARRIER_TICKET_KINDS else None
    days = policy.FOLLOWUP_DAYS.get(kind)
    due = iso(ctx.now + timedelta(days=days)) if days else None
    with ctx.conn:
        tid = db.insert(ctx.conn, "tickets", {
            "order_id": order_id, "kind": kind, "subject": subject, "body": body, "status": "open",
            "opened_at": iso(ctx.now), "due_at": due, "carrier_ref": ref, "opened_by": ctx.actor})
        eid = _log(ctx, "open_ticket", "order", order_id, {
            "ticket_id": tid, "kind": kind, "due_at": due, "carrier_ref": ref})
    return {"ticket_id": tid, "kind": kind, "due_at": due, "carrier_ref": ref, "event_id": eid}


# Human-only tools (see policy.AGENT_TOOLS["human"]).

def decide_approval(ctx: Ctx, approval_id: int, approve: bool) -> dict:
    ap = db.one(ctx.conn, "SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if ap is None or ap["status"] != "pending":
        raise ValueError(f"approval {approval_id} is not pending")
    now = iso(ctx.now)
    with ctx.conn:
        db.update(ctx.conn, "approvals", approval_id, status="approved" if approve else "rejected",
                  decided_by=ctx.actor, decided_at=now)
        if approve:
            db.insert(ctx.conn, "refunds", {"order_id": ap["order_id"], "amount_cents": ap["amount_cents"],
                                            "approval_id": approval_id, "issued_at": now, "issued_by": ctx.actor})
        if ap["return_id"]:
            db.update(ctx.conn, "returns", ap["return_id"], status="refund_issued" if approve else "in_review")
        eid = _log(ctx, "decide_approval", "order", ap["order_id"], {
            "approval_id": approval_id, "approved": approve, "amount_cents": ap["amount_cents"]})
    return {"approval_id": approval_id, "approved": approve, "event_id": eid}


def send_draft(ctx: Ctx, draft_id: int) -> dict:
    d = db.one(ctx.conn, "SELECT * FROM drafts WHERE id = ?", (draft_id,))
    if d is None or d["status"] != "ready":
        raise ValueError(f"draft {draft_id} is not sendable (status={d and d['status']})")
    with ctx.conn:
        db.update(ctx.conn, "drafts", draft_id, status="sent")
        if d["ticket_id"]:
            db.update(ctx.conn, "tickets", d["ticket_id"], status="closed")
        eid = _log(ctx, "send_draft", "order", d["order_id"], {"draft_id": draft_id, "mock_delivery": True})
    return {"draft_id": draft_id, "event_id": eid}


REGISTRY = {f.__name__: f for f in (
    lookup_order, rerate_shipment, issue_label, approve_refund, draft_customer_email, open_ticket,
    decide_approval, send_draft)}
WRITE_TOOLS = frozenset(REGISTRY) - {"lookup_order"}
