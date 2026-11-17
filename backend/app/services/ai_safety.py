"""Deterministic emergency screening. Runs BEFORE any LLM call and cannot be bypassed by it.

Lexicons cover English, French and Spanish. Twi/Fante/Hausa lexicons are intentionally NOT shipped
here: they must be authored and clinically reviewed by native-speaking clinicians. Until then, input in
those languages is screened after STT->English translation, and every reply carries the emergency footer.
"""
import re

EMERGENCY_PATTERNS = [
    # English
    r"chest (pain|tightness|pressure)", r"can'?t breathe|cannot breathe|difficulty breathing|short(ness)? of breath",
    r"struggling to breathe", r"stroke|face droop|slurred speech|sudden weakness|one side of (my|the) body",
    r"unconscious|passed out|not responding|unresponsive", r"seizure|convuls", r"severe bleeding|bleeding (heavily|won'?t stop)",
    r"suicid|kill myself|end my life|want to die", r"overdose|poison|swallowed (bleach|pills)",
    r"anaphyla|throat (is )?(closing|swelling)|swollen (tongue|lips|face)", r"(coughing|vomiting) blood",
    r"pregnan\w*.*(bleeding|severe pain)", r"baby (is )?(not breathing|blue|limp)",
    # French
    r"douleur (dans la |à la )?poitrine", r"(ne )?peut pas respirer|difficult[ée] à respirer", r"inconscient|convulsion",
    r"saignement (abondant|sévère)", r"suicide|me tuer", r"avc\b|paralysie soudaine",
    # Spanish
    r"dolor (de|en el) pecho", r"no puedo respirar|dificultad para respirar", r"inconsciente|convulsi[oó]n",
    r"sangrado (abundante|severo)", r"suicid|quiero morir", r"derrame cerebral|par[aá]lisis repentina",
]
_RX = re.compile("|".join(f"(?:{p})" for p in EMERGENCY_PATTERNS), re.IGNORECASE)

EMERGENCY_MESSAGE = {
    "en": "This may be a medical emergency. Call emergency services NOW ({number}) or go to the nearest emergency facility immediately. Do not wait for an online reply.",
    "fr": "Il peut s'agir d'une urgence médicale. Appelez les secours MAINTENANT ({number}) ou rendez-vous aux urgences les plus proches. N'attendez pas une réponse en ligne.",
    "es": "Esto puede ser una emergencia médica. Llame a emergencias AHORA ({number}) o acuda al servicio de urgencias más cercano. No espere una respuesta en línea.",
}
FOOTER = {
    "en": "This assistant is not a doctor and does not replace professional care. In an emergency call {number}.",
    "fr": "Cet assistant n'est pas un médecin et ne remplace pas les soins professionnels. En cas d'urgence, appelez le {number}.",
    "es": "Este asistente no es un médico y no sustituye la atención profesional. En una emergencia llame al {number}.",
}


def screen_emergency(text: str) -> bool:
    return bool(_RX.search(text or ""))


def emergency_message(lang: str, number: str) -> str:
    return EMERGENCY_MESSAGE.get(lang, EMERGENCY_MESSAGE["en"]).format(number=number)


def footer(lang: str, number: str) -> str:
    return FOOTER.get(lang, FOOTER["en"]).format(number=number)


_FORBIDDEN_OUTPUT = re.compile(
    r"\bI am (a|your) (licensed )?(doctor|physician|pharmacist)\b|\bas your doctor\b|\byou definitely have\b|"
    r"\bI (prescribe|am prescribing)\b|\b(no need|don'?t need) to (see|visit|call) (a|an|the) (doctor|hospital|emergency)|"
    r"\bwait (a few days|and see) .{0,40}(chest|breath)", re.IGNORECASE)


def output_is_safe(text: str) -> bool:
    return not _FORBIDDEN_OUTPUT.search(text or "")
