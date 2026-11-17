import time

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Payment, Settlement
from app.services.paystack import _sim
from .conftest import PW, pay, register_patient, register_pro, settle_and_verify

A = "/api/v1"


def _awaiting_consult(client, admin):
    doc, dh = register_pro(client, admin)
    ph = register_patient(client)
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post(f"{A}/consultations", headers=ph, json={"provider_id": doc, "channel": "text", "concern": "x"}).json()
    return doc, dh, ph, c["id"]


def test_second_checkout_for_same_consultation_reuses_pending_payment(client, admin):
    doc, dh, ph, cid = _awaiting_consult(client, admin)
    a = pay(client, ph, "consultation", cid, key="idem-aaaa-0001")
    b = pay(client, ph, "consultation", cid, key="idem-bbbb-0002")  # different idempotency key, same consultation
    assert a["reference"] == b["reference"]


def test_duplicate_paid_consultation_never_pays_provider_twice(client, admin):
    """Even if two payments for one consultation both clear at the gateway, only one settlement exists."""
    doc, dh, ph, cid = _awaiting_consult(client, admin)
    first = pay(client, ph, "consultation", cid, key="idem-aaaa-0001")
    settle_and_verify(client, ph, first["reference"])
    # forge a second payment row for the same consultation (e.g. created by an older client / race)
    with SessionLocal() as db:
        p1 = db.scalar(select(Payment).where(Payment.reference == first["reference"]))
        dup = Payment(reference="MC-dup-123456", idempotency_key="dup-key-000001", user_id=p1.user_id, purpose="consultation",
                      consultation_id=cid, amount_pesewas=p1.amount_pesewas, currency="GHS", method="card")
        db.add(dup)
        db.commit()
    _sim.charges["MC-dup-123456"] = type(_sim.charges[first["reference"]])("sim_dup", "succeeded", 20000, "GHS", "MC-dup-123456")
    assert client.post(f"{A}/payments/MC-dup-123456/verify", headers=ph).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Settlement.id))) == 1
        d = db.scalar(select(Payment).where(Payment.reference == "MC-dup-123456"))
        assert d.failure_reason == "duplicate_payment_needs_refund"
    assert client.get(f"{A}/payments/earnings", headers=dh).json()["pending_net_pesewas"] == 17000


def test_admin_cannot_read_clinical_content(client, admin):
    doc, dh, ph, cid = _awaiting_consult(client, admin)
    pid = client.get(f"{A}/auth/me", headers=ph).json()["id"]
    client.post(f"{A}/records", headers=ph, json={"category": "diagnosis", "title": "Dx", "body": "private"})
    assert client.get(f"{A}/consultations/{cid}/messages", headers=admin).status_code == 404
    assert client.get(f"{A}/consultations/{cid}", headers=admin).status_code == 404
    assert client.get(f"{A}/patients/{pid}/records", headers=admin).status_code == 403
    assert client.get(f"{A}/patients/{pid}/vitals", headers=admin).status_code == 403


def test_registration_input_validation_returns_422_not_500(client):
    base = {"email": "v@x.com", "password": PW, "role": "patient", "full_name": "V"}
    for bad in ({"country": "GHA"}, {"country": "g"}, {"date_of_birth": "not-a-date"}, {"date_of_birth": "2999-01-01"}, {"preferred_channel": "pigeon"},
                {"full_name": "x" * 500}, {"sex": "x" * 50}, {"phone": "y" * 100}, {"allergies": ["a"] * 500}, {"region": "r" * 500}):
        r = client.post(f"{A}/auth/register", json={**base, **bad})
        assert r.status_code == 422, (bad, r.status_code, r.text[:100])


def test_login_timing_does_not_reveal_which_emails_exist(client):
    register_patient(client)
    def t(email):
        s = time.perf_counter()
        client.post(f"{A}/auth/login", json={"email": email, "password": "wrong-password"})
        return time.perf_counter() - s
    known = sorted(t("p@x.com") for _ in range(3))[1]
    unknown = sorted(t(f"nobody{i}@x.com") for i in range(3))[1]
    assert unknown > known * 0.5, (known, unknown)  # unknown emails must also pay the password-hash cost


def test_oversized_json_body_rejected(client):
    r = client.post(f"{A}/auth/login", content=b'{"email":"a@b.co","password":"' + b"x" * (2 * 1024 * 1024) + b'"}', headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_ai_chat_is_rate_limited(client, monkeypatch):
    from app import ratelimit
    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    ratelimit.reset()
    h = register_patient(client)
    codes = [client.post(f"{A}/ai/chat", headers=h, json={"messages": [{"role": "user", "content": "hello"}]}).status_code for _ in range(35)]
    assert 429 in codes and codes[:30] == [200] * 30
    ratelimit.reset()


def test_ws_ticket_expiry_is_timezone_independent(client, admin, monkeypatch):
    import os, jwt
    os.environ["TZ"] = "Pacific/Auckland"; time.tzset()
    try:
        doc, dh = register_pro(client, admin)
        ph = register_patient(client)
        settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
        c = client.post(f"{A}/consultations", headers=ph, json={"provider_id": doc, "channel": "video", "concern": "x"}).json()
        settle_and_verify(client, ph, pay(client, ph, "consultation", c["id"], key="idem-tz-000001")["reference"])
        client.post(f"{A}/consultations/{c['id']}/decision", headers=dh, json={"accept": True})
        t = client.post(f"{A}/consultations/{c['id']}/call-ticket", headers=ph).json()["ticket"]
        exp = jwt.decode(t, get_settings().jwt_secret, algorithms=["HS256"])["exp"]
        assert 20 < exp - time.time() < 60
    finally:
        os.environ["TZ"] = "UTC"; time.tzset()


def test_facility_creation_rejects_bad_types(client, admin):
    uid, fh = register_pro(client, admin, role="facility_admin", email="f@x.com")
    for bad in ({"latitude": "abc"}, {"latitude": 999}, {"services": "notalist"}, {"name": "n" * 500}, {"kind": "spaceship"}):
        r = client.post(f"{A}/facilities/mine", headers=fh, json={"name": "C", "kind": "clinic", "address": "a", **bad})
        assert r.status_code == 422, (bad, r.status_code)
    assert client.post(f"{A}/facilities/mine", headers=fh, json={"name": "C", "kind": "clinic", "address": "a", "latitude": 5.6, "longitude": -0.2}).status_code == 201


def test_create_admin_script_makes_a_working_admin(client):
    from scripts.create_admin import create_admin
    with SessionLocal() as db:
        create_admin(db, "root@x.com", "Sup3r-Secret-Pass", "Root")
        with pytest.raises(SystemExit):
            create_admin(db, "root@x.com", "Sup3r-Secret-Pass", "Root")  # no duplicates
        with pytest.raises(SystemExit):
            create_admin(db, "weak@x.com", "short", "Weak")
    r = client.post(f"{A}/auth/login", json={"email": "root@x.com", "password": "Sup3r-Secret-Pass"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
