from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..models import Consultation, LabRequest, ProviderProfile, Role, StoredFile, User, VerificationStatus, PROFESSIONAL_ROLES
from ..services import storage
from ..services.audit import audit

router = APIRouter(prefix="/files", tags=["files"])
MAX_FILES_PER_USER = 300


def can_read(db: Session, f: StoredFile, u: User) -> bool:
    from .health import _grant_ok  # local import to avoid a cycle
    if u.id in (f.owner_id, f.patient_id):
        return True
    if f.purpose == "credential":
        return u.role == Role.admin  # identity/licence documents: admins only (for verification)
    if f.consultation_id:
        c = db.get(Consultation, f.consultation_id)
        if c and u.id in (c.patient_id, c.provider_id):
            return True
    if f.patient_id and u.role in PROFESSIONAL_ROLES:
        return _grant_ok(db, f.patient_id, u, "document")
    return False


def require_owned(db: Session, key: str | None, owner: User, purposes: set[str], consultation_id: int | None = None) -> None:
    """Reject attaching a file key the user doesn't own (prevents referencing other people's uploads)."""
    if not key:
        return
    f = db.scalar(select(StoredFile).where(StoredFile.key == key))
    if not f or f.owner_id != owner.id or f.purpose not in purposes or (consultation_id and f.consultation_id != consultation_id):
        raise HTTPException(422, "Invalid file reference")


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), purpose: str = Form(...), consultation_id: int | None = Form(None),
                 lab_request_id: int | None = Form(None), u: User = Depends(current_user), db: Session = Depends(get_db)):
    if purpose not in storage.PURPOSES:
        raise HTTPException(422, f"purpose must be one of {sorted(storage.PURPOSES)}")
    if db.scalar(select(func.count(StoredFile.id)).where(StoredFile.owner_id == u.id)) >= MAX_FILES_PER_USER:
        raise HTTPException(429, "Upload quota reached")
    patient_id: int | None = u.id if u.role == Role.patient else None
    consult = None
    if consultation_id is not None:  # any consultation-linked upload: only the two parties, and it's shared with both
        if purpose not in ("consult", "voice", "symptom_photo"):
            raise HTTPException(422, "consultation_id is only valid for consult, voice or symptom_photo uploads")
        consult = db.get(Consultation, consultation_id)
        if not consult or u.id not in (consult.patient_id, consult.provider_id):
            raise HTTPException(404, "Consultation not found")
        patient_id = consult.patient_id
    if purpose == "credential":
        if u.role not in PROFESSIONAL_ROLES:
            raise HTTPException(403, "Professionals only")
    elif purpose == "lab":
        lab = db.get(LabRequest, lab_request_id or 0)
        pp = db.get(ProviderProfile, u.id)
        if u.role != Role.lab or not pp or pp.status != VerificationStatus.approved or not lab or lab.status == "resulted":
            raise HTTPException(403, "Only a verified laboratory can attach results to an open request")
        patient_id = lab.patient_id
    elif purpose == "consult" and not consult:
        raise HTTPException(422, "consultation_id required")
    elif purpose in ("record", "symptom_photo", "voice") and u.role != Role.patient and not consult:
        raise HTTPException(403, "Patients only")
    # read at most limit+1 bytes so an oversized upload can't exhaust memory
    data = await file.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    try:
        key, ctype, digest = storage.save(data)
    except storage.UploadError as e:
        raise HTTPException(415 if "type" in str(e) else 413 if "large" in str(e) else 422, str(e))
    name = (file.filename or "file").replace("\\", "/").split("/")[-1][:120]
    f = StoredFile(key=key, owner_id=u.id, patient_id=patient_id, purpose=purpose, consultation_id=consult.id if consult else None,
                   original_name=name, content_type=ctype, size=len(data), sha256=digest)
    db.add(f)
    audit(db, u.id, "file.upload", "file", key, patient_id=patient_id, purpose=purpose, size=len(data))
    db.commit()
    return {"key": key, "content_type": ctype, "size": len(data), "name": name}


@router.get("/{key}")
def download(key: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    f = db.scalar(select(StoredFile).where(StoredFile.key == key))
    if not f or not can_read(db, f, u):
        raise HTTPException(404)  # 404, not 403: don't reveal that a key exists
    try:
        data = storage.load(key)
    except (FileNotFoundError, storage.UploadError):
        raise HTTPException(404)
    if u.id not in (f.owner_id, f.patient_id):
        audit(db, u.id, "file.read", "file", key, patient_id=f.patient_id)
        db.commit()
    safe = "".join(c for c in f.original_name if c.isalnum() or c in "._- ") or "file"
    return Response(data, media_type=f.content_type, headers={"Content-Disposition": f'attachment; filename="{safe}"',
                                                              "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.get("")
def my_files(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(StoredFile).where(StoredFile.owner_id == u.id).order_by(StoredFile.id.desc()).limit(100)).all()
    return [{"key": f.key, "name": f.original_name, "purpose": f.purpose, "content_type": f.content_type, "size": f.size, "created_at": f.created_at} for f in rows]
