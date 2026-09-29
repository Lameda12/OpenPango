"""Deterministic email copy. Every factual sentence is filled from TrackingFacts."""
from __future__ import annotations

from .clock import fmt_date, fmt_money
from .facts import TrackingFacts

SIGNOFF = "\nThe Pango Goods support team"


def _scan(f: TrackingFacts) -> str:
    where = f" ({f.last_location})" if f.last_location else ""
    return f'The latest scan, on {f.last_date}, reads: "{f.last_desc}"{where}.'


def _ident(f: TrackingFacts) -> str:
    return f"Order #{f.order_number} is with {f.carrier}, tracking number {f.tracking_number}."


def _no_eta(f: TrackingFacts) -> str:
    return f"{f.carrier} has not provided an estimated delivery date, and we won't guess one."


def _followup(extras: dict) -> str:
    return f"We will check with them again on {fmt_date(extras['followup_date'])}."


def stuck_customs(o, f, x):
    return "Update on your order", [
        _ident(f), _scan(f),
        f"The package has been in customs processing for {f.customs_days} days, since {fmt_date(f.customs_since)}.",
        _no_eta(f),
        f"We have opened an inquiry with {f.carrier}. {_followup(x)}",
        "If customs needs anything from you, we will reach out right away.",
    ]


def late(o, f, x):
    lines = [_ident(f), _scan(f)]
    if f.carrier_eta:
        lines.append(f"The carrier-listed delivery date of {fmt_date(f.carrier_eta)} has passed.")
    lines += [f"{f.carrier} has not provided an updated delivery estimate, and we won't guess one.",
              f"We have opened an inquiry with {f.carrier}. {_followup(x)}"]
    return "Your order is running late", lines


def wismo(o, f, x):
    lines = [_ident(f), _scan(f)]
    if f.carrier_eta:
        lines.append(f"The carrier lists an estimated delivery date of {fmt_date(f.carrier_eta)}.")
    else:
        lines.append(_no_eta(f))
    return "Where your order is", lines


def refused(o, f, x):
    return "Your delivery was refused", [
        _ident(f),
        f"The carrier recorded that delivery was refused on {fmt_date(f.refused_ts)}.",
        _scan(f),
        "The package is being returned to us. Once it is scanned back into our warehouse we will contact you "
        "about next steps. If the refusal was a mistake, reply to this email and we will help.",
    ]


def lost(o, f, x):
    return "We are investigating your package", [
        _ident(f), _scan(f),
        f"That was {f.days_since_scan} days ago, with no carrier movement since, so we cannot currently locate the package.",
        f"We have opened a claim with {f.carrier}.",
        f"Your request for {fmt_money(x['amount_cents'])} has been sent to our team for review. "
        "We will email you as soon as there is a decision.",
    ]


def refund_approved(o, f, x):
    return "Your refund", [
        f"Order #{f.order_number} was delivered on {fmt_date(f.delivered_ts)} (tracking number {f.tracking_number}).",
        f"Your return is approved and a refund of {fmt_money(x['amount_cents'])} has been issued to your original payment method.",
    ]


def refund_pending(o, f, x):
    return "Your return request", [
        f"Order #{f.order_number} was delivered on {fmt_date(f.delivered_ts)} (tracking number {f.tracking_number}).",
        f"Your refund of {fmt_money(x['amount_cents'])} needs sign-off from our team. We will email you once it is decided.",
    ]


def return_denied(o, f, x):
    return "About your return request", [
        f"Order #{f.order_number} was delivered on {fmt_date(f.delivered_ts)} (tracking number {f.tracking_number}), "
        f"{f.delivered_days} days ago.",
        f"Our return window is {x['window_days']} days, so this request is outside the window.",
        f"We have asked a team member to review your request for {fmt_money(x['amount_cents'])} and you will hear back by email.",
    ]


def address_reissue(o, f, x):
    return "We re-sent your shipping label", [
        f"The carrier flagged a delivery address problem on {fmt_date(f.address_issue_ts)} for tracking number {x['previous_tracking']}.",
        "Using the corrected address you sent us, we re-issued the shipping label.",
        f"Your new tracking number is {f.tracking_number} with {f.carrier}. It has not been scanned yet, "
        "and we do not have a delivery estimate.",
    ]


def delivered_dispute(o, f, x):
    return "About your missing delivery", [
        f"{f.carrier} shows order #{f.order_number} as delivered on {fmt_date(f.delivered_ts)} (tracking number {f.tracking_number}).",
        f'The delivery scan reads: "{f.last_desc}" ({f.last_location}).' if f.last_location
        else f'The delivery scan reads: "{f.last_desc}".',
        f"Since you have not received it, we opened a claim with {f.carrier} to trace the delivery. "
        "In the meantime, please check with neighbors and around the delivery location.",
        f"We will update you on {fmt_date(x['followup_date'])}.",
    ]


def not_picked_up(o, f, x):
    return "Your order has not shipped yet", [
        f"{f.carrier} created a shipping label for order #{f.order_number} (tracking number {f.tracking_number}) "
        f"on {fmt_date(f.label_created_ts)}, {f.days_since_scan} days ago.",
        _scan(f),
        f"{f.carrier} has not scanned the package as picked up and has not provided an estimated delivery date.",
        f"We are chasing the pickup with them. {_followup(x)}",
    ]


TEMPLATES = {fn.__name__: fn for fn in (
    stuck_customs, late, wismo, refused, lost, refund_approved, refund_pending,
    return_denied, address_reissue, delivered_dispute, not_picked_up,
)}


def render(name: str, order: dict, f: TrackingFacts, extras: dict) -> tuple[str, str]:
    subject, lines = TEMPLATES[name](order, f, extras)
    first = order["customer_name"].split()[0]
    body = f"Hi {first},\n\n" + "\n\n".join(lines) + "\n" + SIGNOFF
    return f"{subject} (#{order['number']})", body
