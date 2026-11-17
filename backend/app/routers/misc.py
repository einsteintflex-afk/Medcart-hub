import math

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import current_user
from ..ratelimit import limit
from ..models import Facility, Language, Notification, PatientProfile, User
from ..services import ai_assistant

router = APIRouter(tags=["misc"])


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _fac(f: Facility, d: float | None = None) -> dict:
    out = {"id": f.id, "name": f.name, "kind": f.kind, "address": f.address, "phone": f.phone, "services": f.services,
           "specialties": f.specialties, "hours": f.hours, "has_emergency": f.has_emergency,
           "directions_url": f"https://www.google.com/maps/dir/?api=1&destination={f.latitude},{f.longitude}" if f.latitude is not None else None}
    if d is not None:
        out["distance_km"] = round(d, 1)
    return out


def find_facilities(db: Session, kind=None, city=None, lat=None, lon=None, radius_km: float = 25, emergency_only: bool = False) -> list[dict]:
    """Plain function (no FastAPI parameter objects) so other endpoints can reuse it safely."""
    q = select(Facility).where(Facility.verified)
    if kind:
        q = q.where(Facility.kind == kind)
    if city:
        q = q.where(Facility.city.ilike(city))
    if emergency_only:
        q = q.where(Facility.has_emergency)
    rows = db.scalars(q).all()
    if lat is not None and lon is not None:  # location is used for this request only, never stored
        scored = [(f, haversine_km(lat, lon, f.latitude, f.longitude)) for f in rows if f.latitude is not None]
        return [_fac(f, d) for f, d in sorted(scored, key=lambda x: x[1]) if d <= radius_km]
    return [_fac(f) for f in rows]


@router.get("/facilities")
def facilities(kind: Literal["hospital", "clinic", "pharmacy", "laboratory", "diagnostic", "specialist"] | None = None,
               city: str | None = Query(None, max_length=100), lat: float | None = Query(None, ge=-90, le=90),
               lon: float | None = Query(None, ge=-180, le=180), radius_km: float = Query(25, gt=0, le=500),
               emergency_only: bool = False, db: Session = Depends(get_db)):
    return find_facilities(db, kind, city, lat, lon, radius_km, emergency_only)


@router.get("/languages")
def languages(db: Session = Depends(get_db)):
    """Effective capability = admin flag AND what the configured provider can really do."""
    from ..services import language as lang
    caps = lang.capabilities()
    return [{"code": x.code, "name": x.name, "stt": x.stt_supported and caps.get(x.code, {}).get("stt", False),
             "tts": x.tts_supported and caps.get(x.code, {}).get("tts", False), "translate": caps.get(x.code, {}).get("translate", False),
             "human_interpreter": x.human_interpreter_available} for x in db.scalars(select(Language).where(Language.enabled))]


# ---- emergency
@router.get("/emergency/info")
def emergency_info(country: str = Query("GH", pattern=r"^[A-Z]{2}$"), lat: float | None = Query(None, ge=-90, le=90),
                   lon: float | None = Query(None, ge=-180, le=180), db: Session = Depends(get_db)):
    s = get_settings()
    near = find_facilities(db, lat=lat, lon=lon, radius_km=50, emergency_only=True)
    return {"emergency_number": s.emergency_numbers.get(country, "112"), "nearby_emergency_facilities": near[:5],
            "warning_signs": ["Chest pain or pressure", "Difficulty breathing", "Sudden weakness, face droop or slurred speech",
                              "Severe bleeding", "Seizure or loss of consciousness", "Thoughts of harming yourself",
                              "Severe allergic reaction (swollen face/throat)", "Pregnancy with heavy bleeding or severe pain"],
            "disclaimer": "MedCart is not an emergency medical service. Call emergency services or go to the nearest emergency facility."}


class NotifyContactIn(BaseModel):
    message: str | None = None
    lat: float | None = None
    lon: float | None = None


@router.post("/emergency/notify-contact")
def notify_contact(body: NotifyContactIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    from ..services.notifications import _send_sms
    pp = db.get(PatientProfile, u.id)
    if not pp or not pp.emergency_contact_phone:
        raise HTTPException(409, "No emergency contact on file")
    loc = f" My location: https://maps.google.com/?q={body.lat},{body.lon}" if body.lat is not None and body.lon is not None else ""
    _send_sms(pp.emergency_contact_phone, f"{u.full_name} needs urgent help. {body.message or ''}{loc}")  # location only if user chose to share
    return {"ok": True}


# ---- notifications
@router.get("/notifications")
def notifications(u: User = Depends(current_user), db: Session = Depends(get_db)):
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "read": n.read, "created_at": n.created_at}
            for n in db.scalars(select(Notification).where(Notification.user_id == u.id).order_by(Notification.id.desc()).limit(100))]


@router.post("/notifications/{nid}/read")
def mark_read(nid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n or n.user_id != u.id:
        raise HTTPException(404)
    n.read = True
    db.commit()
    return {"ok": True}


# ---- AI assistant
class ChatMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AIIn(BaseModel):
    messages: list[ChatMsg] = Field(min_length=1, max_length=40)
    language: Literal["en", "tw", "ha", "fat", "fr", "es"] | None = None


@router.post("/ai/chat", dependencies=[Depends(limit("ai", 30, 60))])
def ai_chat(body: AIIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.messages[-1].role != "user":
        raise HTTPException(422, "last message must be from the user")
    hist = [{"role": m.role, "content": m.content} for m in body.messages[-12:]]
    pp = db.get(PatientProfile, u.id)
    lang = body.language or u.preferred_language
    extra = None
    if lang in ("tw", "ha", "fat"):  # no local-language lexicon yet: also screen an English translation of the user's words
        from ..services import language as langsvc
        try:
            extra = " ".join(langsvc.get_provider().translate(m["content"], lang, "en").text for m in hist[-4:] if m["role"] == "user")
        except Exception:  # noqa: BLE001 - provider missing: fall back to the always-on emergency footer
            extra = None
    return ai_assistant.respond(hist, lang, pp.country if pp else "GH", extra_screen_text=extra)
