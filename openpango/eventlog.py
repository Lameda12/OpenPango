"""Append-only, hash-chained event log. Every tool call writes here."""
from __future__ import annotations

import hashlib
import json
import sqlite3

GENESIS = "0" * 64


def _digest(prev: str, ts: str, actor: str, tool: str, etype: str, eid: int | None, payload: str) -> str:
    raw = "|".join([prev, ts, actor, tool, etype, str(eid), payload])
    return hashlib.sha256(raw.encode()).hexdigest()


def append(conn: sqlite3.Connection, *, ts: str, actor: str, tool: str,
           entity_type: str, entity_id: int | None, payload: dict) -> int:
    row = conn.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    prev = row[0] if row else GENESIS
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    h = _digest(prev, ts, actor, tool, entity_type, entity_id, body)
    cur = conn.execute(
        "INSERT INTO events(ts, actor, tool, entity_type, entity_id, payload, prev_hash, hash) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ts, actor, tool, entity_type, entity_id, body, prev, h),
    )
    return int(cur.lastrowid)


def verify_chain(conn: sqlite3.Connection) -> tuple[bool, int | None]:
    """Recompute every hash. Returns (ok, first_bad_event_id)."""
    prev = GENESIS
    for r in conn.execute("SELECT * FROM events ORDER BY id"):
        expect = _digest(prev, r["ts"], r["actor"], r["tool"], r["entity_type"], r["entity_id"], r["payload"])
        if r["prev_hash"] != prev or r["hash"] != expect:
            return False, r["id"]
        prev = r["hash"]
    return True, None


def read(conn: sqlite3.Connection, *, entity_type: str | None = None, entity_id: int | None = None,
         since_id: int = 0) -> list[dict]:
    sql, params = "SELECT * FROM events WHERE id > ?", [since_id]
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if entity_id is not None:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    out = []
    for r in conn.execute(sql + " ORDER BY id", params):
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out
