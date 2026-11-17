"""DEV ONLY demo data: python -m scripts.seed  (refuses to run when MEDCART_ENV=production)."""
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.models import (Contribution, ContribStatus, Credential, Facility, Language, PatientProfile, ProviderProfile, Role, User,
                        VerificationStatus)
from app.security import hash_password
from app.services.credits import award_for_contribution, content_hash
from app.db import utcnow

PW = "Demo-Passw0rd!"


def main():
    if get_settings().env == "production":
        raise SystemExit("refusing to seed production")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if db.query(User).filter_by(email="admin@example.com").first():
            print("already seeded"); return
        for code, name in [("en", "English"), ("tw", "Twi"), ("ha", "Hausa"), ("fat", "Fante"), ("fr", "Français"), ("es", "Español")]:
            if not db.get(Language, code):
                db.add(Language(code=code, name=name, stt_supported=code in ("en", "fr", "es"), tts_supported=code in ("en", "fr", "es")))
        def mk(email, role, name, **kw):
            u = User(email=email, password_hash=hash_password(PW), role=role, full_name=name, email_verified=True, phone=kw.pop("phone", None)); db.add(u); db.flush(); return u
        admin = mk("admin@example.com", Role.admin, "Ama Admin")
        pat = mk("patient@example.com", Role.patient, "Kofi Mensah", phone="+233200000010")
        db.add(PatientProfile(user_id=pat.id, country="GH", city="Accra", emergency_contact_name="Abena", emergency_contact_phone="+233200000011", allergies=["penicillin"]))
        def pro(email, role, name, spec, yrs, langs, prescribe=False, status=VerificationStatus.approved):
            u = mk(email, role, name); db.add(ProviderProfile(user_id=u.id, status=status, specialty=spec, years_experience=yrs, languages=langs, city="Accra",
                qualifications="MB ChB" if role == Role.doctor else "PharmD", can_prescribe=prescribe, reviewed_by=admin.id, reviewed_at=utcnow()))
            db.add(Credential(provider_id=u.id, kind="licence", issuer="Ghana Health Professions Council", number=f"GHPC-{u.id:05d}", status=status)); return u
        doc = pro("doctor@example.com", Role.doctor, "Dr. Esi Owusu", "General Practice", 9, ["en", "tw", "fat"], True)
        pro("pharmacist@example.com", Role.pharmacist, "Yaw Boateng, PharmD", "Community Pharmacy", 6, ["en", "tw", "ha"])
        pro("lab@example.com", Role.lab, "Efua Lab Scientist", "Medical Laboratory", 4, ["en"])
        pro("facility@example.com", Role.facility_admin, "Kwame Clinic Admin", "Administration", 3, ["en"])
        pro("pending.doctor@example.com", Role.doctor, "Dr. Pending Applicant", "Paediatrics", 2, ["en", "fr"], status=VerificationStatus.pending)
        for n, k, c, lat, lon, em in [("Korle Bu Teaching Hospital", "hospital", "Accra", 5.5360, -0.2270, True), ("Ridge Hospital", "hospital", "Accra", 5.5600, -0.1960, True),
                                      ("Community Pharmacy Osu", "pharmacy", "Accra", 5.5550, -0.1820, False), ("Lancet Laboratory", "laboratory", "Accra", 5.5900, -0.1700, False)]:
            db.add(Facility(name=n, kind=k, address=f"{c}, Ghana", city=c, latitude=lat, longitude=lon, has_emergency=em, verified=True, phone="030 000 0000",
                            services=["Consultation", "Diagnostics"], specialties=["General"], hours={"Mon-Fri": "08:00-17:00"}))
        body = "Hypertension is common in Ghana. Regular blood pressure checks, reducing salt, staying active and taking prescribed medicines help prevent stroke and heart disease. " * 4
        c = Contribution(author_id=doc.id, kind="article", title="Living well with high blood pressure", body=body, topic="chronic", language="en",
                         content_hash=content_hash("Living well with high blood pressure", body), status=ContribStatus.approved, published_at=utcnow(), reviewer_id=admin.id)
        db.add(c); db.flush(); award_for_contribution(db, c, admin.id)
        db.commit()
        print("seeded. Password for all demo users:", PW)


if __name__ == "__main__":
    main()
