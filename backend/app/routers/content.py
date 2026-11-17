from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, verified_professional
from ..models import Contribution, ContribStatus, CreditEntry, ProviderProfile, User
from ..services import credits
from ..services.audit import audit

router = APIRouter(tags=["content"])
KINDS = {"article", "research", "education", "answer", "campaign"}


class ContribIn(BaseModel):
    kind: str
    title: str
    body: str
    topic: str | None = None
    language: str = "en"
    submit: bool = True


@router.post("/contributions", status_code=201)
def create(body: ContribIn, u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    c = Contribution(author_id=u.id, kind=body.kind, title=body.title, body=body.body, topic=body.topic, language=body.language,
                     content_hash=credits.content_hash(body.title, body.body),
                     status=ContribStatus.submitted if body.submit else ContribStatus.draft)
    db.add(c)
    db.commit()
    return {"id": c.id, "status": c.status.value}


@router.get("/contributions/mine")
def mine(u: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Contribution).where(Contribution.author_id == u.id).order_by(Contribution.id.desc())).all()
    return [{"id": c.id, "title": c.title, "kind": c.kind, "status": c.status.value, "review_note": c.review_note} for c in rows]


@router.post("/contributions/{cid}/withdraw")
def withdraw(cid: int, u: User = Depends(current_user), db: Session = Depends(get_db)):
    c = db.get(Contribution, cid)
    if not c or c.author_id != u.id:
        raise HTTPException(404)
    was_approved = c.status == ContribStatus.approved
    c.status = ContribStatus.withdrawn
    if was_approved:  # withdrawn content no longer earns its credit
        credits.reverse_award(db, c.id, u.id, "Content withdrawn by author")
    db.commit()
    return {"status": "withdrawn"}


@router.get("/articles")
def published(topic: str | None = None, language: str | None = None, db: Session = Depends(get_db)):
    """Public education feed: approved content only, with the author's verified profile."""
    q = select(Contribution, User, ProviderProfile).join(User, User.id == Contribution.author_id) \
        .join(ProviderProfile, ProviderProfile.user_id == User.id).where(Contribution.status == ContribStatus.approved)
    if topic:
        q = q.where(Contribution.topic == topic)
    if language:
        q = q.where(Contribution.language == language)
    return [{"id": c.id, "title": c.title, "body": c.body, "kind": c.kind, "topic": c.topic, "language": c.language,
             "published_at": c.published_at,
             "author": {"id": usr.id, "name": usr.full_name, "role": usr.role.value, "specialty": p.specialty,
                        "qualifications": p.qualifications, "verified": p.status.value == "approved"}}
            for c, usr, p in db.execute(q.order_by(Contribution.published_at.desc()))]


@router.get("/credits/me")
def my_credits(u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    ledger = db.scalars(select(CreditEntry).where(CreditEntry.provider_id == u.id).order_by(CreditEntry.id.desc())).all()
    return {**credits.renewal_status(db, u.id),
            "ledger": [{"id": e.id, "type": e.entry_type, "units": e.amount_tenths / 10, "reason": e.reason,
                        "contribution_id": e.contribution_id, "at": e.created_at} for e in ledger]}


@router.post("/credits/redeem-renewal")
def redeem(u: User = Depends(verified_professional()), db: Session = Depends(get_db)):
    try:
        rb = credits.redeem_renewal(db, u.id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    db.commit()
    return {"free_until": rb.period_end}
