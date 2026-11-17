import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import current_user, verified_professional
from ..models import (AccessGrant, ConsultMessage, Consultation, ConsultStatus, Prescription, ProviderProfile, Rating,
                      Referral, Role, User)
from ..services.audit import audit
from ..services.notifications import notify
from ..services.payments import has_active_subscription

router = APIRouter(prefix="/consultations", tags=["consultations"])


class ConsultIn(BaseModel):
    provider_id: int
    channel: str  # text|audio|video
    concern: str
    urgent: bool = False
    scheduled_for: datetime | None = None
    share_records: bool = False
    language: str = "en"
    interpretation_enabled: bool = False


def _can_view(c: Consultation, u: User) -> bool:
    return u.id in (c.patient_id, c.provider_id) or u.role == Role.admin


@router.post("", status_code=201)
def request_consult(body: ConsultIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    s = get_settings()
    if u.role != Role.patient:
        raise HTTPException(403, "Patients only")
    if body.channel not in ("text", "audio", "video"):
        raise HTTPException(422, "channel must be text, audio or video")
    if not has_active_subscription(db, u.id, "patient"):
        raise HTTPException(402, "An active monthly subscription is required")
    prov = db.get(User, body.provider_id)
    pp = db.get(ProviderProfile, body.provider_id)
    if not prov or not pp or pp.status.value != "approved" or prov.role not in (Role.doctor, Role.pharmacist):
        raise HTTPException(404, "Provider not available")
    # Doctor consultations are ALWAYS paid separately; subscription never covers them.
    fee = s.doctor_consultation_pesewas if prov.role == Role.doctor else s.pharmacist_consultation_pesewas
    c = Consultation(patient_id=u.id, provider_id=prov.id, provider_role=prov.role, channel=body.channel,
                     urgent=body.urgent, scheduled_for=body.scheduled_for, concern=body.concern, fee_pesewas=fee,
                     share_records=body.share_records, language=body.language,
                     interpretation_enabled=body.interpretation_enabled, room_id=uuid.uuid4().hex,
                     status=ConsultStatus.awaiting_payment if fee > 0 else ConsultStatus.requested)
    db.add(c)
    db.flush()
    if body.share_records:  # explicit patient consent captured at booking, time-limited
        db.add(AccessGrant(patient_id=u.id, provider_id=prov.id, categories=["*"], expires_at=None))
    if fee == 0:
        notify(db, prov.id, "consult_request", "New consultation request", f"Consultation #{c.id} awaits your response.")
    audit(db, u.id, "consult.create", "consultation", c.id, patient_id=u.id)
    db.commit()
    return {"id": c.id, "status": c.status.value, "fee_pesewas": fee, "next": "pay" if fee else "wait_for_provider"}


@router.get("")
def my_consults(u: User = Depends(current_user), db: Session = Depends(get_db)):
    col = Consultation.patient_id if u.role == Role.patient else Consultation.provider_id
    rows = db.scalars(select(Consultation).where(col == u.id).order_by(Consultation.id.desc())).all()
    return [{"id": c.id, "status": c.status.value, "channel": c.channel, "urgent": c.urgent, "provider_id": c.provider_id,
             "patient_id": c.patient_id, "scheduled_for": c.scheduled_for, "fee_pesewas": c.fee_pesewas} for c in rows]


class DecisionIn(BaseModel):
    accept: bool
    note: str | None = None


@router.post("/{cid}/decision")
def decide(cid: int, body: DecisionIn, u: User = Depends(verified_professional(Role.doctor, Role.pharmacist)),
           db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or c.provider_id != u.id or c.status != ConsultStatus.requested:
        raise HTTPException(404, "No pending request")
    c.status = ConsultStatus.accepted if body.accept else ConsultStatus.rejected
    if not body.accept and c.fee_pesewas:  # paid but rejected -> admin/finance refunds via payments router
        notify(db, c.patient_id, "consult_rejected", "Consultation declined", "Your payment will be refunded.")
    elif body.accept:
        notify(db, c.patient_id, "consult_accepted", "Consultation accepted", f"Consultation #{c.id} was accepted.")
    audit(db, u.id, "consult.decision", "consultation", c.id, patient_id=c.patient_id, accept=body.accept)
    db.commit()
    return {"status": c.status.value}


class MessageIn(BaseModel):
    body: str
    language: str = "en"
    machine_translated: bool = False
    attachment_key: str | None = None


@router.post("/{cid}/messages", status_code=201)
def send_message(cid: int, body: MessageIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or u.id not in (c.patient_id, c.provider_id):
        raise HTTPException(404)
    if c.status not in (ConsultStatus.accepted, ConsultStatus.in_progress):
        raise HTTPException(409, "Consultation is not open for messaging")
    c.status = ConsultStatus.in_progress
    m = ConsultMessage(consultation_id=cid, sender_id=u.id, body=body.body, language=body.language,
                       machine_translated=body.machine_translated, attachment_key=body.attachment_key)
    db.add(m)
    notify(db, c.provider_id if u.id == c.patient_id else c.patient_id, "consult_message", "New message", f"Consultation #{cid}", external=False)
    db.commit()
    return {"id": m.id}


@router.get("/{cid}/messages")
def messages(cid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or not _can_view(c, u):
        raise HTTPException(404)
    audit(db, u.id, "consult.read_messages", "consultation", cid, patient_id=c.patient_id)
    db.commit()
    rows = db.scalars(select(ConsultMessage).where(ConsultMessage.consultation_id == cid).order_by(ConsultMessage.id)).all()
    return [{"id": m.id, "sender_id": m.sender_id, "body": m.body, "language": m.language,
             "machine_translated": m.machine_translated,
             "translation_notice": "Automatically translated; confirm critical information with your clinician."
             if m.machine_translated else None, "created_at": m.created_at} for m in rows]


class CompleteIn(BaseModel):
    clinical_note: str
    recommendation: str
    follow_up_at: datetime | None = None


@router.post("/{cid}/complete")
def complete(cid: int, body: CompleteIn, u: User = Depends(verified_professional(Role.doctor, Role.pharmacist)),
             db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or c.provider_id != u.id or c.status not in (ConsultStatus.accepted, ConsultStatus.in_progress):
        raise HTTPException(404)
    c.clinical_note, c.recommendation = body.clinical_note, body.recommendation
    c.status, c.completed_at = ConsultStatus.completed, utcnow()
    if body.follow_up_at:
        from ..models import Appointment
        db.add(Appointment(patient_id=c.patient_id, provider_id=u.id, starts_at=body.follow_up_at, status="confirmed",
                           reason="Follow-up", consultation_id=c.id))
        notify(db, c.patient_id, "follow_up", "Follow-up scheduled", f"{body.follow_up_at:%Y-%m-%d %H:%M}")
    audit(db, u.id, "consult.complete", "consultation", c.id, patient_id=c.patient_id)
    db.commit()
    return {"status": c.status.value}


class RxIn(BaseModel):
    items: list[dict]


@router.post("/{cid}/prescriptions", status_code=201)
def prescribe(cid: int, body: RxIn, u: User = Depends(verified_professional(Role.doctor)), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    pp = db.get(ProviderProfile, u.id)
    if not c or c.provider_id != u.id:
        raise HTTPException(404)
    if not pp.can_prescribe:
        raise HTTPException(403, "You are not authorised to prescribe on this platform")
    if not body.items or any(not {"drug", "dose", "frequency", "duration"} <= i.keys() for i in body.items):
        raise HTTPException(422, "Each item needs drug, dose, frequency, duration")
    rx = Prescription(consultation_id=cid, patient_id=c.patient_id, prescriber_id=u.id, items=body.items)
    db.add(rx)
    notify(db, c.patient_id, "prescription", "New prescription", f"Consultation #{cid}")
    audit(db, u.id, "prescription.create", "prescription", cid, patient_id=c.patient_id)
    db.commit()
    return {"id": rx.id}


class ReferralIn(BaseModel):
    to_provider_id: int | None = None
    to_facility_id: int | None = None
    reason: str


@router.post("/{cid}/referrals", status_code=201)
def refer(cid: int, body: ReferralIn, u: User = Depends(verified_professional(Role.doctor, Role.pharmacist, Role.nurse)),
          db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or c.provider_id != u.id:
        raise HTTPException(404)
    db.add(Referral(consultation_id=cid, from_provider_id=u.id, to_provider_id=body.to_provider_id,
                    to_facility_id=body.to_facility_id, reason=body.reason))
    notify(db, c.patient_id, "referral", "You have been referred", body.reason[:140])
    db.commit()
    return {"ok": True}


class RateIn(BaseModel):
    stars: int
    comment: str | None = None


@router.post("/{cid}/rating", status_code=201)
def rate(cid: int, body: RateIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or c.patient_id != u.id or c.status != ConsultStatus.completed:
        raise HTTPException(404)
    if not 1 <= body.stars <= 5 or db.scalar(select(Rating.id).where(Rating.consultation_id == cid)):
        raise HTTPException(422, "Invalid or duplicate rating")
    db.add(Rating(consultation_id=cid, patient_id=u.id, provider_id=c.provider_id, stars=body.stars, comment=body.comment))
    pp = db.get(ProviderProfile, c.provider_id)
    pp.rating_avg = (pp.rating_avg * pp.rating_count + body.stars) / (pp.rating_count + 1)
    pp.rating_count += 1
    db.commit()
    return {"ok": True}
