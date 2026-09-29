import json

import pytest

from openpango import clock, db, eventlog, replay
from openpango.agents import exceptions
from openpango.evals import run as evals

IDS = [fx["id"] for fx in replay.list_incidents()]


def test_ten_incidents_bundled():
    assert len(IDS) == 10


@pytest.mark.parametrize("incident", IDS)
def test_every_incident_passes_eval(incident):
    row = next(r for r in evals.evaluate() if r["incident"] == incident)
    assert row["passed"], row["failures"]


def test_hero_incident():
    r = replay.run("1042-customs")
    d = r.decision
    assert (d.exception, d.action, d.approval) == ("stuck_customs", "carrier_inquiry", "none")
    body = d.draft["body"]
    assert "JD014600006281" in body and "9 days" in body and "won't guess" in body
    assert replay.run("1042").decision.action == d.action        # order number works as a key


def test_replay_is_deterministic():
    a, b = replay.run("lost-package"), replay.run("lost-package")
    assert replay.to_json(a) == replay.to_json(b)
    assert [e["hash"] for e in eventlog.read(a.conn)] == [e["hash"] for e in eventlog.read(b.conn)]


def test_lost_package_refund_waits_for_a_human():
    r = replay.run("lost-package")
    assert r.decision.approval == "pending"
    assert r.conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0
    assert "has been issued" not in r.decision.draft["body"]


def test_small_damaged_refund_auto_issues():
    r = replay.run("damaged-refund")
    assert r.conn.execute("SELECT SUM(amount_cents) FROM refunds").fetchone()[0] == 4000


def test_late_return_gets_no_refund():
    r = replay.run("return-late")
    assert r.conn.execute("SELECT COUNT(*) FROM refunds").fetchone()[0] == 0


def test_handling_twice_does_not_double_file_with_carrier():
    from openpango.agents import ops_lead
    r = replay.run("1042-customs")
    ops_lead.handle(r.ctx, "1042")
    n = r.conn.execute("SELECT COUNT(*) FROM tickets WHERE kind = 'carrier_inquiry'").fetchone()[0]
    assert n == 1


def test_classify_none_for_healthy_order():
    from openpango.agents import ops_lead
    r = replay.run("wismo-normal")
    f = exceptions.classify(db.load_view(r.conn, number="1063"), r.ctx.now)
    assert f.type == "wismo"


def test_cli_replay_output(capsys):
    from openpango.__main__ import main
    assert main(["replay", "1042-customs"]) == 0
    out = capsys.readouterr().out
    assert "action     carrier_inquiry" in out and "DRAFT EMAIL  (guard: PASS)" in out
    assert main(["replay", "nope"]) == 2


def test_cli_eval_exit_code(capsys):
    from openpango.__main__ import main
    assert main(["eval"]) == 0
    assert "10/10 incidents passed" in capsys.readouterr().out


def test_claude_drafter_output_goes_through_guard():
    from openpango.drafters import ClaudeDrafter

    class Block:
        type = "text"
        def __init__(self, text): self.text = text

    class Client:
        def __init__(self, text): self.text = text
        @property
        def messages(self): return self
        def create(self, **kw):
            assert kw["model"] and "reference_draft" in kw["messages"][0]["content"]
            return type("R", (), {"content": [Block(self.text)]})()

    bad = replay.run("1042-customs", drafter=ClaudeDrafter(Client("Your parcel will arrive in 2 days.")))
    assert bad.decision.draft["status"] == "blocked"
