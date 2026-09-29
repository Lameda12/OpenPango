"""Ops inbox: stdlib HTTP server, JSON API, one static HTML page."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import clock, dashboard, db, eventlog, replay
from .context import Ctx

UI = Path(__file__).parent / "ui" / "index.html"


class App:
    def __init__(self, conn):
        self.conn = conn
        self.lock = threading.Lock()
        self.now = clock.parse(clock.DEMO_NOW)

    def human(self) -> Ctx:
        return Ctx(conn=self.conn, now=self.now, actor="human")

    def get(self, path: str) -> tuple[int, object]:
        with self.lock:
            if path == "/api/dashboard":
                return 200, dashboard.aging(self.conn, self.now)
            if path == "/api/inbox":
                return 200, dashboard.inbox(self.conn)
            if path == "/api/events":
                ok, bad = eventlog.verify_chain(self.conn)
                return 200, {"chain_ok": ok, "first_bad": bad, "events": eventlog.read(self.conn)[-200:][::-1]}
        return 404, {"error": "not found"}

    def post(self, path: str, body: dict) -> tuple[int, object]:
        parts = path.strip("/").split("/")
        try:
            with self.lock:
                if parts[:2] == ["api", "approvals"] and len(parts) == 3:
                    return 200, self.human().tool("decide_approval", approval_id=int(parts[2]), approve=bool(body.get("approve")))
                if parts[:2] == ["api", "drafts"] and len(parts) == 4 and parts[3] == "send":
                    return 200, self.human().tool("send_draft", draft_id=int(parts[2]))
        except (ValueError, KeyError) as exc:
            return 409, {"error": str(exc)}
        return 404, {"error": "not found"}


def make_handler(app: App):
    class H(BaseHTTPRequestHandler):
        def _send(self, code: int, payload, ctype="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
            self._send(*app.get(self.path.split("?")[0]))

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(*app.post(self.path, body))

        def log_message(self, *a):
            pass
    return H


def build_app(db_path: str = ":memory:", drafter=None) -> App:
    conn = db.connect(db_path)
    if not db.one(conn, "SELECT 1 AS x FROM orders LIMIT 1"):
        replay.seed_all(conn, drafter=drafter)
    return App(conn)


def serve(host: str, port: int, db_path: str) -> None:
    app = build_app(db_path)
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"OpenPango inbox on http://{host}:{srv.server_address[1]}  (clock frozen at {clock.DEMO_NOW})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
