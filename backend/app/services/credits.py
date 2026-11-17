"""Contribution-credit ledger and professional-subscription renewal benefit.

All eligibility maths happens here on the server. Amounts are integer tenths of a credit unit
(0.8 units == 8 tenths; 120 units == 1200 tenths) so there is no floating-point drift.
"""
import hashlib
import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import (Contribution, ContribStatus, CreditEntry, ProviderProfile, RenewalBenefit,
                      Subscription, VerificationStatus)
from .audit import audit
from .notifications import notify


def content_hash(title: str, body: str) -> str:
    norm = re.sub(r"\W+", " ", f"{title} {body}".lower()).strip()
    return hashlib.sha256(norm.encode()).hexdigest()


def balance_tenths(db: Session, provider_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(CreditEntry.amount_tenths), 0))
                     .where(CreditEntry.provider_id == provider_id)) or 0


def award_for_contribution(db: Session, c: Contribution, actor_id: int) -> CreditEntry | None:
    """Award once per approved contribution. Returns None if rejected by quality/anti-abuse rules."""
    s = get_settings()
    if c.status != ContribStatus.approved:
        return None
    if len(c.body.strip()) < s.min_contribution_chars:
        return None
    dup = db.scalar(select(Contribution.id).where(
        Contribution.content_hash == c.content_hash, Contribution.id != c.id,
        Contribution.status == ContribStatus.approved, Contribution.id < c.id))
    if dup:  # identical/near-identical content already approved earlier
        return None
    entry = CreditEntry(provider_id=c.author_id, entry_type="award", contribution_id=c.id,
                        amount_tenths=s.credit_per_contribution_tenths, actor_id=actor_id,
                        reason=f"Approved {c.kind}")
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except IntegrityError:
        return None  # already awarded (idempotent)
    before = balance_tenths(db, c.author_id) - entry.amount_tenths
    after = before + entry.amount_tenths
    notify(db, c.author_id, "credit_awarded", "Contribution credit awarded",
           f"You earned {s.credit_per_contribution_tenths / 10:.1f} credit units.")
    th = s.credit_renewal_threshold_tenths
    if before < th <= after:
        notify(db, c.author_id, "renewal_eligible", "Renewal benefit unlocked",
               "You have reached 120 credit units. Your next professional subscription month can be renewed free, "
               "subject to verification, good standing, applicable taxes and platform terms.")
    elif before < th * 0.9 <= after:
        notify(db, c.author_id, "renewal_near", "Close to a free renewal",
               "You are within 10% of the 120-credit renewal threshold.")
    return entry


def reverse_award(db: Session, contribution_id: int, actor_id: int, reason: str) -> CreditEntry | None:
    award = db.scalar(select(CreditEntry).where(CreditEntry.contribution_id == contribution_id,
                                                CreditEntry.entry_type == "award"))
    if not award:
        return None
    rev = CreditEntry(provider_id=award.provider_id, entry_type="reversal", contribution_id=contribution_id,
                      amount_tenths=-award.amount_tenths, actor_id=actor_id, reason=reason)
    try:
        with db.begin_nested():
            db.add(rev)
            db.flush()
    except IntegrityError:
        return None
    audit(db, actor_id, "credit.reverse", "credit_ledger", rev.id, reason=reason)
    return rev


def adjust(db: Session, provider_id: int, tenths: int, actor_id: int, reason: str) -> CreditEntry:
    if not reason.strip():
        raise ValueError("reason required")
    e = CreditEntry(provider_id=provider_id, entry_type="adjustment", amount_tenths=tenths,
                    actor_id=actor_id, reason=reason)
    db.add(e)
    db.flush()
    audit(db, actor_id, "credit.adjust", "credit_ledger", e.id, provider_id=provider_id, tenths=tenths, reason=reason)
    return e


def renewal_status(db: Session, provider_id: int) -> dict:
    s = get_settings()
    prof = db.get(ProviderProfile, provider_id)
    bal = balance_tenths(db, provider_id)
    good_standing = bool(prof and prof.status == VerificationStatus.approved)
    eligible = good_standing and bal >= s.credit_renewal_threshold_tenths
    return {
        "balance_units": bal / 10,
        "threshold_units": s.credit_renewal_threshold_tenths / 10,
        "credit_per_contribution": s.credit_per_contribution_tenths / 10,
        "good_standing": good_standing,
        "eligible": eligible,
        "contributions_needed": max(0, -(-(s.credit_renewal_threshold_tenths - bal) // s.credit_per_contribution_tenths)),
        "terms": ("Redeeming 120 credit units gives one free month of the professional subscription, applied to the "
                  "next month after your current subscription ends. Requires verified account in good standing; "
                  "applicable taxes and platform terms apply; credits are non-transferable and non-purchasable; "
                  "credits reversed for fraudulent or withdrawn content reduce your balance."),
    }


def redeem_renewal(db: Session, provider_id: int) -> RenewalBenefit:
    """Backend-computed free renewal. Consumes exactly the threshold and extends the pro subscription by 30 days."""
    s = get_settings()
    st = renewal_status(db, provider_id)
    if not st["eligible"]:
        raise PermissionError("Not eligible for renewal benefit")
    now = utcnow()
    latest = db.scalar(select(func.max(Subscription.expires_at)).where(
        Subscription.user_id == provider_id, Subscription.plan == "professional"))
    start = max(latest, now) if latest else now
    end = start + timedelta(days=30)
    db.add(CreditEntry(provider_id=provider_id, entry_type="redemption",
                       amount_tenths=-s.credit_renewal_threshold_tenths, reason="Free renewal month"))
    db.add(Subscription(user_id=provider_id, plan="professional", starts_at=start, expires_at=end, source="credit_renewal"))
    rb = RenewalBenefit(provider_id=provider_id, credits_redeemed_tenths=s.credit_renewal_threshold_tenths,
                        period_start=start, period_end=end)
    db.add(rb)
    db.flush()
    notify(db, provider_id, "renewal_applied", "Free renewal applied",
           f"Your professional subscription is extended until {end:%Y-%m-%d}.")
    audit(db, provider_id, "credit.redeem", "renewal_benefit", rb.id)
    return rb
