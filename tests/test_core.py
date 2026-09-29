import sqlite3

import pytest

from openpango import clock, db, eventlog, facts, guard, policy, replay
from openpango.context import Ctx
from openpango.models import CarrierEvent, Order, Shipment


def make_ctx(total=20000):
    conn = db.connect()
    now = clock.parse(clock.DEMO_NOW)
    with conn:
        oid = db.insert(conn, "orders", Order("9001", "Test Person", "t@example.com", "thing", total,
                                              clock.ago(now, 10), "US", "1 Main St"))
        sid = db.insert(conn, "shipments", Shipment(oid, "UPS", "Ground", "1ZTEST", clock.ago(now, 8), 500, "1 Main St"))
    return Ctx(conn, now), oid, sid


# ---- event log ----------------------------------------------------------------------------

def test_event_log_rejects_update_and_delete():
    ctx, oid, _ = make_ctx()
    ctx.as_actor("ops_lead").tool("lookup_order", number="9001")
    for sql in ("UPDATE events SET actor = 'x'", "DELETE FROM events"):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            ctx.conn.execute(sql)


def test_chain_detects_tampering():
    ctx, *_ = make_ctx()
    lead = ctx.as_actor("ops_lead")
    for _ in range(3):
        lead.tool("lookup_order", number="9001")
    assert eventlog.verify_chain(ctx.conn) == (True, None)
    # Bypass the triggers the way an attacker with file access would.
    ctx.conn.execute("DROP TRIGGER events_no_update")
    ctx.conn.execute("UPDATE events SET payload = '{\"number\":\"evil\"}' WHERE id = 2")
    assert eventlog.verify_chain(ctx.conn) == (False, 2)


def test_every_write_tool_logs_an_event():
    ctx, oid, sid = make_ctx()
    before = lambda: ctx.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    for actor, tool, kw in [
        ("carrier_chaser", "open_ticket", dict(order_id=oid, kind="carrier_inquiry", subject="s")),
        ("carrier_chaser", "rerate_shipment", dict(shipment_id=sid, address="2 Elm St")),
        ("carrier_chaser", "issue_label", dict(shipment_id=sid, reason="test")),
        ("returns", "approve_refund", dict(order_id=oid, amount_cents=1000, reason_code="damaged")),
        ("support_writer", "draft_customer_email", dict(order_id=oid, template="wismo")),
    ]:
        n = before()
        r = ctx.as_actor(actor).tool(tool, **kw)
        assert before() == n + 1 and r["event_id"] == n + 1


def test_agents_cannot_call_tools_outside_their_role():
    ctx, oid, _ = make_ctx()
    with pytest.raises(PermissionError):
        ctx.as_actor("support_writer").tool("approve_refund", order_id=oid, amount_cents=100, reason_code="x")
    with pytest.raises(PermissionError):
        ctx.as_actor("returns").tool("decide_approval", approval_id=1, approve=True)


# ---- approval policy ----------------------------------------------------------------------

def test_refund_threshold_boundary():
    ctx, oid, _ = make_ctx()
    r = ctx.as_actor("returns")
    at = r.tool("approve_refund", order_id=oid, amount_cents=7500, reason_code="damaged")
    over = r.tool("approve_refund", order_id=oid, amount_cents=7501, reason_code="damaged")
    assert at["status"] == "refund_issued"
    assert over["status"] == "pending_approval" and over["gate"] == "over_threshold"
    issued = ctx.conn.execute("SELECT SUM(amount_cents) FROM refunds").fetchone()[0]
    assert issued == 7500        # the over-threshold one moved no money


def test_lost_package_always_needs_approval_even_when_small():
    ctx, oid, _ = make_ctx()
    r = ctx.as_actor("returns").tool("approve_refund", order_id=oid, amount_cents=500, reason_code="lost_package")
    assert r["status"] == "pending_approval" and r["gate"] == "lost_package"
    assert ctx.conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0


def test_human_decision_issues_refund_and_is_logged():
    ctx, oid, _ = make_ctx()
    ap = ctx.as_actor("returns").tool("approve_refund", order_id=oid, amount_cents=9000, reason_code="damaged")
    human = ctx.as_actor("human")
    human.tool("decide_approval", approval_id=ap["approval_id"], approve=True)
    assert ctx.conn.execute("SELECT SUM(amount_cents) FROM refunds").fetchone()[0] == 9000
    last = eventlog.read(ctx.conn)[-1]
    assert (last["actor"], last["tool"]) == ("human", "decide_approval")
    with pytest.raises(ValueError):
        human.tool("decide_approval", approval_id=ap["approval_id"], approve=True)   # no double payout


def test_refund_cannot_exceed_order_total():
    ctx, oid, _ = make_ctx(total=3000)
    with pytest.raises(ValueError):
        ctx.as_actor("returns").tool("approve_refund", order_id=oid, amount_cents=3001, reason_code="damaged")


def test_approval_gate_function():
    assert policy.approval_gate(7500, "damaged") is None
    assert policy.approval_gate(7501, "damaged") == "over_threshold"
    assert policy.approval_gate(1, "lost_package") == "lost_package"


# ---- guard --------------------------------------------------------------------------------

def _facts_for(key="1042-customs"):
    r = replay.run(key)
    v = db.load_view(r.conn, number=r.fixture["order"]["number"])
    return facts.build(v, r.ctx.now), r


@pytest.mark.parametrize("sentence", [
    "Your package will arrive by Friday.",
    "It should be delivered in 3 days.",
    "Expected delivery is next week.",
    "We guarantee it is on the way.",
    "It is expected to arrive on Oct 5, 2026.",   # a date the carrier never gave
])
def test_guard_rejects_invented_eta(sentence):
    f, _ = _facts_for()
    kinds = {v.kind for v in guard.check(sentence, f)}
    assert kinds & {"invented_eta", "unsupported_date", "unsupported_number"}


def test_guard_allows_carrier_supplied_eta_only():
    f, _ = _facts_for("wismo-normal")
    assert f.carrier_eta == "2026-10-02"
    assert not guard.check("The carrier lists an estimated delivery date of Oct 2, 2026.", f)
    assert guard.check("The carrier lists an estimated delivery date of Oct 3, 2026.", f)


def test_guard_rejects_unsupported_claims_and_numbers():
    f, _ = _facts_for()
    assert guard.check("Your order was delivered yesterday.", f)
    assert guard.check("It has been stuck for 14 days.", f)
    f2, _ = _facts_for("wismo-normal")
    assert guard.check("It cleared customs this morning.", f2)


def test_guard_allows_denying_an_estimate():
    f, _ = _facts_for()
    assert not guard.check("DHL Express has not provided an estimated delivery date, and we won't guess one.", f)


def test_hallucinating_drafter_is_blocked_and_scores_zero():
    from openpango.evals import scorers

    class Liar:
        def draft(self, template, order, facts, extras):
            return "Update", "Hi,\n\nGood news: your package will arrive by Friday.\n"

    r = replay.run("1042-customs", drafter=Liar())
    assert r.decision.draft["status"] == "blocked"
    assert scorers.score_no_invented_facts(r)[0] == 0.0
    assert scorers.score_copy(r)[0] == 0.0
