"""In-app notifications always; email/SMS via pluggable backends (console by default)."""
import logging

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Notification, User

log = logging.getLogger("medcart.notify")


def _send_email(to: str, subject: str, body: str) -> None:
    if get_settings().email_backend == "console":
        log.info("EMAIL to=%s subject=%s", to, subject)
    else:  # plug in SES/SendGrid/etc.
        raise NotImplementedError("configure an email backend")


def _send_sms(to: str, body: str) -> None:
    if get_settings().sms_backend == "console":
        log.info("SMS to=%s", to)
    else:
        raise NotImplementedError("configure an SMS backend")


def notify(db: Session, user: User | int, kind: str, title: str, body: str, *, external: bool = True) -> None:
    u = user if isinstance(user, User) else db.get(User, user)
    if u is None:
        return
    db.add(Notification(user_id=u.id, kind=kind, title=title, body=body))
    if not external:
        return
    try:  # external delivery must never break the business transaction
        if u.preferred_channel == "sms" and u.phone and u.phone_verified:
            _send_sms(u.phone, f"{title}: {body}")
        else:
            _send_email(u.email, title, body)
    except Exception:  # noqa: BLE001
        log.exception("external notification failed for user %s", u.id)
