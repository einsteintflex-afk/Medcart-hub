from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db, utcnow
from ..deps import current_user
from ..models import (Credential, OneTimeToken, PatientProfile, PROFESSIONAL_ROLES, ProviderProfile, Role, User)
from ..security import (create_token, decode_token, hash_password, hash_token, new_opaque_token, new_otp,
                        validate_password_strength, verify_password)
from ..services.audit import audit
from ..services.notifications import notify

router = APIRouter(prefix="/auth", tags=["auth"])
SUPPORTED_LANGS = {"en", "tw", "ha", "fat", "fr", "es"}


class RegisterIn(BaseModel):
    email: EmailStr
    phone: str | None = None
    password: str
    role: Role
    full_name: str
    preferred_language: str = "en"
    preferred_channel: str = "email"
    # patient
    date_of_birth: str | None = None
    sex: str | None = None
    country: str = "GH"
    region: str | None = None
    city: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_history: str | None = None
    allergies: list[str] = []
    current_medications: list[str] = []
    # professional
    specialty: str | None = None
    qualifications: str | None = None
    years_experience: int = 0
    languages: list[str] = []
    credentials: list[dict] = []  # [{kind, issuer, number, document_key?}]

    @field_validator("password")
    @classmethod
    def strong(cls, v):
        validate_password_strength(v)
        return v

    @field_validator("preferred_language")
    @classmethod
    def lang(cls, v):
        if v not in SUPPORTED_LANGS:
            raise ValueError("unsupported language")
        return v


def _issue(db: Session, user: User, purpose: str, otp: bool = False, minutes: int = 60) -> str:
    raw = new_otp() if otp else new_opaque_token()
    db.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=hash_token(raw),
                        expires_at=utcnow() + timedelta(minutes=minutes)))
    return raw


def _consume(db: Session, raw: str, purpose: str, user_id: int | None = None) -> OneTimeToken:
    q = select(OneTimeToken).where(OneTimeToken.token_hash == hash_token(raw), OneTimeToken.purpose == purpose,
                                   OneTimeToken.used_at.is_(None), OneTimeToken.expires_at > utcnow())
    if user_id:
        q = q.where(OneTimeToken.user_id == user_id)
    t = db.scalar(q)
    if not t:
        raise HTTPException(400, "Invalid or expired token")
    t.used_at = utcnow()
    return t


@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if body.role == Role.admin:
        raise HTTPException(403, "Admin accounts cannot be self-registered")
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    if body.phone and db.scalar(select(User.id).where(User.phone == body.phone)):
        raise HTTPException(409, "Phone number already registered")
    if body.role in PROFESSIONAL_ROLES and not body.credentials:
        raise HTTPException(422, "Professionals must submit at least one licence/registration credential")
    u = User(email=body.email.lower(), phone=body.phone, password_hash=hash_password(body.password), role=body.role,
             full_name=body.full_name, preferred_language=body.preferred_language, preferred_channel=body.preferred_channel)
    db.add(u)
    db.flush()
    if body.role == Role.patient:
        from datetime import date
        dob = date.fromisoformat(body.date_of_birth) if body.date_of_birth else None
        db.add(PatientProfile(user_id=u.id, date_of_birth=dob, sex=body.sex, country=body.country, region=body.region,
                              city=body.city, emergency_contact_name=body.emergency_contact_name,
                              emergency_contact_phone=body.emergency_contact_phone, medical_history=body.medical_history,
                              allergies=body.allergies, current_medications=body.current_medications))
    else:
        db.add(ProviderProfile(user_id=u.id, specialty=body.specialty, qualifications=body.qualifications,
                               years_experience=body.years_experience, languages=body.languages or [body.preferred_language],
                               country=body.country, city=body.city))  # status defaults to PENDING
        db.flush()
        for c in body.credentials:
            if not {"kind", "issuer", "number"} <= c.keys():
                raise HTTPException(422, "credential needs kind, issuer, number")
            db.add(Credential(provider_id=u.id, kind=c["kind"], issuer=c["issuer"], number=c["number"],
                              document_key=c.get("document_key")))
    token = _issue(db, u, "verify_email", minutes=60 * 24)
    notify(db, u, "verify_email", "Verify your email", f"Verification token: {token}", external=True)
    if u.phone:
        notify(db, u, "verify_phone", "Verify your phone", f"Your code: {_issue(db, u, 'verify_phone', otp=True, minutes=10)}", external=False)
    audit(db, u.id, "auth.register", "user", u.id, role=body.role.value)
    db.commit()
    msg = "Registered. Verify your email." + (" Your professional account is pending admin verification." if body.role != Role.patient else "")
    return {"id": u.id, "message": msg}


class VerifyIn(BaseModel):
    token: str


@router.post("/verify-email")
def verify_email(body: VerifyIn, db: Session = Depends(get_db)):
    t = _consume(db, body.token, "verify_email")
    db.get(User, t.user_id).email_verified = True
    db.commit()
    return {"ok": True}


@router.post("/verify-phone")
def verify_phone(body: VerifyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _consume(db, body.token, "verify_phone", user.id)
    user.phone_verified = True
    db.commit()
    return {"ok": True}


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    s = get_settings()
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u and u.locked_until and u.locked_until > utcnow():
        raise HTTPException(429, "Account temporarily locked. Try again later.")
    if not u or not verify_password(body.password, u.password_hash):
        if u:
            u.failed_logins += 1
            if u.failed_logins >= s.max_failed_logins:
                u.locked_until, u.failed_logins = utcnow() + timedelta(minutes=s.lockout_minutes), 0
            audit(db, u.id, "auth.login_failed", "user", u.id)
            db.commit()
        raise HTTPException(401, "Invalid credentials")  # same message for unknown email
    if not u.is_active:
        raise HTTPException(403, "Account disabled")
    u.failed_logins = 0
    audit(db, u.id, "auth.login", "user", u.id)
    db.commit()
    return {"access_token": create_token(u.id, "access", minutes=s.access_token_minutes),
            "refresh_token": create_token(u.id, "refresh", days=s.refresh_token_days), "role": u.role.value}


class RefreshIn(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        uid = decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid refresh token")
    u = db.get(User, uid)
    if not u or not u.is_active:
        raise HTTPException(401, "Account disabled")
    return {"access_token": create_token(u.id, "access", minutes=get_settings().access_token_minutes)}


class ForgotIn(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
def forgot(body: ForgotIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u:
        notify(db, u, "reset_password", "Reset your password", f"Reset token: {_issue(db, u, 'reset_password')}")
        db.commit()
    return {"message": "If that email exists, a reset link has been sent."}  # no account enumeration


class ResetIn(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strong(cls, v):
        validate_password_strength(v)
        return v


@router.post("/reset-password")
def reset(body: ResetIn, db: Session = Depends(get_db)):
    t = _consume(db, body.token, "reset_password")
    u = db.get(User, t.user_id)
    u.password_hash, u.failed_logins, u.locked_until = hash_password(body.new_password), 0, None
    audit(db, u.id, "auth.password_reset", "user", u.id)
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(u: User = Depends(current_user), db: Session = Depends(get_db)):
    out = {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role.value,
           "preferred_language": u.preferred_language, "email_verified": u.email_verified}
    if u.provider:
        out["verification_status"] = u.provider.status.value
    return out


class ProfileIn(BaseModel):
    full_name: str | None = None
    preferred_language: str | None = None
    preferred_channel: str | None = None
    phone: str | None = None
    region: str | None = None
    city: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    medical_history: str | None = None
    allergies: list[str] | None = None
    current_medications: list[str] | None = None


@router.patch("/me")
def update_profile(body: ProfileIn, u: User = Depends(current_user), db: Session = Depends(get_db)):
    d = body.model_dump(exclude_unset=True)
    if "preferred_language" in d and d["preferred_language"] not in SUPPORTED_LANGS:
        raise HTTPException(422, "unsupported language")
    for k in ("full_name", "preferred_language", "preferred_channel", "phone"):
        if k in d:
            setattr(u, k, d.pop(k))
    if u.patient:
        for k, v in d.items():
            setattr(u.patient, k, v)
    audit(db, u.id, "profile.update", "user", u.id, patient_id=u.id if u.patient else None)
    db.commit()
    return {"ok": True}
