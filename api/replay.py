import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpango import web

handler = web.make_handler(lambda q: web.replay_incident(q.get("incident", "1042-customs")))
