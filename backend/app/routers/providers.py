from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import current_user, verified_professional
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
def search(role: str | None = None, specialty: str | None = None, language: str | None = None, city: str | None = None,
           min_experience: int = 0, max_fee_pesewas: int | None = None, min_rating: float = 0,
           sort: str = "experience", u: User = Depends(current_user), db: Session = Depends(get_db)):
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


class AvailIn(BaseModel):
    slots: list[dict]  # [{weekday,start_minute,end_minute}]


@router.put("/providers/me/availability")
def set_availability(body: AvailIn, u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    for s in body.slots:
        if not (0 <= s["weekday"] <= 6 and 0 <= s["start_minute"] < s["end_minute"] <= 1440):
            raise HTTPException(422, "invalid slot")
    for old in db.scalars(select(Availability).where(Availability.provider_id == u.id)):
        db.delete(old)
    for s in body.slots:
        db.add(Availability(provider_id=u.id, **{k: s[k] for k in ("weekday", "start_minute", "end_minute")}))
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
def book(body: ApptIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
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
