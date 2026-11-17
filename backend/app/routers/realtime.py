"""Audio/video consultations: WebRTC peer-to-peer media with a WebSocket signalling relay.

Media never touches our servers (DTLS-SRTP end to end). We only relay offers/answers/ICE candidates between the two
authorised parties. State is in-process: run ONE api replica per call room set, or add sticky routing / a Redis relay
before scaling the signalling service horizontally.
"""
import base64
import hashlib
import hmac
import json
import time

import jwt
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal, get_db
from ..deps import current_user
from ..models import Consultation, ConsultStatus, User
from ..services.audit import audit

router = APIRouter(tags=["realtime"])
ALLOWED = {"offer", "answer", "ice", "hangup", "ready"}
MAX_MSG = 16 * 1024
rooms: dict[int, dict[int, WebSocket]] = {}


def _open(c: Consultation | None, uid: int) -> bool:
    return bool(c and uid in (c.patient_id, c.provider_id) and c.channel in ("audio", "video")
                and c.status in (ConsultStatus.accepted, ConsultStatus.in_progress))


def ice_servers(uid: int) -> list[dict]:
    s = get_settings()
    out = [{"urls": s.stun_urls}] if s.stun_urls else []
    if s.turn_urls:
        if s.turn_secret:  # coturn REST-style ephemeral credentials (valid 1 hour)
            user = f"{int(time.time()) + 3600}:{uid}"
            cred = base64.b64encode(hmac.new(s.turn_secret.encode(), user.encode(), hashlib.sha1).digest()).decode()
            out.append({"urls": s.turn_urls, "username": user, "credential": cred})
        elif s.turn_username:
            out.append({"urls": s.turn_urls, "username": s.turn_username, "credential": s.turn_credential})
    return out


@router.post("/consultations/{cid}/call-ticket")
def call_ticket(cid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Consultation, cid)
    if not c or u.id not in (c.patient_id, c.provider_id):
        raise HTTPException(404)
    if not _open(c, u.id):
        raise HTTPException(409, "The call is available once the consultation is accepted (audio/video consultations only)")
    ticket = jwt.encode({"sub": str(u.id), "typ": "ws", "cid": cid, "tv": u.token_version, "exp": time.time() + 45},
                        get_settings().jwt_secret, algorithm="HS256")
    audit(db, u.id, "call.ticket", "consultation", cid, patient_id=c.patient_id)
    db.commit()
    return {"ticket": ticket, "ws_path": f"/api/v1/ws/consultations/{cid}", "ice_servers": ice_servers(u.id)}


@router.websocket("/ws/consultations/{cid}")
async def call_socket(ws: WebSocket, cid: int, ticket: str = ""):
    try:
        p = jwt.decode(ticket, get_settings().jwt_secret, algorithms=["HS256"])
        if p.get("typ") != "ws" or p.get("cid") != cid:
            raise jwt.InvalidTokenError("scope")
        uid = int(p["sub"])
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    with SessionLocal() as db:
        c, u = db.get(Consultation, cid), db.get(User, uid)
        if not u or not u.is_active or u.token_version != p.get("tv") or not _open(c, uid):
            await ws.close(code=4403)
            return
    await ws.accept()
    room = rooms.setdefault(cid, {})
    if uid in room:  # same user reconnecting: drop the stale socket
        try:
            await room[uid].close(code=4409)
        except Exception:  # noqa: BLE001
            pass
    room[uid] = ws
    others = [w for k, w in room.items() if k != uid]
    for o in others:
        await o.send_json({"type": "peer-joined"})
    await ws.send_json({"type": "joined", "peers": len(others)})
    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > MAX_MSG:
                await ws.close(code=1009)
                return
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("type") not in ALLOWED:
                continue
            # Re-check authorisation every message: the consultation may have been completed/cancelled meanwhile.
            with SessionLocal() as db:
                if not _open(db.get(Consultation, cid), uid):
                    await ws.close(code=4403)
                    return
            for k, w in list(room.items()):
                if k != uid:
                    await w.send_json({"type": msg["type"], "data": msg.get("data")})
    except WebSocketDisconnect:
        pass
    finally:
        if room.get(uid) is ws:
            del room[uid]
        for o in list(room.values()):
            try:
                await o.send_json({"type": "peer-left"})
            except Exception:  # noqa: BLE001
                pass
        if not room:
            rooms.pop(cid, None)
