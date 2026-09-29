"""CLI: python -m openpango {replay,list,eval,serve}"""
from __future__ import annotations

import argparse
import json
import sys


def _drafter(name: str):
    if name == "llm":
        from .drafters import ClaudeDrafter
        return ClaudeDrafter()
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="openpango", description="Post-purchase ops agent harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("replay", help="replay one incident and print the recommended action + draft email")
    r.add_argument("incident", help="incident id or order number, e.g. 1042-customs or 1042")
    r.add_argument("--json", action="store_true")
    r.add_argument("--db", default=":memory:", help="SQLite file to keep the event log in")
    r.add_argument("--drafter", choices=["template", "llm"], default="template")

    sub.add_parser("list", help="list bundled incidents")

    e = sub.add_parser("eval", help="score every incident: next action, customer copy, no invented facts")
    e.add_argument("--json", action="store_true")
    e.add_argument("--drafter", choices=["template", "llm"], default="template")

    s = sub.add_parser("serve", help="run the ops inbox UI")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--db", default=":memory:")

    a = p.parse_args(argv)

    if a.cmd == "list":
        from .replay import list_incidents
        for fx in list_incidents():
            print(f"{fx['id']:<24} #{fx['order']['number']:<5} {fx['title']}")
        return 0
    if a.cmd == "replay":
        from . import replay
        try:
            res = replay.run(a.incident, drafter=_drafter(a.drafter), db_path=a.db)
        except KeyError as exc:
            print(exc.args[0], file=sys.stderr)
            return 2
        print(json.dumps(replay.to_json(res), indent=2) if a.json else replay.format_text(res))
        return 0
    if a.cmd == "eval":
        from .evals import run as evals
        return evals.main(as_json=a.json, drafter=_drafter(a.drafter))
    if a.cmd == "serve":
        from . import server
        server.serve(a.host, a.port, a.db)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
