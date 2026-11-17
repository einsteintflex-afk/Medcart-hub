import io
import os
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal, engine, utcnow
from .conftest import PW, _login, pay, register_patient, register_pro, settle_and_verify

A = "/api/v1"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"x" * 64


@pytest.fixture()
def setting(monkeypatch):
    s = get_settings()
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(s, k, v)
    return _set


def up(c, h, data, name="x.png", ctype="image/png", **form):
    return c.post(f"{A}/files", headers=h, files={"file": (name, io.BytesIO(data), ctype)}, data={"purpose": "record", **form})


# ------------------------------------------------------------ encryption at rest
def test_phi_encrypted_in_database_but_readable_via_api(client):
    h = register_patient(client)
    pid = client.get(f"{A}/auth/me", headers=h).json()["id"]
    client.post(f"{A}/records", headers=h, json={"category": "diagnosis", "title": "Dx", "body": "SECRET-HIV-RESULT-123"})
    with engine.connect() as c:
        raw = c.execute(text("select body from health_records")).scalar()
    assert raw.startswith("enc:v1:") and "SECRET" not in raw
    assert client.get(f"{A}/patients/{pid}/records", headers=h).json()[0]["body"] == "SECRET-HIV-RESULT-123"


def test_decrypt_requires_right_key_and_reads_legacy_plaintext(setting):
    from app import crypto
    from cryptography.fernet import Fernet
    k1, k2 = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    setting(data_encryption_keys=k1)
    token = crypto.encrypt("hello")
    setting(data_encryption_keys=f"{k2},{k1}")  # rotation: new key first, old key still decrypts
    assert crypto.decrypt(token) == "hello"
    setting(data_encryption_keys=k2)
    with pytest.raises(RuntimeError):
        crypto.decrypt(token)
    assert crypto.decrypt("legacy plaintext") == "legacy plaintext"
    setting(data_encryption_keys="")


# ------------------------------------------------------------ auth hardening
def test_logout_revokes_access_and_refresh(client):
    register_patient(client)
    r = client.post(f"{A}/auth/login", json={"email": "p@x.com", "password": PW}).json()
    h = {"Authorization": f"Bearer {r['access_token']}"}
    assert client.get(f"{A}/auth/me", headers=h).status_code == 200
    assert client.post(f"{A}/auth/logout", headers=h).status_code == 200
    assert client.get(f"{A}/auth/me", headers=h).status_code == 401
    assert client.post(f"{A}/auth/refresh", json={"refresh_token": r["refresh_token"]}).status_code == 401


def test_password_reset_signs_out_existing_sessions(client):
    register_patient(client)
    r = client.post(f"{A}/auth/login", json={"email": "p@x.com", "password": PW}).json()
    h = {"Authorization": f"Bearer {r['access_token']}"}
    from app.security import hash_token, new_opaque_token
    from app.models import OneTimeToken, User
    from sqlalchemy import select
    tok = new_opaque_token()
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == "p@x.com"))
        db.add(OneTimeToken(user_id=uid, purpose="reset_password", token_hash=hash_token(tok), expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    assert client.post(f"{A}/auth/reset-password", json={"token": tok, "new_password": "NewStr0ngPass!"}).status_code == 200
    assert client.get(f"{A}/auth/me", headers=h).status_code == 401
    assert client.post(f"{A}/auth/reset-password", json={"token": tok, "new_password": "NewStr0ngPass!"}).status_code == 400  # single use


def test_refresh_token_cannot_be_used_as_access(client):
    register_patient(client)
    r = client.post(f"{A}/auth/login", json={"email": "p@x.com", "password": PW}).json()
    assert client.get(f"{A}/auth/me", headers={"Authorization": f"Bearer {r['refresh_token']}"}).status_code == 401


def test_unverified_email_cannot_pay_or_book(client):
    r = client.post(f"{A}/auth/register", json={"email": "u@x.com", "password": PW, "role": "patient", "full_name": "U"})
    h = _login(client, "u@x.com")
    assert client.post(f"{A}/payments/checkout", headers={**h, "Idempotency-Key": "abcdefgh1"}, json={"purpose": "patient_subscription", "method": "card"}).status_code == 403


def test_rate_limit_on_login_and_register(client, setting):
    setting(rate_limit_enabled=True)
    from app import ratelimit
    ratelimit.reset()
    codes = [client.post(f"{A}/auth/login", json={"email": "nobody@x.com", "password": "x"}).status_code for _ in range(23)]
    assert 429 in codes and codes[:20] == [401] * 20
    assert client.post(f"{A}/auth/login", json={"email": "nobody@x.com", "password": "x"}).headers["Retry-After"] == "60"
    ratelimit.reset()


def test_security_headers(client):
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and "no-store" in h["cache-control"]


def test_production_guard_rejects_unsafe_defaults(setting):
    from app.main import production_guard
    setting(env="production")
    with pytest.raises(RuntimeError) as e:
        production_guard()
    msg = str(e.value)
    assert "JWT_SECRET" in msg and "ENCRYPTION" in msg and "PAYSTACK" in msg
    setting(env="development")
    production_guard()  # no error outside production


# ------------------------------------------------------------ files
def test_upload_sniffs_content_not_client_type(client):
    h = register_patient(client)
    r = up(client, h, PNG, "photo.pdf", "application/pdf")  # lying name/type
    assert r.status_code == 201 and r.json()["content_type"] == "image/png"
    assert up(client, h, b"MZ\x90\x00 this is an exe", "a.png", "image/png").status_code == 415
    assert up(client, h, b"<html><script>alert(1)</script>", "a.png", "image/png").status_code == 415
    assert up(client, h, b"RIFF\x00\x00\x00\x00AVI LIST", "a.wav", "audio/wav").status_code == 415  # RIFF but not WAVE
    assert up(client, h, b"", "a.png").status_code == 422


def test_upload_size_limit(client, setting):
    setting(max_upload_mb=1)
    h = register_patient(client)
    assert up(client, h, PDF + b"0" * (1024 * 1024), "big.pdf", "application/pdf").status_code == 413


def test_files_encrypted_on_disk_and_roundtrip(client):
    h = register_patient(client)
    key = up(client, h, PDF + b"PATIENT-NAME-JOHN", "scan.pdf", "application/pdf").json()["key"]
    root = get_settings().upload_dir
    on_disk = open(os.path.join(root, key[:2], key), "rb").read()
    assert b"PATIENT-NAME-JOHN" not in on_disk and not on_disk.startswith(b"%PDF")
    r = client.get(f"{A}/files/{key}", headers=h)
    assert r.status_code == 200 and r.content.endswith(b"PATIENT-NAME-JOHN") and r.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in r.headers["content-disposition"]


def test_file_access_control_and_consent(client, admin):
    doc, dh = register_pro(client, admin)
    owner, other = register_patient(client, "own@x.com"), register_patient(client, "oth@x.com")
    oid = client.get(f"{A}/auth/me", headers=owner).json()["id"]
    key = up(client, owner, PNG).json()["key"]
    assert client.get(f"{A}/files/{key}", headers=other).status_code == 404       # other patient
    assert client.get(f"{A}/files/{key}", headers=dh).status_code == 404          # doctor without consent
    assert client.get(f"{A}/files/{key}", headers=admin).status_code == 404       # admins can't browse medical documents
    assert client.get(f"{A}/files/{key}").status_code == 401
    client.post(f"{A}/access-grants", headers=owner, json={"provider_id": doc, "categories": ["document"]})
    assert client.get(f"{A}/files/{key}", headers=dh).status_code == 200          # with consent
    assert any(a["action"] == "file.read" for a in client.get(f"{A}/access-log", headers=owner).json())
    assert client.get(f"{A}/files/{'../../etc/passwd'}", headers=owner).status_code == 404
    assert client.get(f"{A}/files/{'a' * 48}", headers=owner).status_code == 404


def test_cannot_attach_someone_elses_file(client):
    a, b = register_patient(client, "a@x.com"), register_patient(client, "b@x.com")
    key = up(client, a, PNG).json()["key"]
    r = client.post(f"{A}/records", headers=b, json={"category": "document", "title": "stolen", "document_key": key})
    assert r.status_code == 422
    assert client.post(f"{A}/records", headers=a, json={"category": "document", "title": "mine", "document_key": key}).status_code == 201


def test_credential_documents_visible_only_to_owner_and_admin(client, admin):
    uid, h = register_pro(client, admin, approve=False)
    r = client.post(f"{A}/files", headers=h, files={"file": ("licence.pdf", io.BytesIO(PDF), "application/pdf")}, data={"purpose": "credential"})
    key = r.json()["key"]
    cid = client.post(f"{A}/providers/me/credentials", headers=h, json={"kind": "id", "issuer": "GhanaCard", "number": "GHA-1", "document_key": key}).json()["id"]
    assert client.get(f"{A}/files/{key}", headers=admin).status_code == 200
    other_uid, oh = register_pro(client, admin, email="o@x.com", approve=False)
    assert client.get(f"{A}/files/{key}", headers=oh).status_code == 404
    assert client.get(f"{A}/files/{key}", headers=register_patient(client)).status_code == 404
    pend = client.get(f"{A}/admin/providers/pending", headers=admin).json()
    assert any(c["document_key"] == key for p in pend for c in p["credentials"])
    assert client.post(f"{A}/providers/me/credentials", headers=h, json={"kind": "id", "issuer": "GhanaCard", "number": "GHA-1"}).status_code == 409  # duplicate number
    assert client.post(f"{A}/files", headers=register_patient(client, "pp@x.com"), files={"file": ("l.pdf", io.BytesIO(PDF), "application/pdf")}, data={"purpose": "credential"}).status_code == 403


def _paid_consult(client, admin, channel="video"):
    doc, dh = register_pro(client, admin)
    ph = register_patient(client)
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    c = client.post(f"{A}/consultations", headers=ph, json={"provider_id": doc, "channel": channel, "concern": "cough", "interpretation_enabled": True, "language": "tw"}).json()
    settle_and_verify(client, ph, pay(client, ph, "consultation", c["id"], key="idem-consult-9")["reference"])
    client.post(f"{A}/consultations/{c['id']}/decision", headers=dh, json={"accept": True})
    return doc, dh, ph, c["id"]


def test_consult_attachment_flow(client, admin):
    doc, dh, ph, cid = _paid_consult(client, admin, "text")
    key = client.post(f"{A}/files", headers=ph, files={"file": ("rash.png", io.BytesIO(PNG), "image/png")}, data={"purpose": "symptom_photo", "consultation_id": cid}).json()["key"]
    assert client.get(f"{A}/files/{key}", headers=dh).status_code == 200  # consultation party, no separate grant needed
    assert client.post(f"{A}/consultations/{cid}/messages", headers=ph, json={"body": "see photo", "attachment_key": key}).status_code == 201
    stranger = register_patient(client, "s@x.com")
    assert client.post(f"{A}/files", headers=stranger, files={"file": ("a.png", io.BytesIO(PNG), "image/png")}, data={"purpose": "consult", "consultation_id": cid}).status_code == 404
    assert client.get(f"{A}/files/{key}", headers=stranger).status_code == 404


def test_lab_result_file_goes_to_correct_patient(client, admin):
    lab, lh = register_pro(client, admin, role="lab", email="lab@x.com")
    ph = register_patient(client)
    lid = client.post(f"{A}/lab-requests", headers=ph, json={"tests": ["FBC"]}).json()["id"]
    assert client.post(f"{A}/files", headers=ph, files={"file": ("r.pdf", io.BytesIO(PDF), "application/pdf")}, data={"purpose": "lab", "lab_request_id": lid}).status_code == 403
    key = client.post(f"{A}/files", headers=lh, files={"file": ("r.pdf", io.BytesIO(PDF), "application/pdf")}, data={"purpose": "lab", "lab_request_id": lid}).json()["key"]
    assert client.post(f"{A}/lab-requests/{lid}/result", headers=lh, json={"result_document_key": key}).status_code == 200
    assert client.get(f"{A}/files/{key}", headers=ph).status_code == 200  # patient can read their result
    assert any(r["category"] == "lab" and r["document_key"] == key for r in client.get(f"{A}/patients/{client.get(f'{A}/auth/me', headers=ph).json()['id']}/records", headers=ph).json())


# ------------------------------------------------------------ language
def test_language_none_provider_is_unavailable_not_fake(client):
    h = register_patient(client)
    assert client.post(f"{A}/translate", headers=h, json={"text": "hi", "source": "en", "target": "tw"}).status_code == 503
    caps = client.get(f"{A}/language/capabilities").json()
    assert caps["provider"] == "none" and not any(v["stt"] or v["tts"] or v["translate"] for v in caps["languages"].values())
    assert all(not l["stt"] and not l["tts"] for l in client.get(f"{A}/languages").json())


def test_translation_flags_and_fidelity_guard(client, setting):
    from app.services import language
    setting(language_provider="fake")
    h = register_patient(client)
    ok = client.post(f"{A}/translate", headers=h, json={"text": "Take 2 tablets for 5 days", "source": "en", "target": "tw"}).json()
    assert ok["machine_translated"] and ok["notice"] and ok["needs_human_review"] is False
    assert client.post(f"{A}/translate", headers=h, json={"text": "same", "source": "en", "target": "en"}).json()["machine_translated"] is False
    fat = client.post(f"{A}/translate", headers=h, json={"text": "Take water", "source": "en", "target": "fat"}).json()
    assert fat["needs_human_review"] and "Approximate" in fat["notice"]
    language.fake.drop_numbers = True
    try:
        bad = client.post(f"{A}/translate", headers=h, json={"text": "Take 2 tablets for 5 days", "source": "en", "target": "fr"}).json()
    finally:
        language.fake.drop_numbers = False
    assert bad["needs_human_review"] and bad["missing_numbers"] == ["2", "5"] and "Do not rely" in bad["notice"]


def test_stt_tts_gating_and_emergency_on_transcript(client, setting):
    setting(language_provider="fake")
    h = register_patient(client)
    voice = lambda lang, data=b"ID3I have severe chest pain": client.post(f"{A}/ai/transcribe", headers=h, files={"audio": ("v.mp3", io.BytesIO(data), "audio/mpeg")}, data={"lang": lang})
    r = voice("en")
    assert r.status_code == 200 and r.json()["emergency"] and "112" in r.json()["emergency_message"]
    assert voice("tw").status_code == 501                                   # unvalidated language: refuse rather than guess
    assert client.post(f"{A}/ai/transcribe", headers=h, files={"audio": ("v.exe", io.BytesIO(b"MZ..."), "audio/mpeg")}, data={"lang": "en"}).status_code == 415
    assert client.post(f"{A}/ai/transcribe", headers=h, files={"audio": ("v.png", io.BytesIO(PNG), "audio/mpeg")}, data={"lang": "en"}).status_code == 415
    sp = client.post(f"{A}/ai/speak", headers=h, json={"text": "Take your tablets", "language": "en"})
    assert sp.status_code == 200 and sp.headers["content-type"] == "audio/mpeg"
    assert client.post(f"{A}/ai/speak", headers=h, json={"text": "x", "language": "ha"}).status_code == 501


def test_local_language_chat_screened_via_english_translation(client, setting, monkeypatch):
    from app.services import language
    setting(language_provider="fake")
    h = register_patient(client)
    monkeypatch.setattr(language.fake, "translate", lambda text, s, t: language.Translation("I have chest pain and cannot breathe"))
    r = client.post(f"{A}/ai/chat", headers=h, json={"messages": [{"role": "user", "content": "(twi words)"}], "language": "tw"}).json()
    assert r["emergency"] and not r["llm_used"]


def test_interpreter_request_and_message_translation(client, admin, setting):
    setting(language_provider="fake")
    doc, dh, ph, cid = _paid_consult(client, admin, "text")
    mid = client.post(f"{A}/consultations/{cid}/messages", headers=ph, json={"body": "I take 2 tablets", "language": "en"}).json()["id"]
    t = client.post(f"{A}/consultations/{cid}/messages/{mid}/translate", headers=dh, params={"target": "fr"}).json()
    assert t["machine_translated"] and t["text"].startswith("[fr]")
    assert client.post(f"{A}/consultations/{cid}/messages/{mid}/translate", headers=register_patient(client, "z@x.com"), params={"target": "fr"}).status_code == 404
    assert client.post(f"{A}/consultations/{cid}/interpreter", headers=ph, json={"language": "tw", "reason": "dosage"}).status_code == 201
    rq = client.get(f"{A}/admin/interpreter-requests", headers=admin).json()
    assert rq[0]["language"] == "tw" and rq[0]["status"] == "open"
    client.post(f"{A}/admin/interpreter-requests/{rq[0]['id']}/close", headers=admin, params={"note": "Interpreter booked"})
    assert any(n["kind"] == "interpreter_update" for n in client.get(f"{A}/notifications", headers=ph).json())


# ------------------------------------------------------------ realtime signalling
def test_call_ticket_rules(client, admin):
    doc, dh, ph, cid = _paid_consult(client, admin, "text")
    assert client.post(f"{A}/consultations/{cid}/call-ticket", headers=ph).status_code == 409      # text consult: no call


def test_webrtc_signalling_relay(client, admin):
    from starlette.websockets import WebSocketDisconnect
    doc, dh, ph, cid = _paid_consult(client, admin, "video")
    tp = client.post(f"{A}/consultations/{cid}/call-ticket", headers=ph).json()
    td = client.post(f"{A}/consultations/{cid}/call-ticket", headers=dh).json()
    assert tp["ice_servers"] and tp["ws_path"].endswith(f"/{cid}")
    stranger = register_patient(client, "x@x.com")
    assert client.post(f"{A}/consultations/{cid}/call-ticket", headers=stranger).status_code == 404
    with pytest.raises(WebSocketDisconnect):                                              # no / forged ticket
        with client.websocket_connect(f"{tp['ws_path']}?ticket=garbage"):
            pass
    with client.websocket_connect(f"{tp['ws_path']}?ticket={tp['ticket']}") as pat_ws:
        assert pat_ws.receive_json() == {"type": "joined", "peers": 0}
        with client.websocket_connect(f"{td['ws_path']}?ticket={td['ticket']}") as doc_ws:
            assert doc_ws.receive_json() == {"type": "joined", "peers": 1}
            assert pat_ws.receive_json() == {"type": "peer-joined"}
            pat_ws.send_json({"type": "offer", "data": {"sdp": "v=0..."}})
            assert doc_ws.receive_json() == {"type": "offer", "data": {"sdp": "v=0..."}}
            doc_ws.send_json({"type": "evil", "data": "x"})                               # unknown types are dropped
            doc_ws.send_json({"type": "answer", "data": {"sdp": "a"}})
            assert pat_ws.receive_json() == {"type": "answer", "data": {"sdp": "a"}}
        assert pat_ws.receive_json() == {"type": "peer-left"}
    # a ticket issued for another consultation must not work here
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/v1/ws/consultations/{cid + 1}?ticket={tp['ticket']}"):
            pass


def test_ws_closed_when_consultation_completed(client, admin):
    from starlette.websockets import WebSocketDisconnect
    doc, dh, ph, cid = _paid_consult(client, admin, "audio")
    tp = client.post(f"{A}/consultations/{cid}/call-ticket", headers=ph).json()
    client.post(f"{A}/consultations/{cid}/complete", headers=dh, json={"clinical_note": "n", "recommendation": "r"})
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"{tp['ws_path']}?ticket={tp['ticket']}"):
            pass


def test_turn_credentials_are_ephemeral(setting):
    from app.routers.realtime import ice_servers
    setting(turn_urls=["turn:t.example.com:3478"], turn_secret="s3cret")
    t = [s for s in ice_servers(7) if "username" in s][0]
    assert t["username"].endswith(":7") and int(t["username"].split(":")[0]) > 0 and len(t["credential"]) > 20


# ------------------------------------------------------------ reminders / formulary / consent
def test_medication_reminders_fire_once_per_dose_time(client, admin):
    from zoneinfo import ZoneInfo
    from datetime import datetime
    h = register_patient(client)
    now = datetime.now(ZoneInfo(get_settings().timezone))
    client.post(f"{A}/medications", headers=h, json={"name": "Amlodipine", "dose": "5mg", "times_of_day": [(now - timedelta(minutes=5)).strftime("%H:%M")]})
    client.post(f"{A}/medications", headers=h, json={"name": "Later", "times_of_day": [(now + timedelta(hours=3)).strftime("%H:%M")]})
    assert client.post(f"{A}/admin/jobs/send-reminders", headers=admin).json()["medications"] == 1
    assert client.post(f"{A}/admin/jobs/send-reminders", headers=admin).json()["medications"] == 0
    assert [n for n in client.get(f"{A}/notifications", headers=h).json() if n["kind"] == "medication_reminder"][0]["body"] == "Time to take Amlodipine 5mg"


def test_drug_info_and_pharmacist_medication_access_needs_consent(client, admin):
    ph, = [register_patient(client)]
    pid = client.get(f"{A}/auth/me", headers=ph).json()["id"]
    rx, rh = register_pro(client, admin, role="pharmacist", email="rx@x.com")
    assert client.get(f"{A}/drugs", headers=ph, params={"q": "metformin"}).json()["results"][0]["ask_pharmacist_if"]
    client.post(f"{A}/medications", headers=ph, json={"name": "Metformin", "dose": "500mg"})
    assert client.get(f"{A}/patients/{pid}/medications", headers=rh).status_code == 403
    client.post(f"{A}/access-grants", headers=ph, json={"provider_id": rx, "categories": ["medication"]})
    assert client.get(f"{A}/patients/{pid}/medications", headers=rh).json()[0]["name"] == "Metformin"
    assert client.get(f"{A}/patients/{pid}/medications", headers=ph).status_code == 403  # patients use /medications


def test_urgent_requests_listed_first_for_clinicians(client, admin):
    doc, dh = register_pro(client, admin)
    ph = register_patient(client)
    settle_and_verify(client, ph, pay(client, ph, "patient_subscription")["reference"])
    a = client.post(f"{A}/consultations", headers=ph, json={"provider_id": doc, "channel": "text", "concern": "routine"}).json()["id"]
    b = client.post(f"{A}/consultations", headers=ph, json={"provider_id": doc, "channel": "text", "concern": "urgent!", "urgent": True}).json()["id"]
    assert [c["id"] for c in client.get(f"{A}/consultations", headers=dh).json()] == [b, a]
