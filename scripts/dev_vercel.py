"""Local stand-in for `vercel dev`: serves public/ and routes /api/<name> to api/<name>.py handlers.

    python scripts/dev_vercel.py [port]
"""
import importlib
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "api")]

from openpango.web import JSONHandler  # noqa: E402


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "public"), **kw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            mod = importlib.import_module(path[5:].strip("/"))
            self.route = lambda q: mod.handler.route(self, q)
            return JSONHandler.do_GET(self)
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    print(f"http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
