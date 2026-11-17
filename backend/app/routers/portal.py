"""Dashboard-oriented endpoints for patient, professional, facility-admin and admin portals."""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import current_user, require_admin, require_roles, verified_professional
from ..models import (AccessGrant, Appointment, Availability, Complaint, Consultation, ConsultStatus, Contribution, ContribStatus,
                      CreditEntry, Facility, LabRequest, Language, Medication, Notification, Payment, PROFESSIONAL_ROLES, Prescription,
                      ProviderProfile, Role, Settlement, Subscription, User, VitalReading)
from ..services import credits, reminders
from ..services.audit import audit
from ..services.payments import has_active_subscription

router = APIRouter(tags=["portal"])


# ------------------------------------------------------------------ patient
@router.get("/patients/me/overview")
def patient_overview(u: User = Depends(require_roles(Role.patient)), db: Session = Depends(get_db)):
    sub = db.scalar(select(func.max(Subscription.expires_at)).where(Subscription.user_id == u.id, Subscription.plan == "patient"))
    latest = {}
    for v in db.scalars(select(VitalReading).where(VitalReading.patient_id == u.id).order_by(VitalReading.measured_at.desc()).limit(50)):
        latest.setdefault(v.kind, {"value": v.value, "value2": v.value2, "unit": v.unit, "abnormal": v.abnormal, "at": v.measured_at})
    appts = db.scalars(select(Appointment).where(Appointment.patient_id == u.id, Appointment.starts_at > utcnow(),
                                                 Appointment.status.in_(["pending", "confirmed"])).order_by(Appointment.starts_at).limit(5)).all()
    return {"subscription_active": bool(sub and sub > utcnow()), "subscription_expires_at": sub,
            "upcoming_appointments": [{"id": a.id, "starts_at": a.starts_at, "status": a.status} for a in appts],
            "active_medications": db.scalar(select(func.count(Medication.id)).where(Medication.patient_id == u.id, Medication.active)),
            "unread_notifications": db.scalar(select(func.count(Notification.id)).where(Notification.user_id == u.id, Notification.read.is_(False))),
            "open_consultations": db.scalar(select(func.count(Consultation.id)).where(Consultation.patient_id == u.id,
                                            Consultation.status.in_([ConsultStatus.requested, ConsultStatus.accepted, ConsultStatus.in_progress]))),
            "new_lab_results": db.scalar(select(func.count(LabRequest.id)).where(LabRequest.patient_id == u.id, LabRequest.status == "resulted")),
            "latest_vitals": latest}


class MedUpdate(BaseModel):
    active: bool | None = None
    remaining_doses: int | None = None
    times_of_day: list[str] | None = None
    dose: str | None = None


@router.patch("/medications/{mid}")
def update_med(mid: int, body: MedUpdate, u: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.get(Medication, mid)
    if not m or m.patient_id != u.id:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(m, k, v)
    db.commit()
    return {"ok": True}


@router.get("/access-grants")
def my_grants(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(AccessGrant, User).join(User, User.id == AccessGrant.provider_id)
                      .where(AccessGrant.patient_id == u.id, AccessGrant.revoked_at.is_(None))).all()
    return [{"id": g.id, "provider_id": p.id, "provider_name": p.full_name, "categories": g.categories, "expires_at": g.expires_at} for g, p in rows]


@router.get("/consultations/{cid}")
def consult_detail(cid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or (u.id not in (c.patient_id, c.provider_id) and u.role != Role.admin):
        raise HTTPException(404)
    other = db.get(User, c.provider_id if u.id == c.patient_id else c.patient_id)
    rx = db.scalars(select(Prescription).where(Prescription.consultation_id == cid)).all()
    audit(db, u.id, "consult.read", "consultation", cid, patient_id=c.patient_id)
    db.commit()
    return {"id": c.id, "status": c.status.value, "channel": c.channel, "urgent": c.urgent, "concern": c.concern,
            "scheduled_for": c.scheduled_for, "language": c.language, "interpretation_enabled": c.interpretation_enabled,
            "room_id": c.room_id if c.status in (ConsultStatus.accepted, ConsultStatus.in_progress) else None,
            "clinical_note": c.clinical_note, "recommendation": c.recommendation, "fee_pesewas": c.fee_pesewas,
            "patient_id": c.patient_id, "provider_id": c.provider_id, "other_party": other.full_name if other else None,
            "prescriptions": [{"id": r.id, "items": r.items, "created_at": r.created_at} for r in rx]}


class ComplaintIn(BaseModel):
    body: str
    about_user_id: int | None = None


@router.post("/complaints", status_code=201)
def complain(body: ComplaintIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = Complaint(user_id=u.id, about_user_id=body.about_user_id, body=body.body)
    db.add(c)
    db.commit()
    return {"id": c.id}


@router.post("/notifications/read-all")
def read_all(u: User = Depends(current_user), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.user_id == u.id, Notification.read.is_(False))):
        n.read = True
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ professionals
@router.get("/pro/overview")
def pro_overview(u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    cons = lambda *st: db.scalar(select(func.count(Consultation.id)).where(Consultation.provider_id == u.id, Consultation.status.in_(st)))
    st = db.scalars(select(Settlement).where(Settlement.provider_id == u.id)).all()
    return {"pending_requests": cons(ConsultStatus.requested), "active_consultations": cons(ConsultStatus.accepted, ConsultStatus.in_progress),
            "completed": cons(ConsultStatus.completed),
            "todays_appointments": db.scalar(select(func.count(Appointment.id)).where(
                Appointment.provider_id == u.id, Appointment.status == "confirmed", Appointment.starts_at >= utcnow(),
                Appointment.starts_at < utcnow() + timedelta(days=1))),
            "pending_earnings_pesewas": sum(s.net_pesewas for s in st if s.status == "pending"),
            "paid_earnings_pesewas": sum(s.net_pesewas for s in st if s.status == "paid"),
            "credit_balance_units": credits.balance_tenths(db, u.id) / 10,
            "unread_notifications": db.scalar(select(func.count(Notification.id)).where(Notification.user_id == u.id, Notification.read.is_(False))),
            "subscription_active": has_active_subscription(db, u.id, "professional"),
            "lab_queue": db.scalar(select(func.count(LabRequest.id)).where(LabRequest.status != "resulted")) if u.role == Role.lab else None}


@router.get("/providers/me/profile")
def my_pro_profile(u: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(ProviderProfile, u.id)
    if not p:
        raise HTTPException(403)
    av = db.scalars(select(Availability).where(Availability.provider_id == u.id)).all()
    return {"name": u.full_name, "role": u.role.value, "status": p.status.value, "specialty": p.specialty, "qualifications": p.qualifications,
            "bio": p.bio, "photo_url": p.photo_url, "years_experience": p.years_experience, "languages": p.languages, "city": p.city,
            "can_prescribe": p.can_prescribe, "rating": p.rating_avg, "rating_count": p.rating_count,
            "availability": [{"weekday": a.weekday, "start_minute": a.start_minute, "end_minute": a.end_minute} for a in av]}


@router.get("/pro/patients")
def pro_patients(u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    """Patients this professional has treated or has been granted access to."""
    ids = set(db.scalars(select(Consultation.patient_id).where(Consultation.provider_id == u.id)))
    ids |= set(db.scalars(select(AccessGrant.patient_id).where(AccessGrant.provider_id == u.id, AccessGrant.revoked_at.is_(None),
                                                               or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > utcnow()))))
    return [{"id": p.id, "name": p.full_name} for p in db.scalars(select(User).where(User.id.in_(ids)))] if ids else []


@router.get("/patients/{pid}/summary")
def patient_summary(pid: int, u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    """Allergies/current medications are shown only to a professional with an active relationship (grant)."""
    from .health import _any_grant
    if not _any_grant(db, pid, u):
        raise HTTPException(403, "The patient has not shared their record with you")
    pt = db.get(User, pid)
    audit(db, u.id, "patient.summary_read", "patient", pid, patient_id=pid)
    db.commit()
    pp = pt.patient
    return {"name": pt.full_name, "sex": pp.sex, "date_of_birth": pp.date_of_birth, "allergies": pp.allergies,
            "current_medications": pp.current_medications, "medical_history": pp.medical_history}


# ------------------------------------------------------------------ facility admin
@router.post("/facilities/mine", status_code=201)
def create_my_facility(body: dict, u: User = Depends(require_roles(Role.facility_admin)), db: Session = Depends(get_db)):
    allowed = {"name", "kind", "address", "city", "region", "country", "phone", "latitude", "longitude", "services", "specialties", "hours", "has_emergency"}
    if not {"name", "kind", "address"} <= body.keys():
        raise HTTPException(422, "name, kind, address required")
    f = Facility(**{k: v for k, v in body.items() if k in allowed}, admin_user_id=u.id, verified=False)  # hidden until admin verifies
    db.add(f)
    db.commit()
    return {"id": f.id, "verified": False}


@router.get("/facilities/mine")
def my_facilities(u: User = Depends(require_roles(Role.facility_admin)), db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name, "kind": f.kind, "address": f.address, "verified": f.verified, "services": f.services,
             "specialties": f.specialties, "hours": f.hours, "phone": f.phone, "has_emergency": f.has_emergency}
            for f in db.scalars(select(Facility).where(Facility.admin_user_id == u.id))]


@router.patch("/facilities/mine/{fid}")
def update_my_facility(fid: int, body: dict, u: User = Depends(require_roles(Role.facility_admin)), db: Session = Depends(get_db)):
    f = db.get(Facility, fid)
    if not f or f.admin_user_id != u.id:
        raise HTTPException(404)
    for k in {"name", "address", "phone", "services", "specialties", "hours", "has_emergency", "city", "region"} & body.keys():
        setattr(f, k, body[k])
    audit(db, u.id, "facility.update", "facility", fid)
    db.commit()
    return {"ok": True}


@router.get("/facilities/mine/appointments")
def facility_appointments(u: User = Depends(require_roles(Role.facility_admin)), db: Session = Depends(get_db)):
    ids = list(db.scalars(select(Facility.id).where(Facility.admin_user_id == u.id)))
    rows = db.scalars(select(Appointment).where(Appointment.facility_id.in_(ids)).order_by(Appointment.starts_at)).all() if ids else []
    return [{"id": a.id, "facility_id": a.facility_id, "starts_at": a.starts_at, "status": a.status, "reason": a.reason, "patient_id": a.patient_id} for a in rows]


@router.patch("/facilities/mine/appointments/{aid}")
def facility_appt_action(aid: int, action: str, u: User = Depends(require_roles(Role.facility_admin)), db: Session = Depends(get_db)):
    a = db.get(Appointment, aid)
    mine = set(db.scalars(select(Facility.id).where(Facility.admin_user_id == u.id)))
    if not a or a.facility_id not in mine or action not in ("confirm", "cancel", "complete"):
        raise HTTPException(404)
    a.status = {"confirm": "confirmed", "cancel": "cancelled", "complete": "completed"}[action]
    db.commit()
    return {"status": a.status}


# ------------------------------------------------------------------ admin lists
def _page(q, db, limit, offset):
    return db.scalars(q.limit(min(limit, 200)).offset(offset)).all()


@router.get("/admin/users")
def admin_users(q: str | None = None, role: str | None = None, limit: int = 50, offset: int = 0,
                admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(User).order_by(User.id.desc())
    if q:
        s = s.where(or_(User.email.ilike(f"%{q}%"), User.full_name.ilike(f"%{q}%")))
    if role:
        s = s.where(User.role == Role(role))
    return [{"id": x.id, "email": x.email, "name": x.full_name, "role": x.role.value, "active": x.is_active,
             "email_verified": x.email_verified, "created_at": x.created_at} for x in _page(s, db, limit, offset)]


@router.get("/admin/providers")
def admin_providers(status: str | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(User, ProviderProfile).join(ProviderProfile, ProviderProfile.user_id == User.id)
    if status:
        s = s.where(ProviderProfile.status == status)
    return [{"id": u.id, "name": u.full_name, "role": u.role.value, "status": p.status.value, "specialty": p.specialty,
             "can_prescribe": p.can_prescribe, "rating": p.rating_avg, "credit_units": credits.balance_tenths(db, u.id) / 10}
            for u, p in db.execute(s)]


@router.get("/admin/consultations")
def admin_consults(status: str | None = None, limit: int = 100, offset: int = 0, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(Consultation).order_by(Consultation.id.desc())
    if status:
        s = s.where(Consultation.status == ConsultStatus(status))
    return [{"id": c.id, "patient_id": c.patient_id, "provider_id": c.provider_id, "role": c.provider_role.value, "channel": c.channel,
             "status": c.status.value, "urgent": c.urgent, "fee_pesewas": c.fee_pesewas, "created_at": c.created_at} for c in _page(s, db, limit, offset)]


@router.get("/admin/appointments")
def admin_appts(limit: int = 100, offset: int = 0, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(Appointment).order_by(Appointment.starts_at.desc())
    return [{"id": a.id, "patient_id": a.patient_id, "provider_id": a.provider_id, "facility_id": a.facility_id, "starts_at": a.starts_at,
             "status": a.status} for a in _page(s, db, limit, offset)]


@router.get("/admin/payments")
def admin_payments(status: str | None = None, limit: int = 100, offset: int = 0, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(Payment).order_by(Payment.id.desc())
    if status:
        s = s.where(Payment.status == status)
    return [{"id": p.id, "reference": p.reference, "user_id": p.user_id, "purpose": p.purpose, "amount_pesewas": p.amount_pesewas,
             "method": p.method, "status": p.status.value, "failure_reason": p.failure_reason, "created_at": p.created_at} for p in _page(s, db, limit, offset)]


@router.get("/admin/subscriptions")
def admin_subs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": x.id, "user_id": x.user_id, "plan": x.plan, "source": x.source, "starts_at": x.starts_at, "expires_at": x.expires_at,
             "active": x.expires_at > utcnow()} for x in db.scalars(select(Subscription).order_by(Subscription.id.desc()).limit(200))]


class GrantSubIn(BaseModel):
    user_id: int
    plan: str
    days: int = 30
    reason: str


@router.post("/admin/subscriptions/grant", status_code=201)
def grant_sub(body: GrantSubIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if body.plan not in ("patient", "professional") or not body.reason.strip() or not 1 <= body.days <= 366:
        raise HTTPException(422)
    now = utcnow()
    db.add(Subscription(user_id=body.user_id, plan=body.plan, starts_at=now, expires_at=now + timedelta(days=body.days), source="admin_grant"))
    audit(db, admin.id, "subscription.grant", "subscription", body.user_id, plan=body.plan, days=body.days, reason=body.reason)
    db.commit()
    return {"ok": True}


@router.get("/admin/settlements")
def admin_settlements(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": s.id, "provider_id": s.provider_id, "gross": s.gross_pesewas, "commission": s.commission_pesewas, "net": s.net_pesewas,
             "status": s.status, "paid_at": s.paid_at} for s in db.scalars(select(Settlement).order_by(Settlement.id.desc()).limit(200))]


@router.get("/admin/facilities")
def admin_facilities(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name, "kind": f.kind, "city": f.city, "verified": f.verified, "has_emergency": f.has_emergency}
            for f in db.scalars(select(Facility).order_by(Facility.verified, Facility.id.desc()))]


@router.put("/admin/facilities/{fid}/verified")
def verify_facility(fid: int, verified: bool, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(Facility, fid)
    if not f:
        raise HTTPException(404)
    f.verified = verified
    audit(db, admin.id, "facility.verify", "facility", fid, verified=verified)
    db.commit()
    return {"ok": True}


@router.get("/admin/labs")
def admin_labs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": r.id, "patient_id": r.patient_id, "tests": r.tests, "status": r.status, "created_at": r.created_at}
            for r in db.scalars(select(LabRequest).order_by(LabRequest.id.desc()).limit(200))]


@router.get("/admin/complaints")
def admin_complaints(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": c.id, "user_id": c.user_id, "about_user_id": c.about_user_id, "body": c.body, "status": c.status, "created_at": c.created_at}
            for c in db.scalars(select(Complaint).order_by(Complaint.status, Complaint.id.desc()).limit(200))]


@router.post("/admin/complaints/{cid}/resolve")
def resolve_complaint(cid: int, note: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Complaint, cid)
    if not c:
        raise HTTPException(404)
    c.status = "resolved"
    audit(db, admin.id, "complaint.resolve", "complaint", cid, note=note)
    db.commit()
    return {"ok": True}


@router.get("/admin/contributions")
def admin_contribs(status: str | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(Contribution).order_by(Contribution.id.desc()).limit(200)
    if status:
        s = s.where(Contribution.status == ContribStatus(status))
    return [{"id": c.id, "author_id": c.author_id, "title": c.title, "kind": c.kind, "status": c.status.value, "published_at": c.published_at}
            for c in db.scalars(s)]


class EditIn(BaseModel):
    title: str | None = None
    body: str | None = None
    topic: str | None = None


@router.patch("/admin/contributions/{cid}")
def edit_contrib(cid: int, body: EditIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Contribution, cid)
    if not c:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    c.content_hash = credits.content_hash(c.title, c.body)
    audit(db, admin.id, "contribution.edit", "contribution", cid)
    db.commit()
    return {"ok": True}


@router.get("/admin/credits/ledger")
def admin_ledger(provider_id: int | None = None, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = select(CreditEntry).order_by(CreditEntry.id.desc()).limit(300)
    if provider_id:
        s = s.where(CreditEntry.provider_id == provider_id)
    return [{"id": e.id, "provider_id": e.provider_id, "type": e.entry_type, "units": e.amount_tenths / 10, "contribution_id": e.contribution_id,
             "actor_id": e.actor_id, "reason": e.reason, "at": e.created_at} for e in db.scalars(s)]


@router.get("/admin/languages")
def admin_languages(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"code": x.code, "name": x.name, "enabled": x.enabled, "stt": x.stt_supported, "tts": x.tts_supported,
             "human_interpreter": x.human_interpreter_available} for x in db.scalars(select(Language))]


@router.get("/admin/settings")
def admin_settings(admin: User = Depends(require_admin)):
    """Effective NON-SECRET platform settings (change via environment/config deploy; secrets never returned)."""
    s = get_settings()
    return {"currency": s.currency, "patient_subscription_pesewas": s.patient_subscription_pesewas,
            "doctor_consultation_pesewas": s.doctor_consultation_pesewas, "pharmacist_consultation_pesewas": s.pharmacist_consultation_pesewas,
            "professional_subscription_pesewas": s.professional_subscription_pesewas, "platform_commission_bps": s.platform_commission_bps,
            "credit_per_contribution_units": s.credit_per_contribution_tenths / 10, "credit_renewal_threshold_units": s.credit_renewal_threshold_tenths / 10,
            "payment_mode": s.payment_mode, "paystack_configured": bool(s.paystack_secret_key), "ai_configured": bool(s.anthropic_api_key),
            "emergency_numbers": s.emergency_numbers}


@router.get("/admin/reports/trends")
def trends(days: int = 30, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    rev: dict[str, int] = {}
    for p in db.scalars(select(Payment).where(Payment.status == "succeeded", Payment.created_at >= since)):
        k = f"{p.created_at:%Y-%m-%d}"
        rev[k] = rev.get(k, 0) + p.amount_pesewas
    signups: dict[str, int] = {}
    for u in db.scalars(select(User).where(User.created_at >= since)):
        k = f"{u.created_at:%Y-%m-%d}"
        signups[k] = signups.get(k, 0) + 1
    return {"revenue_by_day_pesewas": rev, "signups_by_day": signups}


@router.post("/admin/jobs/send-reminders")
def run_reminders(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return reminders.run_all(db)
