import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from openpango import server


def test_dashboard_buckets():
    app = server.build_app()
    code, dash = app.get("/api/dashboard")
    b = dash["buckets"]
    assert code == 200
    assert b["stuck_customs"]["count"] == 1 and b["stuck_customs"]["oldest_days"] == 9
    assert b["late"]["count"] == 1 and b["refused_delivery"]["count"] == 1
    assert b["wismo"]["count"] == 2
    assert {i["type"] for i in b["other"]["items"]} == {"lost", "delivered_dispute", "not_picked_up"}


def test_approve_flow_over_http():
    app = server.build_app()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        inbox = json.load(urllib.request.urlopen(base + "/api/inbox"))
        pending = [a for a in inbox["approvals"] if a["status"] == "pending"]
        assert len(pending) == 1 and pending[0]["amount_cents"] == 12000
        req = urllib.request.Request(f"{base}/api/approvals/{pending[0]['id']}", data=b'{"approve": true}', method="POST")
        assert json.load(urllib.request.urlopen(req))["approved"] is True
        ev = json.load(urllib.request.urlopen(base + "/api/events"))
        assert ev["chain_ok"] and ev["events"][0]["actor"] == "human"
        assert b"OpenPango" in urllib.request.urlopen(base + "/").read()
    finally:
        srv.shutdown()


def test_send_blocked_draft_is_refused():
    app = server.build_app()
    code, _ = app.post("/api/drafts/999/send", {})
    assert code == 409


def test_web_demo_payloads():
    from openpango import web
    assert len(web.incidents()["incidents"]) == 10
    r = web.replay_incident("1042")
    assert r["action"] == "carrier_inquiry" and r["events"][0]["code"] == "PICKED_UP" and "JD014600006281" in r["draft"]["body"]
    assert web.eval_all()["passed"] == 10
    assert web.aging()["buckets"]["stuck_customs"]["count"] == 1


def test_vercel_config_is_valid_and_points_at_real_paths():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cfg = json.loads((root / "vercel.json").read_text())
    assert (root / cfg["outputDirectory"] / "index.html").exists()
    assert sorted(p.name for p in (root / "api").glob("*.py")) == ["dashboard.py", "eval.py", "incidents.py", "replay.py"]
