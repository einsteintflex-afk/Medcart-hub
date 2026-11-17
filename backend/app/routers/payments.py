import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_admin, verified_email
from ..models import (Consultation, ConsultStatus, Payment, PROFESSIONAL_ROLES, Role, Settlement, Subscription, User, WebhookEvent)
from ..services import payments as svc
from ..services.paystack import PaystackError, verify_webhook_signature

router = APIRouter(prefix="/payments", tags=["payments"])


class CheckoutIn(BaseModel):
    purpose: str  # patient_subscription | consultation | pro_subscription
    method: str
    consultation_id: int | None = None


@router.post("/checkout", status_code=201)
def checkout(body: CheckoutIn, idempotency_key: str = Header(min_length=8, max_length=80),
             u: User = Depends(verified_email), db: Session = Depends(get_db)):
    consult = None
    if body.purpose == "patient_subscription" and u.role != Role.patient:
        raise HTTPException(403, "Patients only")
    if body.purpose == "pro_subscription" and u.role not in PROFESSIONAL_ROLES:
        raise HTTPException(403, "Professionals only")
    if body.purpose == "consultation":
        consult = db.get(Consultation, body.consultation_id or 0)
        if not consult or consult.patient_id != u.id or consult.status != ConsultStatus.awaiting_payment:
            raise HTTPException(404, "No consultation awaiting payment")
    elif body.purpose not in ("patient_subscription", "pro_subscription"):
        raise HTTPException(422, "Unknown purpose")
    try:
        p, url = svc.create_payment(db, u, body.purpose, body.method, idempotency_key, consult)
    except (ValueError, PermissionError) as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"reference": p.reference, "amount_pesewas": p.amount_pesewas, "currency": p.currency,
            "status": p.status.value, "checkout_url": url or p.checkout_url}


@router.post("/dev/simulate/{reference}")
def dev_simulate(reference: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """DEV ONLY: stands in for the customer approving on Paystack. Doesn't exist in live mode or production."""
    from ..config import get_settings
    from ..services.paystack import _sim
    s = get_settings()
    if s.payment_mode != "simulator" or s.env == "production":
        raise HTTPException(404)
    p = db.scalar(select(Payment).where(Payment.reference == reference, Payment.user_id == u.id))
    if not p:
        raise HTTPException(404)
    _sim.settle(reference)
    svc.fulfil_if_verified(db, reference)
    db.commit()
    return {"status": "succeeded"}


@router.post("/{reference}/verify")
def verify(reference: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Client may ask the server to re-check; the SERVER asks Paystack. Client claims are never trusted."""
    p = db.scalar(select(Payment).where(Payment.reference == reference))
    if not p or (p.user_id != u.id and u.role != Role.admin):
        raise HTTPException(404, "Not found")
    try:
        p = svc.fulfil_if_verified(db, reference)
    except PaystackError:
        raise HTTPException(502, "Payment provider unavailable")
    db.commit()
    return {"reference": p.reference, "status": p.status.value}


@router.post("/webhooks/paystack")
async def paystack_webhook(request: Request, x_paystack_signature: str = Header(""), db: Session = Depends(get_db)):
    raw = await request.body()  # signature is over the raw bytes, so read them before any parsing
    if not verify_webhook_signature(raw, x_paystack_signature):
        raise HTTPException(401, "Bad signature")
    try:
        event = json.loads(raw)
        etype, data = event["event"], event["data"]
        ref = data.get("reference")
        # Paystack sends no event id: dedupe on event type + transaction id (fallback: reference).
        event_id = f"{etype}:{data.get('id') or ref}"[:80]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, "Malformed event")
    try:  # idempotency: duplicate deliveries are acknowledged and ignored
        with db.begin_nested():
            db.add(WebhookEvent(event_id=event_id, event_type=etype[:40], payload=event))
            db.flush()
    except IntegrityError:
        return {"status": "duplicate"}
    if etype in ("charge.success", "charge.failed") and ref:
        try:
            svc.fulfil_if_verified(db, ref)  # re-verifies via Paystack's verify API; the body is only a trigger
        except LookupError:
            pass  # not one of our payments
        except PaystackError:
            db.rollback()
            raise HTTPException(503, "retry later")  # non-2xx makes Paystack redeliver
    db.commit()
    return {"status": "ok"}


@router.get("/history")
def history(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).where(Payment.user_id == u.id).order_by(Payment.id.desc())).all()
    return [{"reference": p.reference, "purpose": p.purpose, "amount_pesewas": p.amount_pesewas, "currency": p.currency,
             "status": p.status.value, "created_at": p.created_at} for p in rows]


@router.get("/subscription")
def subscription(u: User = Depends(current_user), db: Session = Depends(get_db)):
    plan = "patient" if u.role == Role.patient else "professional"
    sub = db.scalar(select(Subscription).where(Subscription.user_id == u.id, Subscription.plan == plan)
                    .order_by(Subscription.expires_at.desc()))
    return {"plan": plan, "active": svc.has_active_subscription(db, u.id, plan),
            "expires_at": sub.expires_at if sub else None,
            "note": "The subscription does not include doctor consultations, which are paid separately."
            if plan == "patient" else None}


@router.get("/earnings")
def earnings(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Settlement).where(Settlement.provider_id == u.id).order_by(Settlement.id.desc())).all()
    return {"pending_net_pesewas": sum(r.net_pesewas for r in rows if r.status == "pending"),
            "paid_net_pesewas": sum(r.net_pesewas for r in rows if r.status == "paid"),
            "items": [{"payment_id": r.payment_id, "gross": r.gross_pesewas, "commission": r.commission_pesewas,
                       "net": r.net_pesewas, "status": r.status} for r in rows]}


@router.post("/admin/{payment_id}/refund")
def refund(payment_id: int, reason: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404)
    try:
        svc.refund_payment(db, p, admin.id, reason)
    except (ValueError, PaystackError) as e:
        raise HTTPException(400, str(e))
    db.commit()
    return {"ok": True}


@router.get("/admin/reconciliation")
def reconciliation(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return svc.reconciliation(db)
