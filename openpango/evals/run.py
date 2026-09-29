"""Run every bundled incident and print a score table. Exit code 1 if anything is below threshold."""
from __future__ import annotations

import json

from .. import eventlog, replay
from . import scorers

THRESHOLD = 1.0


def evaluate(drafter=None) -> list[dict]:
    rows = []
    for fx in replay.list_incidents():
        r = replay.run(fx["id"], drafter=drafter)
        a, af = scorers.score_next_action(r)
        c, cf = scorers.score_copy(r)
        n, nf = scorers.score_no_invented_facts(r)
        log_ok, _ = eventlog.verify_chain(r.conn)
        rows.append({"incident": fx["id"], "action": a, "copy": c, "no_invented_facts": n, "log_ok": log_ok,
                     "passed": min(a, c, n) >= THRESHOLD and log_ok, "failures": af + cf + nf})
    return rows


def main(as_json: bool = False, drafter=None) -> int:
    rows = evaluate(drafter)
    if as_json:
        print(json.dumps(rows, indent=2))
    else:
        print(f"{'incident':<26}{'next action':>12}{'copy':>8}{'no invented':>13}{'log':>6}   result")
        for r in rows:
            print(f"{r['incident']:<26}{r['action']:>12.2f}{r['copy']:>8.2f}{r['no_invented_facts']:>13.2f}"
                  f"{'ok' if r['log_ok'] else 'BAD':>6}   {'PASS' if r['passed'] else 'FAIL'}")
            for f in r["failures"]:
                print(f"    - {f}")
        n = sum(r["passed"] for r in rows)
        print(f"\n{n}/{len(rows)} incidents passed")
    return 0 if all(r["passed"] for r in rows) else 1
