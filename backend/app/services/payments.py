"""Payment creation, verification and fulfilment.

Services are fulfilled ONLY from `fulfil_if_verified`, which re-queries Paystack server-side and checks
amount/currency/status. Frontend 'payment done' signals and webhook bodies alone never unlock anything.
Fulfilment is idempotent (Payment.fulfilled_at) and race-safe (row lock on PostgreSQL).
"""
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import (Consultation, ConsultStatus, Payment, PaymentStatus, Refund, Settlement, Subscription, User)
from .audit import audit
from .paystack import PaystackError, get_gateway
from .notifications import notify

METHODS = {"mtn_momo", "telecel_cash", "at_money", "card"}


def price_for(purpose: str) -> int:
    s = get_settings()
    return {"patient_subscription": s.patient_subscription_pesewas,
            "consultation": s.doctor_consultation_pesewas,
            "pro_subscription": s.professional_subscription_pesewas}[purpose]


def create_payment(db: Session, user: User, purpose: str, method: str, idempotency_key: str,
                   consultation: Consultation | None = None) -> tuple[Payment, str | None]:
    if method not in METHODS:
        raise ValueError("Unsupported payment method")
    existing = db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
    if existing:
        if existing.user_id != user.id:
            raise PermissionError("idempotency key conflict")
        return existing, None
    # Amount is ALWAYS computed server-side.
    amount = consultation.fee_pesewas if consultation else price_for(purpose)
    p = Payment(reference=f"MC-{uuid.uuid4().hex[:20]}", idempotency_key=idempotency_key, user_id=user.id,
                purpose=purpose, consultation_id=consultation.id if consultation else None,
                amount_pesewas=amount, currency=get_settings().currency, method=method)
    db.add(p)
    db.flush()
    try:
        ch = get_gateway().create_charge(reference=p.reference, amount_pesewas=amount, currency=p.currency,
                                         method=method, email=user.email, customer_phone=user.phone,
                                         callback_url=get_settings().payment_callback_url,
                                         metadata={"payment_id": p.id, "purpose": purpose}, idempotency_key=idempotency_key)
    except PaystackError as e:
        p.status, p.failure_reason = PaymentStatus.failed, str(e)[:200]
        return p, None
    p.provider_txn_id = ch.txn_id
    audit(db, user.id, "payment.create", "payment", p.id, purpose=purpose, amount=amount)
    return p, ch.checkout_url


def fulfil_if_verified(db: Session, reference: str) -> Payment:
    p = db.scalar(select(Payment).where(Payment.reference == reference).with_for_update())
    if p is None:
        raise LookupError("unknown payment")
    if p.fulfilled_at or p.status in (PaymentStatus.refunded,):
        return p  # idempotent
    ch = get_gateway().get_charge(reference)  # authoritative server-to-server check
    if ch.amount_pesewas != p.amount_pesewas or ch.currency != p.currency:
        p.status, p.failure_reason = PaymentStatus.failed, "amount_mismatch"
        audit(db, None, "payment.fraud_flag", "payment", p.id, reason="amount_mismatch")
        return p
    if ch.status == "failed":
        p.status, p.failure_reason = PaymentStatus.failed, "declined"
        notify(db, p.user_id, "payment_failed", "Payment failed", "Your payment did not go through. Please try again.")
        return p
    if ch.status != "succeeded":
        return p
    p.status, p.fulfilled_at, p.provider_txn_id = PaymentStatus.succeeded, utcnow(), ch.txn_id
    _fulfil(db, p)
    notify(db, p.user_id, "payment_confirmed", "Payment confirmed",
           f"We received GH₵{p.amount_pesewas / 100:.2f}. Receipt: {p.reference}")
    audit(db, None, "payment.fulfil", "payment", p.id)
    return p


def _extend(db: Session, user_id: int, plan: str, source: str, payment_id: int) -> None:
    now = utcnow()
    latest = db.scalar(select(func.max(Subscription.expires_at)).where(
        Subscription.user_id == user_id, Subscription.plan == plan))
    start = max(latest, now) if latest else now
    db.add(Subscription(user_id=user_id, plan=plan, starts_at=start, expires_at=start + timedelta(days=30),
                        source=source, payment_id=payment_id))


def _fulfil(db: Session, p: Payment) -> None:
    s = get_settings()
    if p.purpose == "patient_subscription":
        _extend(db, p.user_id, "patient", "payment", p.id)
    elif p.purpose == "pro_subscription":
        _extend(db, p.user_id, "professional", "payment", p.id)
    elif p.purpose == "consultation":
        c = db.get(Consultation, p.consultation_id)
        if c and c.status == ConsultStatus.awaiting_payment:
            c.status = ConsultStatus.requested
            notify(db, c.provider_id, "consult_request", "New consultation request", f"Consultation #{c.id} is paid and awaiting you.")
        commission = p.amount_pesewas * s.platform_commission_bps // 10000
        db.add(Settlement(provider_id=c.provider_id, payment_id=p.id, gross_pesewas=p.amount_pesewas,
                          commission_pesewas=commission, net_pesewas=p.amount_pesewas - commission))


def has_active_subscription(db: Session, user_id: int, plan: str = "patient") -> bool:
    return db.scalar(select(Subscription.id).where(Subscription.user_id == user_id, Subscription.plan == plan,
                                                  Subscription.expires_at > utcnow()).limit(1)) is not None


def refund_payment(db: Session, p: Payment, actor_id: int, reason: str) -> Refund:
    if p.status != PaymentStatus.succeeded:
        raise ValueError("Only succeeded payments can be refunded")
    get_gateway().refund(reference=p.reference, amount_pesewas=p.amount_pesewas)
    p.status = PaymentStatus.refunded
    r = Refund(payment_id=p.id, amount_pesewas=p.amount_pesewas, reason=reason, actor_id=actor_id)
    db.add(r)
    st = db.scalar(select(Settlement).where(Settlement.payment_id == p.id))
    if st:
        st.status = "reversed"
    if p.consultation_id:
        c = db.get(Consultation, p.consultation_id)
        if c:
            c.status = ConsultStatus.refunded
    sub = db.scalar(select(Subscription).where(Subscription.payment_id == p.id))
    if sub:
        sub.expires_at = utcnow()  # end the entitlement
    notify(db, p.user_id, "refund", "Refund issued", f"GH₵{p.amount_pesewas / 100:.2f} refunded.")
    audit(db, actor_id, "payment.refund", "payment", p.id, reason=reason)
    return r


def reconciliation(db: Session) -> dict:
    """Compare our ledger with Paystack for pending/succeeded payments; report discrepancies."""
    gw = get_gateway()
    issues = []
    for p in db.scalars(select(Payment).where(Payment.status.in_([PaymentStatus.pending, PaymentStatus.succeeded]))):
        try:
            ch = gw.get_charge(p.reference)
        except PaystackError:
            issues.append({"reference": p.reference, "issue": "missing_at_paystack"})
            continue
        if ch.status == "succeeded" and p.status == PaymentStatus.pending:
            issues.append({"reference": p.reference, "issue": "paid_at_paystack_not_fulfilled"})
        if ch.status != "succeeded" and p.status == PaymentStatus.succeeded:
            issues.append({"reference": p.reference, "issue": "fulfilled_but_not_paid_at_paystack"})
        if ch.amount_pesewas != p.amount_pesewas:
            issues.append({"reference": p.reference, "issue": "amount_mismatch"})
    gross = db.scalar(select(func.coalesce(func.sum(Payment.amount_pesewas), 0)).where(Payment.status == PaymentStatus.succeeded))
    return {"succeeded_gross_pesewas": gross, "discrepancies": issues}
