"""Vital-sign thresholds and a SMALL illustrative drug-interaction table.

The interaction table is NOT a clinical database. Production must license a vetted source
(e.g. a commercial drug-interaction API) and have it reviewed by the clinical lead.
"""
from itertools import combinations

UNITS = {"bp": "mmHg", "glucose": "mmol/L", "heart_rate": "bpm", "temperature": "°C", "weight": "kg",
         "spo2": "%", "resp_rate": "breaths/min", "bmi": "kg/m²"}


def is_abnormal(kind: str, v: float, v2: float | None = None) -> bool:
    if kind == "bp":
        return v >= 140 or v < 90 or (v2 is not None and (v2 >= 90 or v2 < 60))
    return {
        "glucose": lambda: v < 3.9 or v > 10.0,
        "heart_rate": lambda: v < 50 or v > 110,
        "temperature": lambda: v < 35.5 or v >= 38.0,
        "spo2": lambda: v < 94,
        "resp_rate": lambda: v < 10 or v > 24,
        "bmi": lambda: v < 18.5 or v >= 30,
    }.get(kind, lambda: False)()


# ILLUSTRATIVE formulary for the info screens. Replace/extend with a licensed source reviewed by a pharmacist.
DRUGS = {
    "paracetamol": {"use": "Pain and fever", "side_effects": ["Rare at normal doses"], "warnings": ["Do not exceed the labelled daily maximum", "Liver damage risk in overdose or with heavy alcohol use"], "ask_pharmacist_if": "you have liver disease, drink alcohol regularly, or take other medicines containing paracetamol"},
    "ibuprofen": {"use": "Pain, inflammation and fever", "side_effects": ["Stomach upset", "Heartburn"], "warnings": ["Take with food", "Avoid in stomach ulcers, kidney disease and late pregnancy"], "ask_pharmacist_if": "you take blood thinners, blood-pressure medicines or have asthma"},
    "amoxicillin": {"use": "Bacterial infections (antibiotic)", "side_effects": ["Diarrhoea", "Nausea", "Rash"], "warnings": ["Do not use if allergic to penicillin", "Finish the course exactly as prescribed"], "ask_pharmacist_if": "you have had a rash or swelling with any antibiotic"},
    "artemether-lumefantrine": {"use": "Uncomplicated malaria", "side_effects": ["Headache", "Dizziness", "Loss of appetite"], "warnings": ["Take with fatty food or milk", "Complete all doses even if you feel better"], "ask_pharmacist_if": "you are pregnant, breastfeeding or have heart rhythm problems"},
    "metformin": {"use": "Type 2 diabetes", "side_effects": ["Nausea", "Diarrhoea", "Metallic taste"], "warnings": ["Take with meals", "Stop and seek care if vomiting/dehydrated"], "ask_pharmacist_if": "you have kidney problems or are having a contrast scan"},
    "amlodipine": {"use": "High blood pressure, angina", "side_effects": ["Ankle swelling", "Flushing", "Headache"], "warnings": ["Do not stop suddenly without advice"], "ask_pharmacist_if": "you take other blood-pressure or heart medicines"},
    "lisinopril": {"use": "High blood pressure, heart failure", "side_effects": ["Dry cough", "Dizziness"], "warnings": ["Swelling of face/lips needs emergency care", "Avoid in pregnancy"], "ask_pharmacist_if": "you take potassium supplements or anti-inflammatory painkillers"},
    "oral rehydration salts": {"use": "Replacing fluid lost in diarrhoea", "side_effects": ["Rare"], "warnings": ["Mix exactly as the packet says", "Seek care for babies, blood in stool or fever"], "ask_pharmacist_if": "the person is very young, elderly or not improving in 24 hours"},
}

INTERACTIONS = {
    frozenset({"warfarin", "aspirin"}): ("major", "Increased bleeding risk."),
    frozenset({"warfarin", "ibuprofen"}): ("major", "Increased bleeding risk."),
    frozenset({"sildenafil", "nitroglycerin"}): ("contraindicated", "Severe drop in blood pressure."),
    frozenset({"metformin", "alcohol"}): ("moderate", "Raised risk of lactic acidosis."),
    frozenset({"ibuprofen", "lisinopril"}): ("moderate", "May reduce blood pressure control and harm kidneys."),
    frozenset({"simvastatin", "clarithromycin"}): ("major", "Raised risk of muscle damage."),
    frozenset({"artemether", "lumefantrine"}): ("info", "Standard combination; take with fatty food."),
}


def check_interactions(drugs: list[str]) -> list[dict]:
    names = sorted({d.strip().lower() for d in drugs if d.strip()})
    out = []
    for a, b in combinations(names, 2):
        hit = INTERACTIONS.get(frozenset({a, b}))
        if hit:
            out.append({"drugs": [a, b], "severity": hit[0], "note": hit[1]})
    return out
