"""Speech-to-text, text-to-speech and translation behind a provider interface.

Honesty rules baked in:
* Capability tables only list language/feature pairs a vendor is known to support. Twi/Hausa/Fante speech
  is NOT enabled by default; turn it on per language only after a native-speaker clinical validation.
* Every translation is labelled machine-generated, and a fidelity guard flags outputs that dropped or
  altered numbers (doses, durations, phone numbers) so the UI can require human review.
"""
import base64
import re
from dataclasses import dataclass

import httpx

from ..config import get_settings


class ProviderUnavailable(Exception):
    pass


# feature support per language code (conservative). Fante (fat) is approximated by Twi (ak) for translation only.
SUPPORT = {
    "stt": {"en", "fr", "es"},
    "tts": {"en", "fr", "es"},
    "translate": {"en", "fr", "es", "tw", "ha", "fat"},
}
GOOGLE_TRANSLATE_CODE = {"tw": "ak", "fat": "ak", "ha": "ha", "en": "en", "fr": "fr", "es": "es"}
GOOGLE_SPEECH_CODE = {"en": "en-GH", "fr": "fr-FR", "es": "es-ES"}
GOOGLE_VOICE_CODE = {"en": "en-GB", "fr": "fr-FR", "es": "es-ES"}
APPROXIMATE = {"fat"}  # translations that go through a related language


@dataclass
class Translation:
    text: str
    approximate: bool = False


class Provider:
    name = "none"

    def transcribe(self, audio: bytes, content_type: str, lang: str) -> tuple[str, float | None]:
        raise ProviderUnavailable("Speech-to-text is not configured")

    def translate(self, text: str, source: str, target: str) -> Translation:
        raise ProviderUnavailable("Translation is not configured")

    def synthesize(self, text: str, lang: str) -> tuple[bytes, str]:
        raise ProviderUnavailable("Text-to-speech is not configured")


class GoogleProvider(Provider):
    name = "google"
    _ENC = {"audio/webm": "WEBM_OPUS", "audio/ogg": "OGG_OPUS", "audio/wav": "LINEAR16", "audio/mpeg": "MP3"}

    def __init__(self):
        self.key = get_settings().google_api_key
        self.http = httpx.Client(timeout=30)

    def _post(self, url: str, payload: dict) -> dict:
        try:
            r = self.http.post(url, params={"key": self.key}, json=payload)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderUnavailable(f"language provider error: {type(e).__name__}")

    def transcribe(self, audio, content_type, lang):
        enc = self._ENC.get(content_type)
        if not enc or lang not in GOOGLE_SPEECH_CODE:
            raise ProviderUnavailable("Unsupported audio format or language")
        cfg = {"encoding": enc, "languageCode": GOOGLE_SPEECH_CODE[lang], "enableAutomaticPunctuation": True}
        if enc == "WEBM_OPUS" or enc == "OGG_OPUS":
            cfg["sampleRateHertz"] = 48000
        d = self._post("https://speech.googleapis.com/v1/speech:recognize", {"config": cfg, "audio": {"content": base64.b64encode(audio).decode()}})
        alts = [r["alternatives"][0] for r in d.get("results", []) if r.get("alternatives")]
        text = " ".join(a.get("transcript", "") for a in alts).strip()
        conf = min((a.get("confidence", 0) for a in alts), default=None)
        return text, conf

    def translate(self, text, source, target):
        d = self._post("https://translation.googleapis.com/language/translate/v2",
                       {"q": text, "source": GOOGLE_TRANSLATE_CODE[source], "target": GOOGLE_TRANSLATE_CODE[target], "format": "text"})
        out = d["data"]["translations"][0]["translatedText"]
        return Translation(out, approximate=source in APPROXIMATE or target in APPROXIMATE)

    def synthesize(self, text, lang):
        d = self._post("https://texttospeech.googleapis.com/v1/text:synthesize",
                       {"input": {"text": text}, "voice": {"languageCode": GOOGLE_VOICE_CODE[lang]}, "audioConfig": {"audioEncoding": "MP3"}})
        return base64.b64decode(d["audioContent"]), "audio/mpeg"


class FakeProvider(Provider):
    """Deterministic provider for tests/dev. NOT a real translator; refused in production."""
    name = "fake"
    drop_numbers = False

    def transcribe(self, audio, content_type, lang):
        return audio.decode("utf-8", "ignore").strip() or "(silence)", 0.9

    def translate(self, text, source, target):
        out = re.sub(r"\d+(\.\d+)?", "", text) if self.drop_numbers else text
        return Translation(f"[{target}] {out}", approximate=source in APPROXIMATE or target in APPROXIMATE)

    def synthesize(self, text, lang):
        return b"ID3" + text.encode(), "audio/mpeg"


fake = FakeProvider()


def get_provider() -> Provider:
    s = get_settings()
    if s.language_provider == "google" and s.google_api_key:
        return GoogleProvider()
    if s.language_provider == "fake" and s.env != "production":
        return fake
    return Provider()


def capabilities() -> dict[str, dict[str, bool]]:
    """Effective per-language capability: what the configured provider can really do."""
    p = get_provider()
    live = p.name != "none"
    return {code: {"stt": live and code in SUPPORT["stt"], "tts": live and code in SUPPORT["tts"],
                   "translate": live and code in SUPPORT["translate"]} for code in ("en", "tw", "ha", "fat", "fr", "es")}


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def check_fidelity(source: str, translated: str) -> list[str]:
    """Numbers (doses, frequencies, durations, phone numbers) must survive translation unchanged."""
    missing = [n for n in _NUM.findall(source) if n not in translated]
    return missing


def translate_clinical(text: str, source: str, target: str) -> dict:
    """Translate with provenance + safety flags. Callers must show `notice` next to the text."""
    if source == target:
        return {"text": text, "machine_translated": False, "needs_human_review": False, "notice": None, "missing_numbers": []}
    if source not in SUPPORT["translate"] or target not in SUPPORT["translate"]:
        raise ProviderUnavailable("Translation between these languages is not supported")
    t = get_provider().translate(text, source, target)
    missing = check_fidelity(text, t.text)
    review = bool(missing) or t.approximate
    notice = "Automatically translated. Confirm dosages, warnings and emergency advice with your clinician or an interpreter."
    if missing:
        notice = "⚠ This translation may have changed numbers (" + ", ".join(missing) + "). Do not rely on it; request a human interpreter."
    elif t.approximate:
        notice = "Approximate automatic translation (no dedicated model for this language). Request a human interpreter for anything important."
    return {"text": t.text, "machine_translated": True, "needs_human_review": review, "notice": notice, "missing_numbers": missing}
