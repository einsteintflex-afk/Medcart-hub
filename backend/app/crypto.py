"""Field-level encryption for PHI at rest (Fernet / AES-128-CBC + HMAC), with key rotation via MultiFernet.

Stored form: "enc:v1:<token>". Rows written before encryption was enabled (no prefix) are still readable.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import get_settings

log = logging.getLogger("medcart.crypto")
PREFIX = "enc:v1:"
_cached: tuple[str, MultiFernet] | None = None


def _fernet() -> MultiFernet:
    global _cached
    s = get_settings()
    marker = s.data_encryption_keys or f"dev:{s.jwt_secret}"
    if _cached and _cached[0] == marker:
        return _cached[1]
    if s.data_encryption_keys:
        keys = [Fernet(k.strip().encode()) for k in s.data_encryption_keys.split(",") if k.strip()]
    else:
        if s.env == "production":
            raise RuntimeError("MEDCART_DATA_ENCRYPTION_KEYS must be set in production")
        log.warning("Using a DEV-only encryption key derived from the JWT secret")
        keys = [Fernet(base64.urlsafe_b64encode(hashlib.sha256(marker.encode()).digest()))]
    _cached = (marker, MultiFernet(keys))
    return _cached[1]


def encrypt(plain: str) -> str:
    return PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt(stored: str) -> str:
    if not stored.startswith(PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode()).decode()
    except InvalidToken:
        raise RuntimeError("Cannot decrypt stored data: wrong or missing encryption key")


def encrypt_bytes(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken:
        raise RuntimeError("Cannot decrypt stored file: wrong or missing encryption key")


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)
