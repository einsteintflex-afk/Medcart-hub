"""Encrypted file storage with a pluggable backend (local disk here; swap for S3/GCS by implementing the same 3 functions)."""
import hashlib
import secrets
from pathlib import Path

from ..config import get_settings
from ..crypto import decrypt_bytes, encrypt_bytes

# content sniffing: (magic prefix) -> content type. The client-declared type is NEVER trusted.
_MAGIC = [(b"%PDF-", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
          (b"RIFF", "audio/wav"), (b"ID3", "audio/mpeg"), (b"\xff\xfb", "audio/mpeg"), (b"OggS", "audio/ogg"),
          (b"\x1a\x45\xdf\xa3", "audio/webm")]
PURPOSES = {"record", "consult", "lab", "credential", "symptom_photo", "voice"}


class UploadError(ValueError):
    pass


def sniff(data: bytes) -> str:
    for magic, ctype in _MAGIC:
        if data.startswith(magic):
            if magic == b"RIFF" and data[8:12] != b"WAVE":
                break  # RIFF but not WAV (e.g. AVI/WEBP) -> rejected
            return ctype
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    raise UploadError("Unsupported file type. Allowed: PDF, PNG, JPEG, and audio (WAV, MP3, OGG, WebM, M4A).")


def _path(key: str) -> Path:
    root = Path(get_settings().upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    p = (root / key[:2] / key).resolve()
    if root not in p.parents:  # defence in depth against path traversal
        raise UploadError("bad key")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save(data: bytes) -> tuple[str, str, str]:
    """Returns (key, content_type, sha256)."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    if not data:
        raise UploadError("Empty file")
    if len(data) > limit:
        raise UploadError(f"File too large (max {get_settings().max_upload_mb} MB)")
    ctype = sniff(data)
    key = secrets.token_hex(24)
    _path(key).write_bytes(encrypt_bytes(data))
    return key, ctype, hashlib.sha256(data).hexdigest()


def load(key: str) -> bytes:
    if not key.isalnum():
        raise UploadError("bad key")
    return decrypt_bytes(_path(key).read_bytes())
