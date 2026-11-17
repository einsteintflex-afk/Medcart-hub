import csv
import io
from datetime import datetime, timedelta
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db, utcnow
from ..deps import current_user, verified_professional
from ..models import (AccessGrant, HealthRecord, LabRequest, Medication, PROFESSIONAL_ROLES, Prescription, Role, User, VitalReading)
from ..services.audit import audit
from ..services.clinical import UNITS, check_interactions, is_abnormal
from ..services.notifications import notify

router = APIRouter(tags=["health"])
RECORD_CATEGORIES = {"history", "diagnosis", "medication", "allergy", "consultation", "prescription", "lab", "imaging",
                     "admission", "surgery", "immunization", "note", "document"}


def _grant_ok(db: Session, patient_id: int, viewer: User, category: str) -> bool:
    if viewer.id == patient_id:
        return True
    if viewer.role not in PROFESSIONAL_ROLES:
        return False
    for g in db.scalars(select(AccessGrant).where(AccessGrant.patient_id == patient_id, AccessGrant.provider_id == viewer.id,
                                                  AccessGrant.revoked_at.is_(None),
                                                  or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > utcnow()))):
        if "*" in g.categories or category in g.categories:
            return True
    return False


def _any_grant(db: Session, patient_id: int, viewer: User) -> bool:
    return viewer.role in PROFESSIONAL_ROLES and db.scalar(select(AccessGrant.id).where(
        AccessGrant.patient_id == patient_id, AccessGrant.provider_id == viewer.id, AccessGrant.revoked_at.is_(None),
        or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > utcnow())).limit(1)) is not None


# ---- vitals
class VitalIn(BaseModel):
    kind: str
    value: float
    value2: float | None = None
    measured_at: datetime | None = None
    source: str = "manual"


@router.post("/vitals", status_code=201)
def add_vital(body: VitalIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.role != Role.patient:
        raise HTTPException(403)
    if body.kind not in UNITS:
        raise HTTPException(422, f"kind must be one of {sorted(UNITS)}")
    if body.kind == "bp" and body.value2 is None:
        raise HTTPException(422, "bp needs systolic (value) and diastolic (value2)")
    ab = is_abnormal(body.kind, body.value, body.value2)
    db.add(VitalReading(patient_id=u.id, kind=body.kind, value=body.value, value2=body.value2, unit=UNITS[body.kind],
                        source=body.source, abnormal=ab, measured_at=body.measured_at or utcnow()))
    if ab:
        notify(db, u, "abnormal_reading", "Abnormal reading recorded",
               f"Your {body.kind} reading is outside the usual range. If you feel unwell, contact a clinician; "
               "if symptoms are severe, seek emergency care.")
    db.commit()
    return {"abnormal": ab}


def _vital_rows(db, pid, kind=None, days=30):
    q = select(VitalReading).where(VitalReading.patient_id == pid, VitalReading.measured_at >= utcnow() - timedelta(days=days))
    if kind:
        q = q.where(VitalReading.kind == kind)
    return db.scalars(q.order_by(VitalReading.measured_at)).all()


@router.get("/patients/{pid}/vitals")
def vitals(pid: int, kind: str | None = None, days: int = 30, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _grant_ok(db, pid, u, "vitals"):
        raise HTTPException(403, "The patient has not shared this data with you")
    if u.id != pid:
        audit(db, u.id, "vitals.read", "vital_readings", patient_id=pid)
        db.commit()
    return [{"kind": r.kind, "value": r.value, "value2": r.value2, "unit": r.unit, "abnormal": r.abnormal,
             "measured_at": r.measured_at, "source": r.source} for r in _vital_rows(db, pid, kind, days)]


@router.get("/vitals/summary")
def summary(period: str = "week", u: User = Depends(current_user), db: Session = Depends(get_db)):
    days = {"week": 7, "month": 30}.get(period)
    if not days:
        raise HTTPException(422, "period must be week or month")
    out: dict = {}
    for r in _vital_rows(db, u.id, None, days):
        d = out.setdefault(r.kind, {"unit": r.unit, "values": [], "abnormal_count": 0})
        d["values"].append(r.value)
        d["abnormal_count"] += int(r.abnormal)
    return {k: {"unit": d["unit"], "count": len(d["values"]), "min": min(d["values"]), "max": max(d["values"]),
                "avg": round(mean(d["values"]), 1), "abnormal_count": d["abnormal_count"],
                "trend": "rising" if len(d["values"]) > 2 and d["values"][-1] > d["values"][0] * 1.05
                else "falling" if len(d["values"]) > 2 and d["values"][-1] < d["values"][0] * 0.95 else "stable"}
            for k, d in out.items()}


@router.get("/vitals/report.csv")
def report_csv(days: int = 30, u: User = Depends(current_user), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["measured_at", "kind", "value", "value2", "unit", "abnormal", "source"])
    for r in _vital_rows(db, u.id, None, days):
        w.writerow([r.measured_at.isoformat(), r.kind, r.value, r.value2 or "", r.unit, r.abnormal, r.source])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=vitals.csv"})


# ---- EHR
class RecordIn(BaseModel):
    category: str
    title: str
    body: str | None = None
    document_key: str | None = None
    recorded_on: datetime | None = None


@router.post("/records", status_code=201)
def add_record(body: RecordIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.category not in RECORD_CATEGORIES:
        raise HTTPException(422, f"category must be one of {sorted(RECORD_CATEGORIES)}")
    r = HealthRecord(patient_id=u.id, category=body.category, title=body.title, body=body.body,
                     document_key=body.document_key, author_id=u.id, recorded_on=body.recorded_on or utcnow())
    db.add(r)
    db.flush()
    audit(db, u.id, "record.create", "health_record", r.id, patient_id=u.id)
    db.commit()
    return {"id": r.id}


@router.get("/patients/{pid}/records")
def records(pid: int, category: str | None = None, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.id != pid and u.role != Role.admin and not (_grant_ok(db, pid, u, category) if category else _any_grant(db, pid, u)):
        raise HTTPException(403, "The patient has not shared these records with you")
    q = select(HealthRecord).where(HealthRecord.patient_id == pid)
    if category:
        q = q.where(HealthRecord.category == category)
    rows = db.scalars(q.order_by(HealthRecord.recorded_on.desc())).all()
    if u.id != pid:  # keep only categories the grant allows
        rows = [r for r in rows if _grant_ok(db, pid, u, r.category) or u.role == Role.admin]
    audit(db, u.id, "record.read", "health_record", patient_id=pid, count=len(rows))
    db.commit()
    return [{"id": r.id, "category": r.category, "title": r.title, "body": r.body, "document_key": r.document_key,
             "recorded_on": r.recorded_on} for r in rows]


class GrantIn(BaseModel):
    provider_id: int
    categories: list[str] = ["*"]
    days: int | None = 30


@router.post("/access-grants", status_code=201)
def grant(body: GrantIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    prov = db.get(User, body.provider_id)
    if u.role != Role.patient or not prov or prov.role not in PROFESSIONAL_ROLES:
        raise HTTPException(422)
    g = AccessGrant(patient_id=u.id, provider_id=prov.id, categories=body.categories,
                    expires_at=utcnow() + timedelta(days=body.days) if body.days else None)
    db.add(g)
    db.flush()
    audit(db, u.id, "grant.create", "access_grant", g.id, patient_id=u.id, provider_id=prov.id)
    db.commit()
    return {"id": g.id}


@router.delete("/access-grants/{gid}")
def revoke(gid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    g = db.get(AccessGrant, gid)
    if not g or g.patient_id != u.id:
        raise HTTPException(404)
    g.revoked_at = utcnow()
    audit(db, u.id, "grant.revoke", "access_grant", gid, patient_id=u.id)
    db.commit()
    return {"ok": True}


@router.get("/access-log")
def access_log(u: User = Depends(current_user), db: Session = Depends(get_db)):
    """Patients can see who accessed their data."""
    from ..models import AuditLog
    rows = db.scalars(select(AuditLog).where(AuditLog.patient_id == u.id).order_by(AuditLog.id.desc()).limit(200)).all()
    return [{"actor_id": r.actor_id, "action": r.action, "at": r.created_at} for r in rows]


# ---- medications
class MedIn(BaseModel):
    name: str
    dose: str | None = None
    times_of_day: list[str] = []
    remaining_doses: int | None = None


@router.post("/medications", status_code=201)
def add_med(body: MedIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    existing = [m.name for m in db.scalars(select(Medication).where(Medication.patient_id == u.id, Medication.active))]
    warnings = check_interactions(existing + [body.name])
    m = Medication(patient_id=u.id, name=body.name, dose=body.dose, times_of_day=body.times_of_day,
                   remaining_doses=body.remaining_doses)
    db.add(m)
    db.commit()
    return {"id": m.id, "interaction_warnings": warnings,
            "disclaimer": "Limited automated check. Confirm with a pharmacist or doctor."}


@router.get("/medications")
def list_meds(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Medication).where(Medication.patient_id == u.id)).all()
    return [{"id": m.id, "name": m.name, "dose": m.dose, "times_of_day": m.times_of_day, "active": m.active,
             "remaining_doses": m.remaining_doses,
             "refill_soon": m.remaining_doses is not None and m.remaining_doses <= 7} for m in rows]


@router.get("/medications/interactions")
def interactions(drugs: str, u: User = Depends(current_user)):
    return {"results": check_interactions(drugs.split(",")),
            "disclaimer": "Limited automated check; absence of a warning does not mean a combination is safe."}


@router.get("/prescriptions")
def my_rx(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Prescription).where(Prescription.patient_id == u.id).order_by(Prescription.id.desc())).all()
    return [{"id": r.id, "items": r.items, "created_at": r.created_at, "prescriber_id": r.prescriber_id} for r in rows]


# ---- laboratory
class LabIn(BaseModel):
    tests: list[str]
    facility_id: int | None = None
    scheduled_for: datetime | None = None


@router.post("/lab-requests", status_code=201)
def lab_request(body: LabIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if not body.tests:
        raise HTTPException(422, "tests required")
    r = LabRequest(patient_id=u.id, requested_by=u.id, facility_id=body.facility_id, tests=body.tests,
                   scheduled_for=body.scheduled_for, status="scheduled" if body.scheduled_for else "requested")
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.post("/patients/{pid}/lab-requests", status_code=201)
def clinician_lab_request(pid: int, body: LabIn, u: User = Depends(verified_professional(Role.doctor)),
                          db: Session = Depends(get_db)):
    if not _grant_ok(db, pid, u, "lab"):
        raise HTTPException(403, "No access to this patient")
    r = LabRequest(patient_id=pid, requested_by=u.id, facility_id=body.facility_id, tests=body.tests)
    db.add(r)
    notify(db, pid, "lab_requested", "Laboratory tests requested", ", ".join(body.tests))
    db.commit()
    return {"id": r.id}


@router.get("/lab-requests")
def lab_list(u: User = Depends(current_user), db: Session = Depends(get_db)):
    if u.role == Role.lab:
        q = select(LabRequest).where(LabRequest.status != "resulted")
    else:
        q = select(LabRequest).where(LabRequest.patient_id == u.id)
    return [{"id": r.id, "tests": r.tests, "status": r.status, "result_text": r.result_text if u.role != Role.lab else None,
             "patient_id": r.patient_id, "scheduled_for": r.scheduled_for} for r in db.scalars(q.order_by(LabRequest.id.desc()))]


class LabResultIn(BaseModel):
    result_text: str | None = None
    result_document_key: str | None = None


@router.post("/lab-requests/{lid}/result")
def lab_result(lid: int, body: LabResultIn, u: User = Depends(verified_professional(Role.lab)), db: Session = Depends(get_db)):
    r = db.get(LabRequest, lid)
    if not r or r.status == "resulted":
        raise HTTPException(404)
    if not (body.result_text or body.result_document_key):
        raise HTTPException(422, "result required")
    r.result_text, r.result_document_key, r.resulted_by, r.status = body.result_text, body.result_document_key, u.id, "resulted"
    db.add(HealthRecord(patient_id=r.patient_id, category="lab", title=f"Lab result: {', '.join(r.tests)}",
                        body=body.result_text, document_key=body.result_document_key, author_id=u.id))
    notify(db, r.patient_id, "lab_result", "Your laboratory results are ready", ", ".join(r.tests))
    audit(db, u.id, "lab.result", "lab_request", lid, patient_id=r.patient_id)
    db.commit()
    return {"ok": True}
