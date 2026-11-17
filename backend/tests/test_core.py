import json
import time

from app.config import get_settings
from app.db import SessionLocal
from app.models import Facility
from app.services.paystack import _sim, sign
from .conftest import PW, pay, register_patient, register_pro, settle_and_verify


def test_pro_pending_cannot_act_until_approved(client, admin):
    uid, h = register_pro(client, admin, approve=False)
    r = client.put("/api/v1/providers/me/availability", headers=h, json={"slots": []})
    assert r.status_code == 403
    client.post(f"/api/v1/admin/providers/{uid}/review", headers=admin, json={"approve": True})
    assert client.put("/api/v1/providers/me/availability", headers=h, json={"slots": []}).status_code == 200


def test_duplicate_phone_is_409_not_500(client):
    body = {"password": PW, "role": "patient", "full_name": "x", "phone": "+233201111111"}
    assert client.post("/api/v1/auth/register", json={**body, "email": "one@x.com"}).status_code == 201
    assert client.post("/api/v1/auth/register", json={**body, "email": "two@x.com"}).status_code == 409


def test_admin_cannot_self_register(client):
    r = client.post("/api/v1/auth/register", json={"email": "a@x.com", "password": PW, "role": "admin", "full_name": "x"})
    assert r.status_code == 403


def test_lockout_after_failed_logins(client):
    register_patient(client)
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "p@x.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "p@x.com", "password": PW}).status_code == 429


def test_subscription_requires_server_verified_payment(client):
    h = register_patient(client)
    p = pay(client, h, "patient_subscription")
    assert p["amount_pesewas"] == 6000  # GH₵60, set by server
    # Not paid at Paystack yet: verify must NOT activate.
    client.post(f"/api/v1/payments/{p['reference']}/verify", headers=h)
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is False
    settle_and_verify(client, h, p["reference"])
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is True


def test_checkout_idempotent(client):
    h = register_patient(client)
    a = pay(client, h, "patient_subscription", key="same-key-123")
    b = pay(client, h, "patient_subscription", key="same-key-123")
    assert a["reference"] == b["reference"]


def _webhook(client, ref, event="charge.success", txn_id=555, secret=None):
    body = json.dumps({"event": event, "data": {"id": txn_id, "reference": ref}}).encode()
    sig = sign(secret or get_settings().paystack_secret_key, body)
    return client.post("/api/v1/payments/webhooks/paystack", content=body,
                       headers={"x-paystack-signature": sig, "Content-Type": "application/json"})


def test_webhook_signature_and_idempotency(client):
    h = register_patient(client)
    p = pay(client, h, "patient_subscription")
    assert _webhook(client, p["reference"], secret="wrong").status_code == 401
    assert client.post("/api/v1/payments/webhooks/paystack", content=b"{}").status_code == 401  # unsigned
    # Valid signature but Paystack's verify API says not paid: webhook alone must not unlock service.
    assert _webhook(client, p["reference"], txn_id=1).status_code == 200
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is False
    _sim.settle(p["reference"])
    assert _webhook(client, p["reference"], txn_id=2).status_code == 200
    assert _webhook(client, p["reference"], txn_id=2).json()["status"] == "duplicate"
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is True
    from sqlalchemy import func, select
    from app.models import Subscription
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Subscription.id))) == 1  # fulfilled exactly once


def test_webhook_for_unknown_reference_is_ignored(client):
    assert _webhook(client, "not-ours").status_code == 200


def test_live_gateway_mapping_and_signature():
    from app.services.paystack import _STATUS, verify_webhook_signature
    assert _STATUS["success"] == "succeeded" and "abandoned" not in _STATUS  # abandoned stays pending
    body = b'{"event":"charge.success"}'
    assert verify_webhook_signature(body, sign("sk_test_dummy", body))
    assert not verify_webhook_signature(body, sign("sk_test_dummy", body + b" "))
    assert len(sign("k", b"x")) == 128  # HMAC-SHA512 hex


def test_doctor_consult_needs_separate_payment_and_splits_commission(client, admin):
    doc_id, dh = register_pro(client, admin)
    ph = register_patient(client)
    # no subscription -> blocked
    body = {"provider_id": doc_id, "channel": "video", "concern": "cough"}
    assert client.post("/api/v1/consultations", headers=ph, json=body).status_code == 402
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post("/api/v1/consultations", headers=ph, json=body).json()
    assert c["status"] == "awaiting_payment" and c["fee_pesewas"] == 20000  # subscription does not cover it
    # doctor cannot accept an unpaid consultation
    assert client.post(f"/api/v1/consultations/{c['id']}/decision", headers=dh, json={"accept": True}).status_code == 404
    p = pay(client, ph, "consultation", c["id"], key="idem-consult-1")
    settle_and_verify(client, ph, p["reference"])
    assert client.post(f"/api/v1/consultations/{c['id']}/decision", headers=dh, json={"accept": True}).status_code == 200
    e = client.get("/api/v1/payments/earnings", headers=dh).json()
    assert e["pending_net_pesewas"] == 17000 and e["items"][0]["commission"] == 3000  # 15%


def test_refund_reverses_settlement(client, admin):
    doc_id, dh = register_pro(client, admin)
    ph = register_patient(client)
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post("/api/v1/consultations", headers=ph, json={"provider_id": doc_id, "channel": "text", "concern": "x"}).json()
    p = pay(client, ph, "consultation", c["id"], key="idem-consult-2")
    settle_and_verify(client, ph, p["reference"])
    pid = client.get("/api/v1/payments/history", headers=ph).json()[0]
    from app.models import Payment
    from sqlalchemy import select
    with SessionLocal() as db:
        payment_id = db.scalar(select(Payment.id).where(Payment.reference == p["reference"]))
    assert client.post(f"/api/v1/payments/admin/{payment_id}/refund", headers=admin, params={"reason": "declined"}).status_code == 200
    assert p["reference"] in _sim.refunds
    assert client.get("/api/v1/payments/earnings", headers=dh).json()["pending_net_pesewas"] == 0
    assert client.post(f"/api/v1/payments/admin/{payment_id}/refund", headers=admin, params={"reason": "again"}).status_code == 400


def test_amount_mismatch_flagged(client):
    h = register_patient(client)
    p = pay(client, h, "patient_subscription")
    _sim.charges[p["reference"]].amount_pesewas = 100
    _sim.settle(p["reference"])
    r = client.post(f"/api/v1/payments/{p['reference']}/verify", headers=h).json()
    assert r["status"] == "failed"
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is False


# ---------------- contribution credits
BODY = "Evidence based guidance on managing hypertension in primary care settings. " * 3


def _contrib(client, h, title, body=BODY):
    return client.post("/api/v1/contributions", headers=h, json={"kind": "article", "title": title, "body": body}).json()["id"]


def test_credit_award_duplicate_and_reversal(client, admin):
    uid, h = register_pro(client, admin)
    c1 = _contrib(client, h, "Hypertension basics")
    r = client.post(f"/api/v1/admin/contributions/{c1}/moderate", headers=admin, json={"approve": True}).json()
    assert r["credited"] is True
    assert client.get("/api/v1/credits/me", headers=h).json()["balance_units"] == 0.8
    # same content again by same author: published but earns nothing
    c2 = _contrib(client, h, "Hypertension basics")
    r2 = client.post(f"/api/v1/admin/contributions/{c2}/moderate", headers=admin, json={"approve": True}).json()
    assert r2["credited"] is False
    # too short: no credit
    c3 = _contrib(client, h, "Tiny", "short")
    assert client.post(f"/api/v1/admin/contributions/{c3}/moderate", headers=admin, json={"approve": True}).json()["credited"] is False
    # admin withdrawal reverses credit, once
    assert client.post(f"/api/v1/admin/contributions/{c1}/withdraw", headers=admin, params={"reason": "plagiarised"}).json()["credit_reversed"]
    me = client.get("/api/v1/credits/me", headers=h).json()
    assert me["balance_units"] == 0
    assert [e["type"] for e in me["ledger"]] == ["reversal", "award"]  # append-only history retained


def test_renewal_threshold_backend_computed(client, admin):
    uid, h = register_pro(client, admin)
    assert client.post("/api/v1/credits/redeem-renewal", headers=h).status_code == 403
    client.post(f"/api/v1/admin/credits/{uid}/adjust", headers=admin, json={"units_tenths": 1192, "reason": "migration"})
    assert client.get("/api/v1/credits/me", headers=h).json()["eligible"] is False  # 119.2
    c = _contrib(client, h, "Threshold crossing")
    client.post(f"/api/v1/admin/contributions/{c}/moderate", headers=admin, json={"approve": True})
    me = client.get("/api/v1/credits/me", headers=h).json()
    assert me["balance_units"] == 120.0 and me["eligible"]
    assert client.post("/api/v1/credits/redeem-renewal", headers=h).status_code == 200
    me = client.get("/api/v1/credits/me", headers=h).json()
    assert me["balance_units"] == 0 and not me["eligible"]
    assert client.get("/api/v1/payments/subscription", headers=h).json()["active"] is True


def test_adjust_requires_reason_and_admin(client, admin):
    uid, h = register_pro(client, admin)
    assert client.post(f"/api/v1/admin/credits/{uid}/adjust", headers=h, json={"units_tenths": 5000, "reason": "x"}).status_code == 403
    assert client.post(f"/api/v1/admin/credits/{uid}/adjust", headers=admin, json={"units_tenths": 5, "reason": " "}).status_code == 422


# ---------------- records access / audit / safety
def test_records_require_patient_grant(client, admin):
    doc_id, dh = register_pro(client, admin)
    ph = register_patient(client)
    pid = client.get("/api/v1/auth/me", headers=ph).json()["id"]
    client.post("/api/v1/records", headers=ph, json={"category": "diagnosis", "title": "Malaria 2024"})
    assert client.get(f"/api/v1/patients/{pid}/records", headers=dh).status_code == 403
    g = client.post("/api/v1/access-grants", headers=ph, json={"provider_id": doc_id, "categories": ["diagnosis"]}).json()
    r = client.get(f"/api/v1/patients/{pid}/records", headers=dh)
    assert r.status_code == 200 and len(r.json()) == 1
    client.post("/api/v1/records", headers=ph, json={"category": "note", "title": "private note"})
    assert [x["category"] for x in client.get(f"/api/v1/patients/{pid}/records", headers=dh).json()] == ["diagnosis"]
    assert client.get(f"/api/v1/patients/{pid}/vitals", headers=dh).status_code == 403  # grant scoped to diagnosis
    log = client.get("/api/v1/access-log", headers=ph).json()
    assert any(e["action"] == "record.read" and e["actor_id"] == doc_id for e in log)
    client.delete(f"/api/v1/access-grants/{g['id']}", headers=ph)
    assert client.get(f"/api/v1/patients/{pid}/records", headers=dh).status_code == 403


def test_patient_cannot_read_other_patient(client):
    a = register_patient(client, "a@x.com")
    register_patient(client, "b@x.com")
    bid = client.get("/api/v1/auth/me", headers=register_patient.__globals__["_login"](client, "b@x.com")).json()["id"]
    assert client.get(f"/api/v1/patients/{bid}/records", headers=a).status_code == 403


def test_prescribing_needs_authorisation(client, admin):
    doc_id, dh = register_pro(client, admin, can_prescribe=False)
    ph = register_patient(client)
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post("/api/v1/consultations", headers=ph, json={"provider_id": doc_id, "channel": "text", "concern": "x"}).json()
    r = client.post(f"/api/v1/consultations/{c['id']}/prescriptions", headers=dh,
                    json={"items": [{"drug": "x", "dose": "1", "frequency": "od", "duration": "5d"}]})
    assert r.status_code == 403


def test_abnormal_vital_notifies(client):
    h = register_patient(client)
    assert client.post("/api/v1/vitals", headers=h, json={"kind": "bp", "value": 180, "value2": 110}).json()["abnormal"]
    assert not client.post("/api/v1/vitals", headers=h, json={"kind": "bp", "value": 118, "value2": 76}).json()["abnormal"]
    assert any(n["kind"] == "abnormal_reading" for n in client.get("/api/v1/notifications", headers=h).json())
    s = client.get("/api/v1/vitals/summary", headers=h).json()["bp"]
    assert s["count"] == 2 and s["abnormal_count"] == 1


def test_emergency_screening_bypasses_llm(client):
    h = register_patient(client)
    for text, lang in [("I have crushing chest pain and can't breathe", "en"), ("j'ai une douleur à la poitrine", "fr"),
                       ("no puedo respirar", "es")]:
        r = client.post("/api/v1/ai/chat", headers=h, json={"messages": [{"role": "user", "content": text}], "language": lang}).json()
        assert r["emergency"] and not r["llm_used"] and "112" in r["reply"]
    r = client.post("/api/v1/ai/chat", headers=h, json={"messages": [{"role": "user", "content": "mild headache since morning"}]}).json()
    assert not r["emergency"] and "not a doctor" in r["reply"]
    # symptoms revealed earlier in the conversation still trigger
    r = client.post("/api/v1/ai/chat", headers=h, json={"messages": [
        {"role": "user", "content": "my father is unresponsive"}, {"role": "assistant", "content": "?"},
        {"role": "user", "content": "what should I eat"}]}).json()
    assert r["emergency"]


def test_output_filter():
    from app.services.ai_safety import output_is_safe
    assert not output_is_safe("As your doctor, you definitely have malaria. I prescribe 500mg.")
    assert output_is_safe("This can be caused by many things. Please see a doctor today.")


def test_facility_finder_and_interactions(client, admin):
    client.post("/api/v1/admin/facilities", headers=admin, json={"name": "Korle Bu", "kind": "hospital", "address": "Accra",
                "latitude": 5.536, "longitude": -0.227, "has_emergency": True})
    client.post("/api/v1/admin/facilities", headers=admin, json={"name": "Far Clinic", "kind": "clinic", "address": "Tamale",
                "latitude": 9.4, "longitude": -0.85})
    res = client.get("/api/v1/facilities", params={"lat": 5.55, "lon": -0.2, "radius_km": 20}).json()
    assert [f["name"] for f in res] == ["Korle Bu"] and res[0]["directions_url"]
    info = client.get("/api/v1/emergency/info").json()
    assert info["emergency_number"] == "112" and "not an emergency medical service" in info["disclaimer"]
    h = register_patient(client)
    r = client.get("/api/v1/medications/interactions", headers=h, params={"drugs": "Warfarin, Aspirin"}).json()
    assert r["results"][0]["severity"] == "major"


def test_search_lists_only_verified(client, admin):
    register_pro(client, admin, email="ok@x.com")
    register_pro(client, admin, email="pending@x.com", approve=False)
    h = register_patient(client)
    res = client.get("/api/v1/providers", headers=h, params={"language": "tw", "role": "doctor"}).json()
    assert len(res) == 1 and res[0]["registration_verified"] and res[0]["fee_pesewas"] == 20000
