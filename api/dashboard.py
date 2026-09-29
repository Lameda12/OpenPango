import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpango import web  # noqa: E402


class handler(web.JSONHandler):
    def route(self, q):
        return web.aging()
