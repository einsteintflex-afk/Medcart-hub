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
