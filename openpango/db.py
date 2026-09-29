"""SQLite storage. Plain SQL, no ORM. Event-log immutability is enforced by triggers."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, is_dataclass
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE NOT NULL,
  customer_name TEXT NOT NULL, email TEXT NOT NULL, items TEXT NOT NULL,
  total_cents INTEGER NOT NULL, placed_at TEXT NOT NULL, country TEXT NOT NULL, address TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shipments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  carrier TEXT NOT NULL, service TEXT NOT NULL, tracking_number TEXT NOT NULL,
  shipped_at TEXT NOT NULL, weight_g INTEGER NOT NULL, address TEXT NOT NULL,
  carrier_eta TEXT, label_id TEXT);
CREATE TABLE IF NOT EXISTS carrier_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
  ts TEXT NOT NULL, code TEXT NOT NULL, description TEXT NOT NULL, location TEXT, eta TEXT);
CREATE TABLE IF NOT EXISTS returns(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  reason TEXT NOT NULL, amount_cents INTEGER NOT NULL, requested_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'requested');
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  kind TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open', opened_at TEXT NOT NULL, due_at TEXT,
  carrier_ref TEXT, opened_by TEXT NOT NULL DEFAULT 'customer');
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  return_id INTEGER, kind TEXT NOT NULL, amount_cents INTEGER NOT NULL, reason_code TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', requested_by TEXT NOT NULL, requested_at TEXT NOT NULL,
  decided_by TEXT, decided_at TEXT);
CREATE TABLE IF NOT EXISTS refunds(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  amount_cents INTEGER NOT NULL, approval_id INTEGER, issued_at TEXT NOT NULL, issued_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  ticket_id INTEGER, template TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
  extras_json TEXT NOT NULL, guard_ok INTEGER NOT NULL, violations_json TEXT NOT NULL,
  status TEXT NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, actor TEXT NOT NULL, tool TEXT NOT NULL,
  entity_type TEXT NOT NULL, entity_id INTEGER, payload TEXT NOT NULL,
  prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
  BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
  BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert(conn: sqlite3.Connection, table: str, row: Any) -> int:
    data = asdict(row) if is_dataclass(row) else dict(row)
    if data.get("id") is None:
        data.pop("id", None)
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))
    return int(cur.lastrowid)


def update(conn: sqlite3.Connection, table: str, row_id: int, **cols: Any) -> None:
    sets = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*cols.values(), row_id))


def one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def load_view(conn: sqlite3.Connection, *, number: str | None = None, order_id: int | None = None) -> dict | None:
    """Everything the agents need about one order. Read-only, no event logged."""
    if number is not None:
        order = one(conn, "SELECT * FROM orders WHERE number = ?", (str(number).lstrip("#"),))
    else:
        order = one(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        return None
    oid = order["id"]
    shipment = one(conn, "SELECT * FROM shipments WHERE order_id = ? ORDER BY id DESC LIMIT 1", (oid,))
    events = (
        many(conn, "SELECT * FROM carrier_events WHERE shipment_id = ? ORDER BY ts, id", (shipment["id"],))
        if shipment else []
    )
    return {
        "order": order,
        "shipment": shipment,
        "events": events,
        "returns": many(conn, "SELECT * FROM returns WHERE order_id = ? ORDER BY id", (oid,)),
        "tickets": many(conn, "SELECT * FROM tickets WHERE order_id = ? ORDER BY id", (oid,)),
    }
