"""Scheduled notifications. Call `run_all` from a cron/Celery-beat job (e.g. every 15 minutes)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Appointment, Medication, Subscription
from .notifications import notify


def appointment_reminders(db: Session) -> int:
    n = 0
    for a in db.scalars(select(Appointment).where(Appointment.status == "confirmed", Appointment.reminder_sent.is_(False),
                                                  Appointment.starts_at > utcnow(), Appointment.starts_at <= utcnow() + timedelta(hours=24))):
        for uid in filter(None, (a.patient_id, a.provider_id)):
            notify(db, uid, "appointment_reminder", "Appointment reminder", f"Tomorrow/today at {a.starts_at:%Y-%m-%d %H:%M}")
        a.reminder_sent = True
        n += 1
    return n


def subscription_expiry(db: Session) -> int:
    n = 0
    soon = utcnow() + timedelta(days=3)
    for s in db.scalars(select(Subscription).where(Subscription.expires_at > utcnow(), Subscription.expires_at <= soon)):
        later = db.scalar(select(Subscription.id).where(Subscription.user_id == s.user_id, Subscription.plan == s.plan,
                                                        Subscription.expires_at > soon).limit(1))
        if not later:
            notify(db, s.user_id, "subscription_expiry", "Subscription ending soon", f"Your plan ends on {s.expires_at:%Y-%m-%d}. Renew to keep access.")
            n += 1
    return n


def refill_reminders(db: Session) -> int:
    n = 0
    for m in db.scalars(select(Medication).where(Medication.active, Medication.remaining_doses.is_not(None), Medication.remaining_doses <= 7)):
        notify(db, m.patient_id, "refill", "Time to refill", f"{m.name}: about {m.remaining_doses} doses left.", external=False)
        n += 1
    return n


def run_all(db: Session) -> dict:
    r = {"appointments": appointment_reminders(db), "subscriptions": subscription_expiry(db), "refills": refill_reminders(db)}
    db.commit()
    return r
