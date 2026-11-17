import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt

from .config import get_settings
from .db import utcnow

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P, dklen=32)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10 or password.lower() == password or not any(c.isdigit() for c in password):
        raise ValueError("Password must be 10+ chars with upper-case, lower-case and a digit")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def new_otp() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def create_token(user_id: int, kind: str, minutes: int | None = None, days: int | None = None) -> str:
    s = get_settings()
    exp = utcnow() + (timedelta(minutes=minutes) if minutes else timedelta(days=days or 0))
    return jwt.encode({"sub": str(user_id), "typ": kind, "exp": exp}, s.jwt_secret, algorithm="HS256")


def decode_token(token: str, kind: str) -> int:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    if payload.get("typ") != kind:
        raise jwt.InvalidTokenError("wrong token type")
    return int(payload["sub"])
