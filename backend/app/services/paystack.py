"""Paystack gateway client (https://paystack.com/docs/api).

Conventions used (per Paystack docs): amounts are in the lowest currency unit (pesewas for GHS);
POST /transaction/initialize returns a hosted `authorization_url` supporting mobile money (MTN, Telecel, AT)
and cards; GET /transaction/verify/:reference is the source of truth; webhooks are signed with
HMAC-SHA512 of the RAW body using the secret key, sent in the `x-paystack-signature` header.
Paystack webhooks carry no timestamp, so replay safety comes from idempotency + server-side re-verification.

`SimulatorGateway` exists only for development and tests and is refused in production.
"""
import hashlib
import hmac
from dataclasses import dataclass

import httpx

from ..config import get_settings

_STATUS = {"success": "succeeded", "failed": "failed", "reversed": "failed"}  # everything else == still pending

CHANNELS = {"mtn_momo": ["mobile_money"], "telecel_cash": ["mobile_money"], "at_money": ["mobile_money"],
            "card": ["card"]}


@dataclass
class ChargeResult:
    txn_id: str
    status: str  # pending|succeeded|failed
    amount_pesewas: int
    currency: str
    reference: str
    checkout_url: str | None = None


class PaystackError(Exception):
    pass


def sign(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha512).hexdigest()


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = get_settings().paystack_secret_key
    if not secret or not signature:
        return False  # fail closed
    return hmac.compare_digest(sign(secret, raw_body), signature)


class LiveGateway:
    def __init__(self):
        s = get_settings()
        self.client = httpx.Client(base_url="https://api.paystack.co", timeout=20,
                                   headers={"Authorization": f"Bearer {s.paystack_secret_key}"})

    def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = self.client.request(method, path, **kw)
            d = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise PaystackError(f"network/parse error: {type(e).__name__}")
        if r.status_code >= 400 or not d.get("status"):
            raise PaystackError(str(d.get("message", "request failed"))[:200])
        return d["data"]

    def create_charge(self, *, reference, amount_pesewas, currency, method, email, customer_phone=None,
                      callback_url=None, metadata=None, idempotency_key=None) -> ChargeResult:
        # Paystack enforces unique `reference`, which is our idempotency anchor for initialization.
        d = self._call("POST", "/transaction/initialize", json={
            "email": email, "amount": amount_pesewas, "currency": currency, "reference": reference,
            "channels": CHANNELS.get(method, ["mobile_money", "card"]), "callback_url": callback_url,
            "metadata": metadata or {}})
        return ChargeResult(d["access_code"], "pending", amount_pesewas, currency, reference, d["authorization_url"])

    def get_charge(self, reference: str) -> ChargeResult:
        d = self._call("GET", f"/transaction/verify/{reference}")
        return ChargeResult(str(d["id"]), _STATUS.get(d["status"], "pending"), int(d["amount"]), d["currency"], reference)

    def refund(self, *, reference: str, amount_pesewas: int, **_) -> None:
        self._call("POST", "/refund", json={"transaction": reference, "amount": amount_pesewas})


class SimulatorGateway:
    """In-memory gateway for dev/tests. `settle()` plays the role of the customer approving on their phone."""
    charges: dict[str, ChargeResult] = {}
    refunds: list[str] = []

    def create_charge(self, *, reference, amount_pesewas, currency, method, email, customer_phone=None,
                      callback_url=None, metadata=None, idempotency_key=None):
        existing = self.charges.get(reference)
        if existing:
            return existing
        c = ChargeResult(f"sim_{reference}", "pending", amount_pesewas, currency, reference, f"/simulator/pay/{reference}")
        self.charges[reference] = c
        return c

    def get_charge(self, reference):
        if reference not in self.charges:
            raise PaystackError("Transaction reference not found")
        return self.charges[reference]

    def settle(self, reference: str, status: str = "succeeded") -> None:
        self.charges[reference].status = status

    def refund(self, *, reference, amount_pesewas, **_) -> None:
        self.refunds.append(reference)


_sim = SimulatorGateway()


def get_gateway():
    s = get_settings()
    if s.payment_mode == "live":
        if not s.paystack_secret_key:
            raise RuntimeError("MEDCART_PAYSTACK_SECRET_KEY is not set")
        return LiveGateway()
    if s.env == "production":
        raise RuntimeError("Simulator gateway is not permitted in production")
    return _sim
