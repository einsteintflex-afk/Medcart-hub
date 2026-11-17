from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import client_ip, require_admin
from ..models import (AuditLog, Complaint, Consultation, Contribution, ContribStatus, Credential, CreditEntry, Facility,
                      Language, Payment, PaymentStatus, ProviderProfile, Settlement, User, VerificationStatus)
from ..services import credits
from ..services.audit import audit
from ..services.notifications import notify

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/providers/pending")
def pending(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for p, u in db.execute(select(ProviderProfile, User).join(User, User.id == ProviderProfile.user_id)
                           .where(ProviderProfile.status == VerificationStatus.pending)):
        creds = db.scalars(select(Credential).where(Credential.provider_id == u.id)).all()
        out.append({"id": u.id, "name": u.full_name, "role": u.role.value, "email": u.email,
                    "credentials": [{"id": c.id, "kind": c.kind, "issuer": c.issuer, "number": c.number,
                                     "document_key": c.document_key} for c in creds]})
    return out


class ReviewIn(BaseModel):
    approve: bool
    note: str | None = None
    can_prescribe: bool = False


@router.post("/providers/{pid}/review")
def review(pid: int, body: ReviewIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p, u = db.get(ProviderProfile, pid), db.get(User, pid)
    if not p or not u:
        raise HTTPException(404)
    if body.approve and not db.scalars(select(Credential).where(Credential.provider_id == pid)).first():
        raise HTTPException(409, "No credentials on file")
    status = VerificationStatus.approved if body.approve else VerificationStatus.rejected
    p.status, p.reviewed_by, p.reviewed_at, p.review_note = status, admin.id, utcnow(), body.note
    p.can_prescribe = body.approve and body.can_prescribe and u.role.value == "doctor"
    for c in db.scalars(select(Credential).where(Credential.provider_id == pid)):
        c.status = status
    notify(db, u, "verification", "Credential review update", f"Your account was {status.value}. {body.note or ''}")
    audit(db, admin.id, "provider.review", "provider_profile", pid, status=status.value, can_prescribe=p.can_prescribe)
    db.commit()
    return {"status": status.value}


@router.post("/providers/{pid}/suspend")
def suspend(pid: int, reason: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    p = db.get(ProviderProfile, pid)
    if not p:
        raise HTTPException(404)
    p.status = VerificationStatus.suspended
    audit(db, admin.id, "provider.suspend", "provider_profile", pid, reason=reason)
    db.commit()
    return {"ok": True}


@router.get("/contributions/pending")
def pending_contribs(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": c.id, "author_id": c.author_id, "title": c.title, "kind": c.kind, "body": c.body}
            for c in db.scalars(select(Contribution).where(Contribution.status == ContribStatus.submitted))]


class ModerateIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/contributions/{cid}/moderate")
def moderate(cid: int, body: ModerateIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Contribution, cid)
    if not c or c.status != ContribStatus.submitted:
        raise HTTPException(404, "Not awaiting review")
    c.reviewer_id, c.review_note = admin.id, body.note
    awarded = None
    if body.approve:
        c.status, c.published_at = ContribStatus.approved, utcnow()
        awarded = credits.award_for_contribution(db, c, admin.id)
    else:
        c.status = ContribStatus.rejected
    notify(db, c.author_id, "contribution_review", f"Contribution {c.status.value}", body.note or c.title)
    audit(db, admin.id, "contribution.moderate", "contribution", cid, approve=body.approve, credited=bool(awarded))
    db.commit()
    return {"status": c.status.value, "credited": bool(awarded),
            "credit_note": None if awarded or not body.approve else "Published, but no credit: duplicate or below quality threshold"}


@router.post("/contributions/{cid}/withdraw")
def admin_withdraw(cid: int, reason: str, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Contribution, cid)
    if not c:
        raise HTTPException(404)
    c.status = ContribStatus.withdrawn
    rev = credits.reverse_award(db, cid, admin.id, f"Admin withdrawal: {reason}")
    audit(db, admin.id, "contribution.withdraw", "contribution", cid, reason=reason, reversed=bool(rev))
    db.commit()
    return {"credit_reversed": bool(rev)}


class AdjustIn(BaseModel):
    units_tenths: int
    reason: str


@router.post("/credits/{provider_id}/adjust")
def adjust(provider_id: int, body: AdjustIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        e = credits.adjust(db, provider_id, body.units_tenths, admin.id, body.reason)
    except ValueError as ex:
        raise HTTPException(422, str(ex))
    db.commit()
    return {"ledger_id": e.id, "balance_units": credits.balance_tenths(db, provider_id) / 10}


@router.get("/audit-logs")
def audit_logs(action: str | None = None, limit: int = 200, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if action:
        q = q.where(AuditLog.action == action)
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "entity": a.entity, "entity_id": a.entity_id,
             "patient_id": a.patient_id, "detail": a.detail, "at": a.created_at} for a in db.scalars(q)]


@router.get("/reports/financial")
def financial(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    by_purpose = dict(db.execute(select(Payment.purpose, func.coalesce(func.sum(Payment.amount_pesewas), 0))
                                 .where(Payment.status == PaymentStatus.succeeded).group_by(Payment.purpose)).all())
    commission = db.scalar(select(func.coalesce(func.sum(Settlement.commission_pesewas), 0)).where(Settlement.status != "reversed"))
    owed = db.scalar(select(func.coalesce(func.sum(Settlement.net_pesewas), 0)).where(Settlement.status == "pending"))
    return {"revenue_by_purpose_pesewas": by_purpose, "platform_commission_pesewas": commission,
            "provider_payouts_pending_pesewas": owed}


@router.get("/reports/operational")
def operational(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"users": db.scalar(select(func.count(User.id))),
            "consultations": db.scalar(select(func.count(Consultation.id))),
            "providers_pending": db.scalar(select(func.count(ProviderProfile.user_id)).where(ProviderProfile.status == VerificationStatus.pending)),
            "open_complaints": db.scalar(select(func.count(Complaint.id)).where(Complaint.status == "open"))}


@router.post("/settlements/{sid}/mark-paid")
def mark_paid(sid: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Settlement, sid)
    if not s or s.status != "pending":
        raise HTTPException(404)
    s.status, s.paid_at = "paid", utcnow()
    audit(db, admin.id, "settlement.paid", "settlement", sid, net=s.net_pesewas)
    db.commit()
    return {"ok": True}


class FacilityIn(BaseModel):
    name: str
    kind: str
    address: str
    city: str | None = None
    region: str | None = None
    country: str = "GH"
    phone: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    services: list[str] = []
    specialties: list[str] = []
    hours: dict = {}
    has_emergency: bool = False


@router.post("/facilities", status_code=201)
def add_facility(body: FacilityIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    f = Facility(**body.model_dump(), verified=True)
    db.add(f)
    db.flush()
    audit(db, admin.id, "facility.create", "facility", f.id)
    db.commit()
    return {"id": f.id}


class LangIn(BaseModel):
    code: str
    name: str
    enabled: bool = True
    stt_supported: bool = False
    tts_supported: bool = False
    human_interpreter_available: bool = False


@router.put("/languages")
def upsert_language(body: LangIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    lang = db.get(Language, body.code) or Language(code=body.code, name=body.name)
    for k, v in body.model_dump().items():
        setattr(lang, k, v)
    db.add(lang)
    audit(db, admin.id, "language.upsert", "language", body.code)
    db.commit()
    return {"ok": True}


@router.put("/users/{uid}/active")
def set_active(uid: int, active: bool, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.id == admin.id:
        raise HTTPException(404)
    u.is_active = active
    audit(db, admin.id, "user.set_active", "user", uid, active=active)
    db.commit()
    return {"ok": True}
