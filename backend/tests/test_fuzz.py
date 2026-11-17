"""Hostile-input sweep over every write/read route. The only assertion: the server never answers 5xx.
Run on PostgreSQL for full strength (it rejects NUL bytes and integer overflow that SQLite silently accepts)."""
import re

import pytest

from app.main import app
from .conftest import register_patient, register_pro

SKIP = {("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/files"), ("POST", "/api/v1/ai/transcribe"), ("POST", "/api/v1/payments/webhooks/paystack"),
        ("POST", "/api/v1/auth/forgot-password"), ("POST", "/api/v1/admin/jobs/send-reminders"), ("PUT", "/api/v1/admin/users/{uid}/active")}
HUGE_INT = 99999999999999999999
STRINGS = ["A" * 10000, "a\x00b", "‮'; DROP TABLE users;--", "🙂" * 300, ""]


def resolve(schema, spec):
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def gen(schema, spec, variant, depth=0):
    schema = resolve(schema, spec)
    if "anyOf" in schema:
        opts = [o for o in schema["anyOf"] if o.get("type") != "null"]
        return gen(opts[0], spec, variant, depth) if opts else None
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        if depth > 4:
            return {}
        return {k: gen(v, spec, variant, depth + 1) for k, v in schema.get("properties", {}).items()}
    if t == "array":
        return [gen(schema.get("items", {}), spec, variant, depth + 1)] * (60 if variant % 2 == 0 else 2)
    if t == "string":
        return STRINGS[variant % len(STRINGS)]
    if t == "integer":
        return [HUGE_INT, -1, 0, 2**31][variant % 4]
    if t == "number":
        return [1e308, -1e308, 0.0][variant % 3]
    if t == "boolean":
        return True
    return None


def fill_path(path, variant):
    return re.sub(r"\{[^}]+\}", lambda m: [str(HUGE_INT), "1", "-5", "abc%00"][variant % 4], path)


@pytest.fixture()
def tokens(client, admin):
    pat = register_patient(client)
    uid, doc = register_pro(client, admin)
    lab_id, lab = register_pro(client, admin, role="lab", email="lab@x.com")
    ph_id, pharm = register_pro(client, admin, role="pharmacist", email="rx@x.com")
    fac_id, fac = register_pro(client, admin, role="facility_admin", email="fac@x.com")
    return {"admin": admin, "patient": pat, "doctor": doc, "lab": lab, "pharmacist": pharm, "facility": fac}


def test_no_server_errors_under_hostile_input(client, tokens):
    spec = app.openapi()
    failures = []
    count = 0
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            m = method.upper()
            if m not in ("GET", "POST", "PUT", "PATCH", "DELETE") or (m, path) in SKIP:
                continue
            body_schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            for variant in range(4):
                url = fill_path(path, variant)
                params = {p["name"]: (STRINGS[variant % len(STRINGS)] if p["schema"].get("type") == "string" else HUGE_INT)
                          for p in op.get("parameters", []) if p["in"] == "query"}
                headers_extra = {"Idempotency-Key": "fuzz-key-0000%d" % variant} if "checkout" in path else {}
                for role, h in tokens.items():
                    kw = {"params": params}
                    if body_schema is not None:
                        kw["json"] = gen(body_schema, spec, variant)
                    try:
                        r = client.request(m, url, headers={**h, **headers_extra}, **kw)
                    except Exception as e:  # an unhandled exception inside the app also counts
                        failures.append(f"{role} {m} {path} v{variant}: EXC {type(e).__name__}: {str(e)[:80]}")
                        continue
                    count += 1
                    if r.status_code >= 500 and r.status_code not in (501, 503):  # 501/503 = deliberate "feature unavailable" answers
                        failures.append(f"{role} {m} {path} v{variant} -> {r.status_code}")
    assert not failures, f"{len(failures)} server errors (of {count} requests):\n" + "\n".join(sorted(set(failures))[:80])
    assert count > 2000, f"fuzz sweep sent only {count} requests"
