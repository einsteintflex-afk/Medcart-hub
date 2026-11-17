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


def medication_due(db: Session, window_minutes: int = 30) -> int:
    """Notify for each dose time that has just passed (within the window) and hasn't been reminded yet."""
    from zoneinfo import ZoneInfo
    from ..config import get_settings
    tz = ZoneInfo(get_settings().timezone)
    now_utc = utcnow()
    now_local = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    n = 0
    for m in db.scalars(select(Medication).where(Medication.active)):
        for t in m.times_of_day or []:
            try:
                hh, mm = (int(x) for x in t.split(":"))
            except ValueError:
                continue
            due_local = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
            due_utc = due_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            if due_utc <= now_utc < due_utc + timedelta(minutes=window_minutes) and (m.last_reminded_at is None or m.last_reminded_at < due_utc):
                notify(db, m.patient_id, "medication_reminder", "Medication reminder", f"Time to take {m.name} {m.dose or ''}".strip())
                m.last_reminded_at = now_utc
                n += 1
                break
    return n


def run_all(db: Session) -> dict:
    r = {"appointments": appointment_reminders(db), "subscriptions": subscription_expiry(db), "refills": refill_reminders(db), "medications": medication_due(db)}
    db.commit()
    return r
