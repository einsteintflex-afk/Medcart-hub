"""Database schema. Money is integer pesewas; credits are integer tenths of a unit."""
import enum
from datetime import datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, utcnow


class Role(str, enum.Enum):
    patient = "patient"
    pharmacist = "pharmacist"
    doctor = "doctor"
    nurse = "nurse"
    lab = "lab"
    facility_admin = "facility_admin"
    admin = "admin"


PROFESSIONAL_ROLES = {Role.pharmacist, Role.doctor, Role.nurse, Role.lab, Role.facility_admin}


class VerificationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role))
    full_name: Mapped[str] = mapped_column(String(200))
    preferred_language: Mapped[str] = mapped_column(String(8), default="en")
    preferred_channel: Mapped[str] = mapped_column(String(16), default="email")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    patient: Mapped["PatientProfile | None"] = relationship(back_populates="user", uselist=False)
    provider: Mapped["ProviderProfile | None"] = relationship(back_populates="user", uselist=False,
                                                              foreign_keys="ProviderProfile.user_id")


class OneTimeToken(Base):
    """Email-verification, phone OTP and password-reset tokens (stored hashed)."""
    __tablename__ = "one_time_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(32))  # verify_email | verify_phone | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)


class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    date_of_birth: Mapped[datetime | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str] = mapped_column(String(2), default="GH")
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(200))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))
    medical_history: Mapped[str | None] = mapped_column(Text)
    allergies: Mapped[list] = mapped_column(JSON, default=list)
    current_medications: Mapped[list] = mapped_column(JSON, default=list)
    user: Mapped[User] = relationship(back_populates="patient")


class ProviderProfile(Base):
    __tablename__ = "provider_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus), default=VerificationStatus.pending)
    specialty: Mapped[str | None] = mapped_column(String(120), index=True)
    qualifications: Mapped[str | None] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    years_experience: Mapped[int] = mapped_column(Integer, default=0)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    country: Mapped[str] = mapped_column(String(2), default="GH")
    city: Mapped[str | None] = mapped_column(String(100))
    rating_avg: Mapped[float] = mapped_column(Float, default=0)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    review_note: Mapped[str | None] = mapped_column(Text)
    can_prescribe: Mapped[bool] = mapped_column(Boolean, default=False)  # set by admin after verification
    user: Mapped[User] = relationship(back_populates="provider", foreign_keys=[user_id])


class Credential(Base):
    __tablename__ = "credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.user_id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # licence | degree | national_id | ...
    issuer: Mapped[str] = mapped_column(String(200))  # e.g. Medical and Dental Council, Pharmacy Council
    number: Mapped[str] = mapped_column(String(100))
    document_key: Mapped[str | None] = mapped_column(String(500))  # object-storage key
    expires_on: Mapped[datetime | None] = mapped_column(Date)
    status: Mapped[VerificationStatus] = mapped_column(Enum(VerificationStatus), default=VerificationStatus.pending)
    __table_args__ = (UniqueConstraint("issuer", "number", name="uq_credential_issuer_number"),)


class Availability(Base):
    __tablename__ = "availability"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("provider_profiles.user_id"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0=Mon
    start_minute: Mapped[int] = mapped_column(Integer)
    end_minute: Mapped[int] = mapped_column(Integer)


class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # hospital|clinic|pharmacy|laboratory|diagnostic|specialist
    address: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(2), default="GH")
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    services: Mapped[list] = mapped_column(JSON, default=list)
    specialties: Mapped[list] = mapped_column(JSON, default=list)
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    has_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


# ---------------------------------------------------------------- consultations / appointments
class ConsultStatus(str, enum.Enum):
    awaiting_payment = "awaiting_payment"
    requested = "requested"
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    rejected = "rejected"
    cancelled = "cancelled"
    refunded = "refunded"


class Consultation(Base):
    __tablename__ = "consultations"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_role: Mapped[Role] = mapped_column(Enum(Role))
    channel: Mapped[str] = mapped_column(String(8))  # text|audio|video
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    concern: Mapped[str] = mapped_column(Text)
    status: Mapped[ConsultStatus] = mapped_column(Enum(ConsultStatus), default=ConsultStatus.requested)
    fee_pesewas: Mapped[int] = mapped_column(Integer, default=0)
    share_records: Mapped[bool] = mapped_column(Boolean, default=False)
    language: Mapped[str] = mapped_column(String(8), default="en")
    interpretation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    room_id: Mapped[str | None] = mapped_column(String(64))
    clinical_note: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class ConsultMessage(Base):
    __tablename__ = "consult_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="en")
    machine_translated: Mapped[bool] = mapped_column(Boolean, default=False)  # UI must label these
    attachment_key: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    prescriber_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    items: Mapped[list] = mapped_column(JSON)  # [{drug,dose,frequency,duration,instructions}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"))
    from_provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_provider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    to_facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|confirmed|cancelled|completed
    reason: Mapped[str | None] = mapped_column(Text)
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"))
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------- health data
class VitalReading(Base):
    __tablename__ = "vital_readings"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    value: Mapped[float] = mapped_column(Float)
    value2: Mapped[float | None] = mapped_column(Float)  # diastolic for BP
    unit: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(24), default="manual")  # manual|bluetooth:<device>
    abnormal: Mapped[bool] = mapped_column(Boolean, default=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    __table_args__ = (Index("ix_vitals_patient_kind_time", "patient_id", "kind", "measured_at"),)


class HealthRecord(Base):
    __tablename__ = "health_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    document_key: Mapped[str | None] = mapped_column(String(500))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recorded_on: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccessGrant(Base):
    """Patient-controlled permission for a provider to read selected record categories."""
    __tablename__ = "access_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    categories: Mapped[list] = mapped_column(JSON)  # ["*"] or specific categories, "vitals" included
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Medication(Base):
    __tablename__ = "medications"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    dose: Mapped[str | None] = mapped_column(String(80))
    times_of_day: Mapped[list] = mapped_column(JSON, default=list)  # ["08:00","20:00"]
    start_date: Mapped[datetime | None] = mapped_column(Date)
    end_date: Mapped[datetime | None] = mapped_column(Date)
    remaining_doses: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LabRequest(Base):
    __tablename__ = "lab_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    facility_id: Mapped[int | None] = mapped_column(ForeignKey("facilities.id"))
    tests: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="requested")  # requested|scheduled|resulted
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime)
    result_text: Mapped[str | None] = mapped_column(Text)
    result_document_key: Mapped[str | None] = mapped_column(String(500))
    resulted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- content & credits
class ContribStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    withdrawn = "withdrawn"


class Contribution(Base):
    __tablename__ = "contributions"
    id: Mapped[int] = mapped_column(primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # article|research|education|answer|campaign
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(8), default="en")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[ContribStatus] = mapped_column(Enum(ContribStatus), default=ContribStatus.draft)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class CreditEntry(Base):
    """Append-only ledger. Never update or delete rows; correct with a reversal entry."""
    __tablename__ = "credit_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(16))  # award|reversal|adjustment|redemption
    amount_tenths: Mapped[int] = mapped_column(Integer)  # signed
    contribution_id: Mapped[int | None] = mapped_column(ForeignKey("contributions.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("contribution_id", "entry_type", name="uq_credit_once_per_contribution"),)


class RenewalBenefit(Base):
    __tablename__ = "renewal_benefits"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    credits_redeemed_tenths: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------- payments
class PaymentStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # patient_subscription|consultation|pro_subscription
    consultation_id: Mapped[int | None] = mapped_column(ForeignKey("consultations.id"))
    amount_pesewas: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="GHS")
    method: Mapped[str | None] = mapped_column(String(24))  # mtn_momo|telecel_cash|at_money|card
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.pending)
    fincore_txn_id: Mapped[str | None] = mapped_column(String(80))
    failure_reason: Mapped[str | None] = mapped_column(String(200))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True)  # idempotency
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Refund(Base):
    __tablename__ = "refunds"
    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True)
    amount_pesewas: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan: Mapped[str] = mapped_column(String(24))  # patient|professional
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source: Mapped[str] = mapped_column(String(24))  # payment|credit_renewal|admin_grant
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), unique=True)


class Settlement(Base):
    """Per-consultation split between platform and provider."""
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), unique=True)
    gross_pesewas: Mapped[int] = mapped_column(Integer)
    commission_pesewas: Mapped[int] = mapped_column(Integer)
    net_pesewas: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|paid|reversed
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---------------------------------------------------------------- platform
class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(48))
    patient_id: Mapped[int | None] = mapped_column(Integer, index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    about_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Rating(Base):
    __tablename__ = "ratings"
    id: Mapped[int] = mapped_column(primary_key=True)
    consultation_id: Mapped[int] = mapped_column(ForeignKey("consultations.id"), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stars: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)


class Language(Base):
    __tablename__ = "languages"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    stt_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    tts_supported: Mapped[bool] = mapped_column(Boolean, default=False)
    translation_supported: Mapped[bool] = mapped_column(Boolean, default=True)
    human_interpreter_available: Mapped[bool] = mapped_column(Boolean, default=False)
