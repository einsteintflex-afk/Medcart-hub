import os
import tempfile

_dir = tempfile.mkdtemp()
os.environ.setdefault("MEDCART_DATABASE_URL", f"sqlite:///{_dir}/t.db")  # override to run on PostgreSQL
os.environ["MEDCART_PAYSTACK_SECRET_KEY"] = "sk_test_dummy"
os.environ["MEDCART_MIN_CONTRIBUTION_CHARS"] = "50"
os.environ["MEDCART_RATE_LIMIT_ENABLED"] = "false"
os.environ["MEDCART_UPLOAD_DIR"] = os.path.join(_dir, "uploads")

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Role, User
from app.security import hash_password
from app.services.paystack import _sim

PW = "Str0ngPassword!"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    _sim.charges.clear()
    from app import ratelimit
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _login(c, email, pw=PW):
    r = c.post("/api/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def admin(client):
    with SessionLocal() as db:
        db.add(User(email="admin@x.com", password_hash=hash_password(PW), role=Role.admin, full_name="Admin"))
        db.commit()
    return _login(client, "admin@x.com")


def register_patient(c, email="p@x.com"):
    r = c.post("/api/v1/auth/register", json={"email": email, "password": PW, "role": "patient", "full_name": "Pat",
                                              "phone": "+23320" + str(abs(hash(email)) % 10**7).zfill(7), "emergency_contact_phone": "+233200000002"})
    assert r.status_code == 201, r.text
    assert c.post("/api/v1/auth/verify-email", json={"token": r.json()["dev_verify_token"]}).status_code == 200
    return _login(c, email)


def register_pro(c, admin_h, role="doctor", email="d@x.com", approve=True, can_prescribe=True):
    r = c.post("/api/v1/auth/register", json={"email": email, "password": PW, "role": role, "full_name": "Dr D",
                                              "specialty": "General", "languages": ["en", "tw"], "years_experience": 5,
                                              "credentials": [{"kind": "licence", "issuer": "MDC", "number": f"MDC-{email}"}]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert c.post("/api/v1/auth/verify-email", json={"token": r.json()["dev_verify_token"]}).status_code == 200
    h = _login(c, email)
    if approve:
        rr = c.post(f"/api/v1/admin/providers/{uid}/review", headers=admin_h, json={"approve": True, "can_prescribe": can_prescribe})
        assert rr.status_code == 200
    return uid, h


def pay(c, h, purpose, consultation_id=None, key="idem-key-0001"):
    r = c.post("/api/v1/payments/checkout", headers={**h, "Idempotency-Key": key},
               json={"purpose": purpose, "method": "mtn_momo", "consultation_id": consultation_id})
    assert r.status_code == 201, r.text
    return r.json()


def settle_and_verify(c, h, ref):
    _sim.settle(ref)
    return c.post(f"/api/v1/payments/{ref}/verify", headers=h)
