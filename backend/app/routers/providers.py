from datetime import datetime, timedelta

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import current_user, verified_email, verified_professional
from ..models import (Appointment, Availability, Contribution, ContribStatus, Credential, PROFESSIONAL_ROLES, ProviderProfile,
                      Role, User, VerificationStatus)
from ..services.audit import audit
from ..services.notifications import notify
from ..services.payments import has_active_subscription

router = APIRouter(tags=["providers"])


def _card(db: Session, u: User, p: ProviderProfile) -> dict:
    approved = db.scalars(select(Contribution.title).where(Contribution.author_id == u.id,
                                                           Contribution.status == ContribStatus.approved)).all()
    s = get_settings()
    return {"id": u.id, "name": u.full_name, "role": u.role.value, "specialty": p.specialty,
            "qualifications": p.qualifications, "photo_url": p.photo_url, "years_experience": p.years_experience,
            "languages": p.languages, "city": p.city, "rating": round(p.rating_avg, 1), "rating_count": p.rating_count,
            "registration_verified": p.status == VerificationStatus.approved,
            "fee_pesewas": s.doctor_consultation_pesewas if u.role == Role.doctor else s.pharmacist_consultation_pesewas,
            "approved_contributions": len(approved)}


@router.get("/providers")
def search(role: Literal["doctor", "pharmacist", "nurse"] | None = None, specialty: Annotated[str, Query(max_length=100)] | None = None,
           language: Annotated[str, Query(max_length=8)] | None = None, city: Annotated[str, Query(max_length=100)] | None = None,
           min_experience: int = Query(0, ge=0, le=80), max_fee_pesewas: int | None = Query(None, ge=0, le=10_000_000), min_rating: float = Query(0, ge=0, le=5),
           sort: Literal["experience", "rating"] = "experience", u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Only admin-verified providers are listed. Contributions are shown, never used to override verification."""
    q = (select(User, ProviderProfile).join(ProviderProfile, ProviderProfile.user_id == User.id)
         .where(ProviderProfile.status == VerificationStatus.approved, User.is_active,
                User.role.in_([Role.doctor, Role.pharmacist, Role.nurse])))
    if role:
        q = q.where(User.role == Role(role))
    if specialty:
        q = q.where(ProviderProfile.specialty.ilike(f"%{specialty}%"))
    if city:
        q = q.where(ProviderProfile.city.ilike(city))
    if min_experience:
        q = q.where(ProviderProfile.years_experience >= min_experience)
    if min_rating:
        q = q.where(ProviderProfile.rating_avg >= min_rating)
    rows = [(usr, p) for usr, p in db.execute(q)]
    if language:
        rows = [(a, b) for a, b in rows if language in (b.languages or [])]
    cards = [_card(db, a, b) for a, b in rows]
    if max_fee_pesewas is not None:
        cards = [c for c in cards if c["fee_pesewas"] <= max_fee_pesewas]
    cards.sort(key=lambda c: (-c["rating"], -c["years_experience"]) if sort == "rating" else (-c["years_experience"], -c["rating"]))
    return cards


@router.get("/providers/{pid}")
def detail(pid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    usr, p = db.get(User, pid), db.get(ProviderProfile, pid)
    if not usr or not p or p.status != VerificationStatus.approved:
        raise HTTPException(404)
    av = db.scalars(select(Availability).where(Availability.provider_id == pid)).all()
    return {**_card(db, usr, p), "bio": p.bio,
            "availability": [{"weekday": a.weekday, "start_minute": a.start_minute, "end_minute": a.end_minute} for a in av]}


class ProProfileIn(BaseModel):
    specialty: str | None = None
    qualifications: str | None = None
    bio: str | None = None
    photo_url: str | None = None
    years_experience: int | None = None
    languages: list[str] | None = None
    city: str | None = None


@router.patch("/providers/me/profile")
def update_pro_profile(body: ProProfileIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.role not in PROFESSIONAL_ROLES:
        raise HTTPException(403)
    p = db.get(ProviderProfile, u.id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    audit(db, u.id, "provider.profile_update", "provider_profile", u.id)
    db.commit()
    return {"ok": True}


@router.get("/providers/me/verification")
def my_verification(u: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(ProviderProfile, u.id)
    if not p:
        raise HTTPException(403)
    creds = db.scalars(select(Credential).where(Credential.provider_id == u.id)).all()
    return {"status": p.status.value, "note": p.review_note,
            "credentials": [{"kind": c.kind, "issuer": c.issuer, "number": c.number, "status": c.status.value} for c in creds]}


class Slot(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_minute >= self.end_minute:
            raise ValueError("start must be before end")
        return self


class AvailIn(BaseModel):
    slots: list[Slot] = Field(max_length=70)


@router.put("/providers/me/availability")
def set_availability(body: AvailIn, u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    for old in db.scalars(select(Availability).where(Availability.provider_id == u.id)):
        db.delete(old)
    for s in body.slots:
        db.add(Availability(provider_id=u.id, weekday=s.weekday, start_minute=s.start_minute, end_minute=s.end_minute))
    db.commit()
    return {"ok": True}


# ---- credentials (professionals upload licence/ID scans; only admins can read them)
@router.get("/providers/me/credentials")
def my_credentials(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.role not in PROFESSIONAL_ROLES:
        raise HTTPException(403)
    return [{"id": c.id, "kind": c.kind, "issuer": c.issuer, "number": c.number, "status": c.status.value, "has_document": bool(c.document_key)}
            for c in db.scalars(select(Credential).where(Credential.provider_id == u.id))]


class CredIn(BaseModel):
    kind: str
    issuer: str
    number: str
    document_key: str | None = None


@router.post("/providers/me/credentials", status_code=201)
def add_credential(body: CredIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from .files import require_owned
    if u.role not in PROFESSIONAL_ROLES:
        raise HTTPException(403)
    if db.scalar(select(Credential.id).where(Credential.issuer == body.issuer, Credential.number == body.number)):
        raise HTTPException(409, "This registration number is already on file")
    require_owned(db, body.document_key, u, {"credential"})
    c = Credential(provider_id=u.id, kind=body.kind, issuer=body.issuer, number=body.number, document_key=body.document_key)
    db.add(c)
    p = db.get(ProviderProfile, u.id)
    if p.status == VerificationStatus.rejected:
        p.status = VerificationStatus.pending  # resubmission re-opens review
    audit(db, u.id, "credential.add", "credential", None)
    db.commit()
    return {"id": c.id}


@router.post("/providers/me/credentials/{cid}/document")
def attach_credential_document(cid: int, key: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from .files import require_owned
    c = db.get(Credential, cid)
    if not c or c.provider_id != u.id:
        raise HTTPException(404)
    require_owned(db, key, u, {"credential"})
    c.document_key = key
    db.commit()
    return {"ok": True}


# ---- appointments
class ApptIn(BaseModel):
    provider_id: int | None = None
    facility_id: int | None = None
    starts_at: datetime
    duration_minutes: int = 30
    reason: str | None = None


def _within_availability(db, provider_id, start, minutes) -> bool:
    slots = db.scalars(select(Availability).where(Availability.provider_id == provider_id, Availability.weekday == start.weekday())).all()
    s = start.hour * 60 + start.minute
    return any(a.start_minute <= s and s + minutes <= a.end_minute for a in slots)


@router.post("/appointments", status_code=201)
def book(body: ApptIn, u: User = Depends(verified_email), db: Session = Depends(get_db)):
    if u.role != Role.patient:
        raise HTTPException(403)
    if not (body.provider_id or body.facility_id):
        raise HTTPException(422, "provider_id or facility_id required")
    if body.starts_at <= utcnow():
        raise HTTPException(422, "Appointment must be in the future")
    if not has_active_subscription(db, u.id, "patient"):
        raise HTTPException(402, "An active monthly subscription is required")
    if body.provider_id:
        p = db.get(ProviderProfile, body.provider_id)
        if not p or p.status != VerificationStatus.approved:
            raise HTTPException(404, "Provider not available")
        if not _within_availability(db, body.provider_id, body.starts_at, body.duration_minutes):
            raise HTTPException(409, "Outside provider availability")
        end = body.starts_at + timedelta(minutes=body.duration_minutes)
        for a in db.scalars(select(Appointment).where(Appointment.provider_id == body.provider_id, Appointment.status.in_(["pending", "confirmed"]),
                                                      Appointment.starts_at < end)):
            if a.starts_at + timedelta(minutes=a.duration_minutes) > body.starts_at:
                raise HTTPException(409, "Slot already taken")
    a = Appointment(patient_id=u.id, provider_id=body.provider_id, facility_id=body.facility_id, starts_at=body.starts_at,
                    duration_minutes=body.duration_minutes, reason=body.reason,
                    status="pending")
    db.add(a)
    db.flush()
    if body.provider_id:
        notify(db, body.provider_id, "appointment", "New appointment request", f"{body.starts_at:%Y-%m-%d %H:%M}")
    notify(db, u, "appointment", "Appointment requested", f"{body.starts_at:%Y-%m-%d %H:%M}")
    db.commit()
    return {"id": a.id, "status": a.status}


@router.get("/appointments")
def my_appts(u: User = Depends(current_user), db: Session = Depends(get_db)):
    col = Appointment.patient_id if u.role == Role.patient else Appointment.provider_id
    return [{"id": a.id, "starts_at": a.starts_at, "status": a.status, "provider_id": a.provider_id,
             "facility_id": a.facility_id, "reason": a.reason}
            for a in db.scalars(select(Appointment).where(col == u.id).order_by(Appointment.starts_at))]


class ApptUpdate(BaseModel):
    action: str  # confirm|cancel|reschedule
    starts_at: datetime | None = None


@router.patch("/appointments/{aid}")
def update_appt(aid: int, body: ApptUpdate, u: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Appointment, aid)
    if not a or u.id not in (a.patient_id, a.provider_id):
        raise HTTPException(404)
    if body.action == "confirm" and u.id == a.provider_id:
        a.status = "confirmed"
    elif body.action == "cancel":
        a.status = "cancelled"
    elif body.action == "reschedule" and body.starts_at and body.starts_at > utcnow():
        if a.provider_id and not _within_availability(db, a.provider_id, body.starts_at, a.duration_minutes):
            raise HTTPException(409, "Outside provider availability")
        a.starts_at, a.status, a.reminder_sent = body.starts_at, "pending", False
    else:
        raise HTTPException(422, "Invalid action")
    other = a.provider_id if u.id == a.patient_id else a.patient_id
    if other:
        notify(db, other, "appointment", f"Appointment {a.status}", f"{a.starts_at:%Y-%m-%d %H:%M}")
    db.commit()
    return {"status": a.status}
