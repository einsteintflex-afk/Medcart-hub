# MedCart — Digital Healthcare Platform (Ghana-first)

FastAPI + PostgreSQL backend, React/TypeScript frontend. Run: `docker compose up` (API :8000), `cd frontend && npm i && npm run dev`.
Tests: `cd backend && pip install -r requirements.txt && pytest` (21 tests).

## Implemented
Auth (register/verify/login/lockout/reset/RBAC), admin-gated professional verification, provider search, consultations
(doctor GH₵200 separate from GH₵60 patient subscription), appointments with availability checks, vitals + abnormal alerts +
summaries + CSV, EHR with patient-controlled access grants and patient-visible access log, medications + interaction check,
labs, facility finder, emergency info, notifications, deterministic emergency screening + guarded AI assistant,
contribution credits (append-only ledger, 0.8/approval, duplicate/quality rules, reversal, 120-unit renewal computed server-side),
Fincore payments (server-side verification, HMAC webhooks with replay window, idempotency, refunds, commission/settlements, reconciliation),
admin dashboards/reports/audit logs, 6-language UI shell.

## NOT production-ready yet — required before launch
1. **Fincore API contract** was not provided. `services/fincore.py` follows generic gateway conventions and must be matched to the real API
   (endpoints, signature scheme, MoMo flows). The simulator is blocked when `MEDCART_ENV=production`. Fincore itself (a payment
   system) needs its own licensing/compliance (Bank of Ghana PSP rules) — it is an integration here, not a built ledger.
2. **Regulatory/legal**: Ghana Data Protection Act 2012 (registration with the Data Protection Commission), telemedicine rules of the
   Medical & Dental Council / Pharmacy Council, e-prescribing legality, consent text, terms. Needs counsel.
3. **Clinical sign-off**: vital thresholds, emergency keyword lists, and the drug-interaction table are illustrative. Use a licensed
   interaction database; have clinicians review. Twi/Fante/Hausa emergency lexicons and UI strings need native clinical review.
4. **Unbuilt**: WebRTC video/audio (consultation rows carry `room_id`), STT/TTS and translation vendors (endpoints return 503),
   file-upload storage (`document_key` fields expect object-storage keys), React Native app, Bluetooth devices, SMS/email vendors,
   Alembic migrations, Redis-backed rate limiting/reminder jobs, field-level encryption of PHI at rest, pen-test.
5. **Assumptions to confirm**: platform commission 15%, professional subscription GH₵100/mo, pharmacist consult fee GH₵0.
   All are env-configurable (`MEDCART_*`).
