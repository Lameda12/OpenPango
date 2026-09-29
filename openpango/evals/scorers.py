"""Three scorers, each in [0, 1]. They read the event log and database, not the agent's own report."""
from __future__ import annotations

import json

from .. import db, eventlog, facts, guard, tools


def _resolve(phrase: str, tracking: str, previous: str) -> str:
    return phrase.replace("$PREVIOUS_TRACKING", previous).replace("$TRACKING", tracking)


def _approval_state(conn, order_id: int) -> str:
    if db.one(conn, "SELECT 1 AS x FROM approvals WHERE order_id = ? AND status = 'pending'", (order_id,)):
        return "pending"
    if db.one(conn, "SELECT 1 AS x FROM refunds WHERE order_id = ? AND approval_id IS NULL", (order_id,)):
        return "auto"
    return "none"


def score_next_action(replay) -> tuple[float, list[str]]:
    exp, conn = replay.fixture["expected"], replay.conn
    order = db.load_view(conn, number=replay.fixture["order"]["number"])
    oid = order["order"]["id"]
    d = replay.decision
    events = [e for e in eventlog.read(conn) if e["tool"] in tools.WRITE_TOOLS and e["entity_id"] in (oid, order["shipment"]["id"])]
    seq = [e["tool"] for e in events]
    kinds = [e["payload"].get("kind") for e in events if e["tool"] == "open_ticket"]
    checks = {
        "exception": d.exception == exp["exception"],
        "action": d.action == exp["action"],
        "tool sequence": seq == exp["tools"],
        "approval gate": _approval_state(conn, oid) == exp["approval"] == d.approval,
        "ticket kind": exp.get("ticket_kind") is None or exp["ticket_kind"] in kinds,
    }
    want = {"exception": exp["exception"], "action": exp["action"], "tool sequence": exp["tools"],
            "approval gate": exp["approval"], "ticket kind": exp.get("ticket_kind")}
    got = {"exception": d.exception, "action": d.action, "tool sequence": seq,
           "approval gate": _approval_state(conn, oid), "ticket kind": kinds}
    fails = [f"{k}: got {got[k]!r}, want {want[k]!r}" for k, ok in checks.items() if not ok]
    return sum(checks.values()) / len(checks), fails


def _draft(replay) -> dict | None:
    oid = db.load_view(replay.conn, number=replay.fixture["order"]["number"])["order"]["id"]
    return db.one(replay.conn, "SELECT * FROM drafts WHERE order_id = ? ORDER BY id DESC LIMIT 1", (oid,))


def score_copy(replay) -> tuple[float, list[str]]:
    draft = _draft(replay)
    if draft is None or draft["status"] == "blocked":
        return 0.0, ["no usable draft (missing or blocked by guard)"]
    fx = replay.fixture
    view = db.load_view(replay.conn, number=fx["order"]["number"])
    tracking, previous = view["shipment"]["tracking_number"], fx["shipment"]["tracking_number"]
    text = (draft["subject"] + "\n" + draft["body"]).lower()
    req = [_resolve(p, tracking, previous) for p in fx["expected"]["copy"]["required"]]
    bad = [_resolve(p, tracking, previous) for p in fx["expected"]["copy"]["forbidden"]]
    missing = [p for p in req if p.lower() not in text]
    present_bad = [p for p in bad if p.lower() in text]
    total = len(req) + len(bad)
    fails = [f"missing: {p!r}" for p in missing] + [f"forbidden present: {p!r}" for p in present_bad]
    return (total - len(fails)) / total, fails


def score_no_invented_facts(replay) -> tuple[float, list[str]]:
    """Re-run the guard against facts rebuilt from the database, independent of the draft tool's own verdict."""
    draft = _draft(replay)
    if draft is None:
        return 0.0, ["no draft"]
    view = db.load_view(replay.conn, number=replay.fixture["order"]["number"])
    f = facts.build(view, replay.ctx.now)
    found = guard.check(f"{draft['subject']}\n{draft['body']}", f, json.loads(draft["extras_json"]))
    return (0.0 if found else 1.0), [f"{v.kind}: {v.text}" for v in found]
