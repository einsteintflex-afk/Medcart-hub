"""Fincore payment gateway client.

IMPORTANT: Fincore's real API contract was not provided. This module defines the interface the rest of
the platform depends on (create charge, verify charge, refund, verify webhook signature). The `live`
implementation below follows common gateway conventions and MUST be reconciled with Fincore's actual
API documentation before go-live. `SimulatorGateway` exists only for development and tests and is
refused in production.
"""
import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx

from ..config import get_settings


@dataclass
class ChargeResult:
    txn_id: str
    status: str  # pending|succeeded|failed
    amount_pesewas: int
    currency: str
    reference: str
    checkout_url: str | None = None


class FincoreError(Exception):
    pass


def sign(secret: str, timestamp: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    s = get_settings()
    if not s.fincore_webhook_secret:
        return False  # fail closed
    try:
        if abs(time.time() - int(timestamp)) > s.fincore_webhook_tolerance_seconds:
            return False  # replay protection
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(sign(s.fincore_webhook_secret, timestamp, raw_body), signature or "")


class LiveGateway:
    def __init__(self):
        s = get_settings()
        self.client = httpx.Client(base_url=s.fincore_base_url, timeout=20,
                                   headers={"Authorization": f"Bearer {s.fincore_api_key}"})

    def create_charge(self, *, reference, amount_pesewas, currency, method, customer_phone=None, idempotency_key) -> ChargeResult:
        r = self.client.post("/v1/charges", headers={"Idempotency-Key": idempotency_key}, json={
            "reference": reference, "amount": amount_pesewas, "currency": currency,
            "method": method, "customer_phone": customer_phone})
        if r.status_code >= 400:
            raise FincoreError(r.text[:200])
        d = r.json()
        return ChargeResult(d["id"], d["status"], d["amount"], d["currency"], reference, d.get("checkout_url"))

    def get_charge(self, reference: str) -> ChargeResult:
        r = self.client.get(f"/v1/charges/{reference}")
        if r.status_code >= 400:
            raise FincoreError(r.text[:200])
        d = r.json()
        return ChargeResult(d["id"], d["status"], d["amount"], d["currency"], reference)

    def refund(self, *, txn_id: str, amount_pesewas: int, idempotency_key: str) -> None:
        r = self.client.post(f"/v1/charges/{txn_id}/refunds", headers={"Idempotency-Key": idempotency_key},
                             json={"amount": amount_pesewas})
        if r.status_code >= 400:
            raise FincoreError(r.text[:200])


class SimulatorGateway:
    """In-memory gateway for dev/tests. `settle()` plays the role of the customer approving on their phone."""
    charges: dict[str, ChargeResult] = {}

    def create_charge(self, *, reference, amount_pesewas, currency, method, customer_phone=None, idempotency_key):
        existing = self.charges.get(reference)
        if existing:
            return existing
        c = ChargeResult(f"sim_{reference}", "pending", amount_pesewas, currency, reference, f"/simulator/pay/{reference}")
        self.charges[reference] = c
        return c

    def get_charge(self, reference):
        if reference not in self.charges:
            raise FincoreError("unknown reference")
        return self.charges[reference]

    def settle(self, reference: str, status: str = "succeeded") -> None:
        self.charges[reference].status = status

    def refund(self, *, txn_id, amount_pesewas, idempotency_key) -> None:
        return None


_sim = SimulatorGateway()


def get_gateway():
    s = get_settings()
    if s.fincore_mode == "live":
        return LiveGateway()
    if s.env == "production":
        raise RuntimeError("Simulator gateway is not permitted in production")
    return _sim
