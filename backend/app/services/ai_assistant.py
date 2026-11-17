import httpx

from ..config import get_settings
from . import ai_safety

SYSTEM_PROMPT = """You are the MedCart health information assistant for patients in Ghana and other African markets.
You are NOT a doctor, pharmacist or nurse and must never claim to be one.
Rules:
- Give general health education and help the patient prepare for a consultation. Ask 1-3 relevant follow-up questions when symptoms are unclear.
- Never present a possible cause as a confirmed diagnosis; use wording like "this can be caused by".
- Never prescribe, choose or change doses of medicines. You may explain what a medicine is generally used for, common side effects and well-known interactions, and tell the patient to confirm with a pharmacist or doctor.
- Never advise delaying care for severe, sudden or worsening symptoms. If any red-flag symptom appears, tell the patient to seek emergency care now.
- Always state the level of care suggested: self-care, pharmacist, doctor soon, doctor today, or emergency.
- Preserve warnings, uncertainty and dosage text exactly when explaining or translating.
- Reply in the patient's language ({lang}) using simple words suitable for low health literacy.
"""

RECOMMEND_PROFESSIONAL = {
    "en": "Please book a consultation with a verified pharmacist or doctor on MedCart for personal advice.",
    "fr": "Veuillez réserver une consultation avec un pharmacien ou médecin vérifié sur MedCart pour un avis personnalisé.",
    "es": "Reserve una consulta con un farmacéutico o médico verificado en MedCart para recibir asesoramiento personal.",
}


def _call_llm(system: str, history: list[dict]) -> str:
    s = get_settings()
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=40,
                   headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
                   json={"model": s.ai_model, "max_tokens": 700, "system": system, "messages": history})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"])


def respond(history: list[dict], lang: str, country: str = "GH", extra_screen_text: str | None = None) -> dict:
    """history: [{role: user|assistant, content: str}] with the newest user turn last."""
    s = get_settings()
    number = s.emergency_numbers.get(country, "112")
    latest = history[-1]["content"]
    # Screen the whole recent user text, not just the last turn: symptoms may be revealed gradually.
    user_text = " ".join(m["content"] for m in history[-6:] if m["role"] == "user")
    if ai_safety.screen_emergency(user_text) or (extra_screen_text and ai_safety.screen_emergency(extra_screen_text)):
        return {"emergency": True, "reply": ai_safety.emergency_message(lang, number), "care_level": "emergency",
                "llm_used": False, "emergency_number": number}
    foot = ai_safety.footer(lang, number)
    if not s.anthropic_api_key:
        return {"emergency": False, "care_level": "unknown", "llm_used": False, "emergency_number": number,
                "reply": f"{RECOMMEND_PROFESSIONAL.get(lang, RECOMMEND_PROFESSIONAL['en'])}\n\n{foot}"}
    try:
        text = _call_llm(SYSTEM_PROMPT.format(lang=lang), history)
    except Exception:  # noqa: BLE001
        return {"emergency": False, "care_level": "unknown", "llm_used": False, "emergency_number": number,
                "reply": f"{RECOMMEND_PROFESSIONAL.get(lang, RECOMMEND_PROFESSIONAL['en'])}\n\n{foot}"}
    if not ai_safety.output_is_safe(text):
        text = RECOMMEND_PROFESSIONAL.get(lang, RECOMMEND_PROFESSIONAL["en"])
    return {"emergency": False, "care_level": "see_reply", "llm_used": True, "emergency_number": number,
            "reply": f"{text}\n\n{foot}"}
