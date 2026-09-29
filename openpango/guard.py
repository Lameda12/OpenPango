"""Email guard: a draft may only assert what TrackingFacts (plus stated policy extras) support.

Checks: invented ETAs, dates not from carrier data, numbers not from facts, and claims
("delivered", "customs", "refused", ...) the tracking data does not back up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .clock import fmt_date, fmt_money
from .facts import TrackingFacts

_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
DATE_RES = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(rf"\b{_MON} \d{{1,2}}(?:, \d{{4}})?\b"),
    re.compile(r"\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\b", re.I),
]
ETA_RES = [re.compile(p, re.I) for p in (
    r"\b(?:will|should|shall|expected to|going to|set to|likely to)\s+(?:\w+\s+)?(?:arrive|be delivered|be there|reach you|get to you|deliver)",
    r"\b(?:estimated|expected|anticipated|projected)\s+(?:delivery|arrival)",
    r"\b(?:arrive|arrives|arriving|delivered)\s+(?:within|in)\s+\d+",
    r"\b(?:tomorrow|next week|this week|later today|guarantee[d]?)\b",
)]
# A sentence that *denies* having an estimate is fine ("has not provided an estimated delivery date").
_NEGATED_ETA = re.compile(r"(?:\bnot\b|n't|\bno\b)\W+(?:\w+\W+){0,4}?(?:estimate|delivery date|eta)", re.I)

_CLAIMS = [
    (re.compile(r"(?<!not )\b(?:was|been|marked as|shows as|scanned as|is) delivered\b", re.I),
     lambda f: f.status == "delivered", "claims delivery without a delivery scan"),
    (re.compile(r"\bcustoms\b", re.I),
     lambda f: f.customs_since is not None, "mentions customs without a customs scan"),
    (re.compile(r"\brefused\b", re.I),
     lambda f: f.refused_ts is not None, "mentions refusal without a refusal scan"),
    (re.compile(r"\bout for delivery\b", re.I),
     lambda f: f.out_for_delivery, "claims out-for-delivery without that scan"),
    (re.compile(r"\bbeing returned to us\b", re.I),
     lambda f: f.status == "returning", "claims return-to-sender without that scan"),
]


@dataclass(frozen=True)
class Violation:
    kind: str      # invented_eta | unsupported_date | unsupported_number | unsupported_claim
    text: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text}


def allowed_literals(f: TrackingFacts, extras: dict) -> list[str]:
    lits = [f.tracking_number, f"#{f.order_number}", f.order_number, *f.dates, *f.texts]
    if extras.get("followup_date"):
        lits.append(fmt_date(extras["followup_date"]))
    if extras.get("amount_cents") is not None:
        lits.append(fmt_money(extras["amount_cents"]))
    if extras.get("previous_tracking"):
        lits.append(extras["previous_tracking"])
    return [x for x in lits if x]


def allowed_ints(f: TrackingFacts, extras: dict) -> set[int]:
    vals = {f.days_since_scan, f.customs_days, f.delivered_days, extras.get("window_days")}
    if f.order_number.isdigit():
        vals.add(int(f.order_number))
    return {v for v in vals if v is not None}


def check(text: str, f: TrackingFacts, extras: dict | None = None) -> list[Violation]:
    extras = extras or {}
    lits = allowed_literals(f, extras)
    eta_lit = fmt_date(f.carrier_eta) if f.carrier_eta else None
    out: list[Violation] = []

    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        if any(p.search(sent) for p in ETA_RES):
            if not _NEGATED_ETA.search(sent) and not (eta_lit and eta_lit in sent):
                out.append(Violation("invented_eta", sent.strip()))

    for pat, supported, why in _CLAIMS:
        m = pat.search(text)
        if m and not supported(f):
            out.append(Violation("unsupported_claim", f"'{m.group(0)}': {why}"))

    stripped = text
    for lit in sorted(lits, key=len, reverse=True):
        stripped = stripped.replace(lit, " ")
    for pat in DATE_RES:
        for m in pat.finditer(stripped):
            out.append(Violation("unsupported_date", m.group(0)))
        stripped = pat.sub(" ", stripped)
    ok = allowed_ints(f, extras)
    for m in re.finditer(r"\d+", stripped):
        if int(m.group(0)) not in ok:
            out.append(Violation("unsupported_number", m.group(0)))
    return out
