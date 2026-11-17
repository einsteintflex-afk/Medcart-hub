"""Create the first (or another) administrator: python -m scripts.create_admin --email you@org.com --name "Your Name"
Password is read from MEDCART_ADMIN_PASSWORD or prompted. Admin accounts cannot be self-registered through the API."""
import argparse
import getpass
import os

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Role, User
from app.security import hash_password, validate_password_strength


def create_admin(db, email: str, password: str, name: str) -> User:
    if db.scalar(select(User.id).where(User.email == email.lower())):
        raise SystemExit(f"A user with email {email} already exists")
    try:
        validate_password_strength(password)
    except ValueError as e:
        raise SystemExit(str(e))
    u = User(email=email.lower(), password_hash=hash_password(password), role=Role.admin, full_name=name, email_verified=True)
    db.add(u)
    db.commit()
    return u


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    pw = os.environ.get("MEDCART_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    with SessionLocal() as db:
        u = create_admin(db, a.email, pw, a.name)
    print(f"Created admin #{u.id} ({u.email})")
