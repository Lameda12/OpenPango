"""Deterministic mock carrier API: rates, labels, and claim/inquiry case numbers."""
from __future__ import annotations

import hashlib


def _digits(seed: str, n: int) -> str:
    return str(int(hashlib.sha256(seed.encode()).hexdigest(), 16))[:n]


class MockCarrier:
    ADDRESS_CORRECTION_CENTS = 425

    def rate_cents(self, weight_g: int, country: str, service: str) -> int:
        base = 495 + (weight_g // 100) * 12
        if country.upper() not in ("US", "USA"):
            base += 1500
        if "express" in service.lower():
            base = int(base * 1.8)
        return base

    def new_tracking(self, seed: str) -> str:
        return "PGX" + _digits("trk" + seed, 12)

    def new_label_id(self, seed: str) -> str:
        return "LBL-" + _digits("lbl" + seed, 8)

    def open_case(self, kind: str, tracking_number: str) -> str:
        prefix = "CLM" if kind == "carrier_claim" else "INQ"
        return f"{prefix}-" + _digits(kind + tracking_number, 7)
