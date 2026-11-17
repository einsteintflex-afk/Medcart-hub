"""Authorization sweep over EVERY route the app exposes: a newly added endpoint without auth fails this test."""
import re

from app.main import app
from .conftest import register_patient, register_pro

PUBLIC = {  # intentionally unauthenticated (each is justified)
    ("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/forgot-password"), ("POST", "/api/v1/auth/reset-password"), ("POST", "/api/v1/auth/verify-email"),
    ("GET", "/api/v1/facilities"), ("GET", "/api/v1/articles"), ("GET", "/api/v1/languages"), ("GET", "/api/v1/language/capabilities"),
    ("GET", "/api/v1/emergency/info"),
    ("POST", "/api/v1/payments/webhooks/paystack"),   # authenticated by HMAC signature, tested separately
    ("GET", "/healthz"),
}


def routes():
    """Every HTTP route, from the OpenAPI schema (stable across FastAPI versions, unlike router internals)."""
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                yield method.upper(), path


def concrete(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def test_every_non_public_route_requires_authentication(client):
    leaks = []
    for m, p in routes():
        if (m, p) in PUBLIC:
            continue
        r = client.request(m, concrete(p), json={} if m in ("POST", "PUT", "PATCH") else None)
        if r.status_code != 401:
            leaks.append(f"{m} {p} -> {r.status_code}")
    assert not leaks, "routes reachable without authentication:\n" + "\n".join(leaks)


def test_admin_and_professional_routes_reject_wrong_roles(client, admin):
    patient = register_patient(client)
    _, doctor = register_pro(client, admin)
    bad = []
    for m, p in routes():
        url = concrete(p)
        kw = {"json": {}} if m in ("POST", "PUT", "PATCH") else {}
        if "/admin/" in p or p.startswith("/api/v1/admin"):
            for who, h in (("patient", patient), ("doctor", doctor)):
                s = client.request(m, url, headers=h, **kw).status_code
                if s != 403:
                    bad.append(f"{who} {m} {p} -> {s}")
        if p.startswith("/api/v1/pro/") or p.startswith("/api/v1/facilities/mine"):
            s = client.request(m, url, headers=patient, **kw).status_code
            if s != 403:
                bad.append(f"patient {m} {p} -> {s}")
    assert not bad, "\n".join(bad)


def test_webhook_rejects_unsigned(client):
    assert client.post("/api/v1/payments/webhooks/paystack", content=b'{"event":"charge.success","data":{"reference":"x"}}').status_code == 401


def test_route_inventory_is_sane():
    n = len(list(routes()))
    assert n > 120, f"unexpectedly few routes: {n}"
    must = {("POST", "/api/v1/payments/checkout"), ("DELETE", "/api/v1/access-grants/{gid}"), ("GET", "/api/v1/admin/audit-logs"), ("POST", "/api/v1/files")}
    assert must <= set(routes()), "sweep is not seeing known routes"
