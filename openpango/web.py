"""Pure functions behind the read-only web demo (Vercel functions and scripts/dev_vercel.py).

Serverless is stateless, so the demo replays incidents into a fresh in-memory DB per request.
Approvals and sending stay in the local `serve` inbox, which needs a persistent process.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import clock, dashboard, db, replay
from .evals import run as evals


def incidents() -> dict:
    return {"incidents": [
        {"id": fx["id"], "order": fx["order"]["number"], "title": fx["title"],
         "expected_action": fx["expected"]["action"]} for fx in replay.list_incidents()]}


def replay_incident(key: str) -> dict:
    r = replay.run(key)
    view = db.load_view(r.conn, number=r.fixture["order"]["number"])
    out = replay.to_json(r)
    out.update(
        title=r.fixture["title"], clock=r.fixture["clock"], carrier=view["shipment"]["carrier"],
        tracking_number=view["shipment"]["tracking_number"], to=view["order"]["email"],
        events=[{k: e[k] for k in ("ts", "code", "description", "location")} for e in view["events"]],
        text=replay.format_text(r))
    return out


def eval_all() -> dict:
    rows = evals.evaluate()
    return {"passed": sum(r["passed"] for r in rows), "total": len(rows), "rows": rows}


def aging() -> dict:
    conn = db.connect()
    replay.seed_all(conn)
    return dashboard.aging(conn, clock.parse(clock.DEMO_NOW))


class JSONHandler(BaseHTTPRequestHandler):
    """Base for the Vercel functions. Subclasses implement route(query) -> dict.

    Vercel only detects a Python function when the file itself defines `class handler`,
    so each api/*.py subclasses this instead of assigning a factory result.
    KeyError => 404, anything else => 500.
    """

    def route(self, query: dict[str, str]) -> dict:
        raise NotImplementedError

    def do_GET(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        try:
            code, body = 200, self.route(q)
        except KeyError as exc:
            code, body = 404, {"error": str(exc.args[0]) if exc.args else "not found"}
        except Exception as exc:  # never leak a traceback to the browser
            code, body = 500, {"error": type(exc).__name__}
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        # Output is deterministic (frozen clock, mocked data), so it is safe to cache at the edge.
        self.send_header("Cache-Control", "public, s-maxage=3600, stale-while-revalidate=86400" if code == 200 else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass
