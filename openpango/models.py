"""Core objects. Fields map 1:1 to table columns; money is integer cents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Order:
    number: str
    customer_name: str
    email: str
    items: str
    total_cents: int
    placed_at: str
    country: str
    address: str
    id: int | None = None


@dataclass
class Shipment:
    order_id: int
    carrier: str
    service: str
    tracking_number: str
    shipped_at: str
    weight_g: int
    address: str
    carrier_eta: str | None = None
    label_id: str | None = None
    id: int | None = None


@dataclass
class CarrierEvent:
    shipment_id: int
    ts: str
    code: str
    description: str
    location: str | None = None
    eta: str | None = None
    id: int | None = None


@dataclass
class Return:
    order_id: int
    reason: str           # damaged | not_received | changed_mind
    amount_cents: int
    requested_at: str
    status: str = "requested"   # requested | pending_approval | refund_issued | in_review
    id: int | None = None


@dataclass
class Ticket:
    order_id: int
    kind: str             # wismo | not_received | address_update | carrier_inquiry | carrier_claim | ...
    subject: str
    opened_at: str
    body: str = ""
    status: str = "open"
    due_at: str | None = None
    carrier_ref: str | None = None
    opened_by: str = "customer"
    id: int | None = None
