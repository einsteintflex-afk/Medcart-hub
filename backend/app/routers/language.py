from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user, require_admin
from ..models import ConsultMessage, Consultation, InterpreterRequest, PatientProfile, Role, User
from ..ratelimit import limit
from ..services import ai_safety, language
from ..services.audit import audit
from ..services.notifications import notify
from ..services.storage import UploadError, sniff

router = APIRouter(tags=["language"])
LANG_CODES = {"en", "tw", "ha", "fat", "fr", "es"}


def _unavailable(e: Exception):
    raise HTTPException(503, str(e))


@router.get("/language/capabilities")
def capabilities():
    return {"provider": language.get_provider().name, "languages": language.capabilities(),
            "note": "Speech features for Twi, Fante and Hausa are off until validated with native speakers."}


@router.post("/ai/transcribe", dependencies=[Depends(limit("stt", 30, 60))])
async def transcribe(audio: UploadFile = File(...), lang: str = Form("en"), u: User = Depends(current_user), db: Session = Depends(get_db)):
    if lang not in LANG_CODES:
        raise HTTPException(422, "unsupported language")
    data = await audio.read(get_settings().max_upload_mb * 1024 * 1024 + 1)
    try:
        ctype = sniff(data)
    except UploadError as e:
        raise HTTPException(415, str(e))
    if not ctype.startswith("audio/"):
        raise HTTPException(415, "Audio files only")
    if lang not in language.SUPPORT["stt"]:
        raise HTTPException(501, "Voice input is not yet available in this language. Please type your message, or ask a family member to help.")
    try:
        text, conf = language.get_provider().transcribe(data, ctype, lang)
    except language.ProviderUnavailable as e:
        _unavailable(e)
    number = get_settings().emergency_numbers.get((db.get(PatientProfile, u.id) or PatientProfile()).country or "GH", "112")
    emergency = ai_safety.screen_emergency(text)
    return {"text": text, "language": lang, "confidence": conf, "low_confidence": conf is not None and conf < 0.6,
            "emergency": emergency, "emergency_message": ai_safety.emergency_message(lang, number) if emergency else None}


class SpeakIn(BaseModel):
    text: str
    language: str = "en"


@router.post("/ai/speak", dependencies=[Depends(limit("tts", 60, 60))])
def speak(body: SpeakIn, u: User = Depends(current_user)):
    if len(body.text) > 3000:
        raise HTTPException(422, "Text too long")
    if body.language not in language.SUPPORT["tts"]:
        raise HTTPException(501, "Spoken replies are not yet available in this language.")
    try:
        audio, ctype = language.get_provider().synthesize(body.text, body.language)
    except language.ProviderUnavailable as e:
        _unavailable(e)
    return Response(audio, media_type=ctype, headers={"Cache-Control": "private, no-store"})


class TranslateIn(BaseModel):
    text: str
    source: str
    target: str


@router.post("/translate", dependencies=[Depends(limit("translate", 60, 60))])
def translate(body: TranslateIn, u: User = Depends(current_user)):
    if body.source not in LANG_CODES or body.target not in LANG_CODES or len(body.text) > 4000:
        raise HTTPException(422, "Invalid request")
    try:
        return language.translate_clinical(body.text, body.source, body.target)
    except language.ProviderUnavailable as e:
        _unavailable(e)


@router.post("/consultations/{cid}/messages/{mid}/translate")
def translate_message(cid: int, mid: int, target: str, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    m = db.get(ConsultMessage, mid)
    if not c or not m or m.consultation_id != cid or u.id not in (c.patient_id, c.provider_id) or not c.interpretation_enabled:
        raise HTTPException(404, "Translation is not enabled for this consultation")
    if target not in LANG_CODES:
        raise HTTPException(422)
    try:
        return language.translate_clinical(m.body, m.language, target)
    except language.ProviderUnavailable as e:
        _unavailable(e)


class InterpIn(BaseModel):
    language: str
    reason: str | None = None


@router.post("/consultations/{cid}/interpreter", status_code=201)
def request_interpreter(cid: int, body: InterpIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or u.id not in (c.patient_id, c.provider_id) or body.language not in LANG_CODES:
        raise HTTPException(404)
    r = InterpreterRequest(consultation_id=cid, requested_by=u.id, language=body.language, reason=body.reason)
    db.add(r)
    db.flush()
    for a in db.scalars(select(User).where(User.role == Role.admin, User.is_active)):
        notify(db, a, "interpreter_request", "Human interpreter requested", f"Consultation #{cid}, language {body.language}", external=False)
    audit(db, u.id, "interpreter.request", "consultation", cid, patient_id=c.patient_id, language=body.language)
    db.commit()
    return {"id": r.id, "status": r.status}


@router.get("/admin/interpreter-requests")
def list_interpreter(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": r.id, "consultation_id": r.consultation_id, "language": r.language, "reason": r.reason, "status": r.status, "created_at": r.created_at}
            for r in db.scalars(select(InterpreterRequest).order_by(InterpreterRequest.status, InterpreterRequest.id.desc()).limit(200))]


@router.post("/admin/interpreter-requests/{rid}/close")
def close_interpreter(rid: int, note: str = "", admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(InterpreterRequest, rid)
    if not r:
        raise HTTPException(404)
    r.status = "closed"
    c = db.get(Consultation, r.consultation_id)
    notify(db, r.requested_by, "interpreter_update", "Interpreter update", note or "Your interpreter request was handled.")
    audit(db, admin.id, "interpreter.close", "interpreter_request", rid)
    db.commit()
    return {"ok": True}
