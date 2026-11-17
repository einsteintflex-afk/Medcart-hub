from datetime import timedelta

from app.db import SessionLocal, utcnow
from .conftest import pay, register_patient, register_pro, settle_and_verify

A = "/api/v1"


def test_admin_endpoints_forbidden_to_non_admins(client, admin):
    ph = register_patient(client)
    _, dh = register_pro(client, admin)
    for path in ["/admin/users", "/admin/payments", "/admin/consultations", "/admin/settings", "/admin/complaints",
                 "/admin/credits/ledger", "/admin/subscriptions", "/admin/facilities", "/admin/audit-logs", "/admin/reports/trends"]:
        for h in (ph, dh):
            assert client.get(A + path, headers=h).status_code == 403, path
        assert client.get(A + path).status_code == 401, path
        assert client.get(A + path, headers=admin).status_code == 200, path


def test_admin_settings_never_leak_secrets(client, admin):
    s = client.get(A + "/admin/settings", headers=admin).json()
    assert s["paystack_configured"] is True and "sk_test_dummy" not in str(s)


def test_patient_overview_and_pro_overview(client, admin):
    doc, dh = register_pro(client, admin)
    ph = register_patient(client)
    ov = client.get(A + "/patients/me/overview", headers=ph).json()
    assert ov["subscription_active"] is False and ov["active_medications"] == 0
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    assert client.get(A + "/patients/me/overview", headers=ph).json()["subscription_active"] is True
    assert client.get(A + "/patients/me/overview", headers=dh).status_code == 403  # pros can't use patient overview
    po = client.get(A + "/pro/overview", headers=dh).json()
    assert po["pending_requests"] == 0 and po["credit_balance_units"] == 0


def test_patient_summary_requires_grant_and_consult_detail_scoped(client, admin):
    doc, dh = register_pro(client, admin)
    ph = register_patient(client)
    pid = client.get(A + "/auth/me", headers=ph).json()["id"]
    assert client.get(f"{A}/patients/{pid}/summary", headers=dh).status_code == 403
    client.post(A + "/access-grants", headers=ph, json={"provider_id": doc, "categories": ["*"]})
    assert client.get(f"{A}/patients/{pid}/summary", headers=dh).status_code == 200
    assert [p["id"] for p in client.get(A + "/pro/patients", headers=dh).json()] == [pid]
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post(A + "/consultations", headers=ph, json={"provider_id": doc, "channel": "text", "concern": "x"}).json()
    other = register_patient(client, "other@x.com")
    assert client.get(f"{A}/consultations/{c['id']}", headers=other).status_code == 404
    assert client.get(f"{A}/consultations/{c['id']}", headers=ph).json()["room_id"] is None  # not accepted yet


def test_facility_admin_flow(client, admin):
    fid_user, fh = register_pro(client, admin, role="facility_admin", email="fac@x.com")
    r = client.post(A + "/facilities/mine", headers=fh, json={"name": "Care Clinic", "kind": "clinic", "address": "Kumasi", "latitude": 6.7, "longitude": -1.6})
    fid = r.json()["id"]
    assert client.get(A + "/facilities").json() == []  # hidden until verified by admin
    assert client.put(f"{A}/admin/facilities/{fid}/verified", headers=fh, params={"verified": True}).status_code == 403
    client.put(f"{A}/admin/facilities/{fid}/verified", headers=admin, params={"verified": True})
    assert [f["name"] for f in client.get(A + "/facilities").json()] == ["Care Clinic"]
    # another facility admin cannot edit it
    _, fh2 = register_pro(client, admin, role="facility_admin", email="fac2@x.com")
    assert client.patch(f"{A}/facilities/mine/{fid}", headers=fh2, json={"name": "hacked"}).status_code == 404
    assert client.patch(f"{A}/facilities/mine/{fid}", headers=fh, json={"phone": "030 123 4567"}).status_code == 200


def test_complaints_and_subscription_grant(client, admin):
    ph = register_patient(client)
    cid = client.post(A + "/complaints", headers=ph, json={"body": "Late reply"}).json()["id"]
    assert client.get(A + "/admin/complaints", headers=admin).json()[0]["status"] == "open"
    client.post(f"{A}/admin/complaints/{cid}/resolve", headers=admin, params={"note": "ok"})
    assert client.get(A + "/admin/complaints", headers=admin).json()[0]["status"] == "resolved"
    pid = client.get(A + "/auth/me", headers=ph).json()["id"]
    assert client.post(A + "/admin/subscriptions/grant", headers=admin, json={"user_id": pid, "plan": "patient", "reason": " "}).status_code == 422
    client.post(A + "/admin/subscriptions/grant", headers=admin, json={"user_id": pid, "plan": "patient", "reason": "goodwill"})
    assert client.get(A + "/payments/subscription", headers=ph).json()["active"] is True
    assert any(a["action"] == "subscription.grant" for a in client.get(A + "/admin/audit-logs", headers=admin).json())


def test_reminders_job_is_idempotent(client, admin):
    from app.models import Appointment
    ph = register_patient(client)
    pid = client.get(A + "/auth/me", headers=ph).json()["id"]
    with SessionLocal() as db:
        db.add(Appointment(patient_id=pid, starts_at=utcnow() + timedelta(hours=5), status="confirmed"))
        db.commit()
    assert client.post(A + "/admin/jobs/send-reminders", headers=admin).json()["appointments"] == 1
    assert client.post(A + "/admin/jobs/send-reminders", headers=admin).json()["appointments"] == 0
    assert any(n["kind"] == "appointment_reminder" for n in client.get(A + "/notifications", headers=ph).json())


def test_medication_update_scoped_to_owner(client):
    a, b = register_patient(client, "a@x.com"), register_patient(client, "b@x.com")
    mid = client.post(A + "/medications", headers=a, json={"name": "Amlodipine", "remaining_doses": 3}).json()["id"]
    assert client.patch(f"{A}/medications/{mid}", headers=b, json={"active": False}).status_code == 404
    assert client.patch(f"{A}/medications/{mid}", headers=a, json={"remaining_doses": 30}).status_code == 200


def test_dev_simulate_pays_only_own_payment_in_simulator(client):
    a, b = register_patient(client, "a@x.com"), register_patient(client, "b@x.com")
    ref = pay(client, a, "patient_subscription")["reference"]
    assert client.post(f"{A}/payments/dev/simulate/{ref}", headers=b).status_code == 404
    assert client.post(f"{A}/payments/dev/simulate/{ref}", headers=a).status_code == 200
    assert client.get(A + "/payments/subscription", headers=a).json()["active"] is True
