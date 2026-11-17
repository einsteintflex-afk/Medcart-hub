# MedCart — Digital Healthcare Platform (Ghana-first)

FastAPI + PostgreSQL backend, React/TypeScript (PWA) frontend, WebRTC calls, Paystack payments.

## Run locally
```
cd backend && pip install -r requirements.txt
export MEDCART_DATABASE_URL=sqlite:///./dev.db MEDCART_PAYSTACK_SECRET_KEY=sk_test_x   # simulator payments
python -m scripts.seed            # DEV demo data (password for all: Demo-Passw0rd!)
uvicorn app.main:app --port 8000
cd ../frontend && npm i && npm run dev   # http://localhost:5173
```
Demo logins (`@example.com`): `patient@`, `doctor@`, `pharmacist@`, `lab@`, `facility@`, `pending.doctor@`, `admin@`.
In simulator mode the "Pay" buttons show a confirm dialog standing in for the Paystack checkout page.

## Deploy (production)
1. Copy `.env.example` → `.env`, fill every value. The API **refuses to start** in production with a default JWT secret, no encryption key, simulator payments, SQLite, or localhost CORS.
2. `docker compose up -d --build` (runs `alembic upgrade head`, then the API; web served by nginx on :80 — put TLS in front).
3. Create the first admin: `docker compose exec api python -m scripts.create_admin --email you@org.com --name "Your Name"`.
4. Paystack dashboard: webhook URL `https://<host>/api/v1/payments/webhooks/paystack`; enable Ghana mobile money + cards.
5. Calls: run a TURN server (coturn) and set `MEDCART_TURN_URLS` / `MEDCART_TURN_SECRET`; without TURN, calls fail for some mobile users.
6. Back up PostgreSQL **and** the `uploads` volume **and** the encryption keys (losing the keys makes health data and files unreadable).
7. Run the reminder scheduler: it runs in-process when `MEDCART_SCHEDULER_ENABLED=true` (use one API replica for it, or call `POST /admin/jobs/send-reminders` from cron).

## Who can do what
| Role | Can | Cannot |
|---|---|---|
| Patient | own records, vitals, meds, files; book/pay; share records per professional (time-limited, revocable); see who accessed their data | see anyone else's data |
| Doctor | accept/decline consults, chat/call, notes, referrals, lab requests; prescribe **only if admin enabled** `can_prescribe`; view patient data **only with patient grant** | act before admin verification; read ungranted records |
| Pharmacist | consults, medication history (with grant), referrals | prescribe |
| Nurse | appointments, shared patient data (with grant), contributions | consult as a paid service |
| Lab | lab queue, verified result upload (text + file) | see unrelated patients |
| Facility admin | manage own facility + its appointments; listing hidden until admin verifies | edit other facilities |
| Admin | verify professionals, moderate content, refunds, reports, audit, credits | read clinical chats/records/files (metadata only) |

## How this was verified (all run in this repo)
- **76 API tests** (`cd backend && pytest`), passing on **both SQLite and PostgreSQL 16** (`MEDCART_DATABASE_URL=postgresql+psycopg://… pytest`).
- **Authorization sweep**: every one of 133 HTTP routes is proven to reject unauthenticated callers and wrong roles (a deliberately unprotected route is detected).
- **Fuzz sweep**: ~3,000 hostile requests (NUL bytes, 10KB strings, integer overflow, huge arrays) × every route × 6 roles → zero server errors on PostgreSQL.
- **Migrations**: `alembic upgrade head` → `check` (no drift) → `downgrade base` → `upgrade head`, on PostgreSQL.
- **Browser tests** (Playwright): every page for all roles; full paid-consultation journey; a real two-browser WebRTC video call with received frames; file/voice/translation/registration/logout; no horizontal scroll on 14 pages at 390px.
- **Accessibility**: axe-core WCAG 2 A/AA across every page of every role: 0 violations (automated checks cover only part of accessibility — do a manual screen-reader pass).
- **Static**: bandit (no medium/high), `npm audit` (0 production vulnerabilities), secrets scan, lint for undefined names.

## What still needs humans / real-world validation (not code)
1. **Paystack live mode** has not touched Paystack's real servers; run end-to-end with `sk_test_` keys first.
2. **Language vendors**: translation/STT/TTS run through a provider interface (Google adapter included, verified only against mocks). Twi, Fante and Hausa **speech** is disabled until validated with native speakers; Twi/Hausa/Fante UI strings and emergency wording need review by native-speaking clinicians.
3. **Clinical sign-off**: vital thresholds, emergency keywords, the drug formulary and interaction table are illustrative. License a drug database; have clinicians review.
4. **Legal/regulatory**: Ghana Data Protection Act registration, Medical & Dental Council / Pharmacy Council telemedicine rules, e-prescribing legality, consent/terms text, Bank of Ghana rules for payouts.
5. **Security assurance**: independent penetration test; load/performance testing (not done); WebSocket signalling is in-process (one API replica, or add sticky routing/Redis relay to scale it).
6. **Native mobile app** (React Native) is not built; the web app is mobile-first and installable as a PWA.
7. **Assumptions to confirm**: platform commission 15%, professional subscription GH₵100/mo, pharmacist consult GH₵0 (all `MEDCART_*` settings). Provider payouts are tracked in-app and transferred manually.

## Dashboards
- **Patient** (14 pages): home overview, consultations (search/filter/compare, request, chat, **audio/video call**, photo/document attachments, translation, human-interpreter request, rating),
  appointments, health monitoring (charts, weekly/monthly summaries, CSV), health record (+ uploads) with sharing controls and access history, medications (+interactions, refill/dose reminders),
  labs, drug information + pharmacy directory, facility finder, health education, AI assistant (typed or **voice**, spoken replies), billing/receipts, notifications, settings (language, profile, complaints).
- **Professional** (role-specific menus for doctor, pharmacist, nurse, lab, facility admin): overview, consultation workspace (chat, calls, notes, prescriptions, referrals, follow-ups, translation),
  appointments, patients (only with consent: summary, records, medications, vitals), availability, profile + credential upload & verification status, earnings & subscription,
  contributions + credit ledger + renewal, lab results queue (text + file), facility management. Unverified professionals see only their application.
- **Admin** (17 pages): overview, credential verification (with document viewer), users, content moderation, transactions (+refunds, reconciliation, settlements), subscriptions,
  consultations, appointments, facilities, labs, credits ledger/adjustments, complaints, interpreter requests, languages, reports, audit log, settings.

## Feature summary
Auth (register/verify email/login/lockout/reset/logout-revocation/RBAC, rate-limited), admin-gated professional verification, provider search, consultations
(doctor GH₵200 separate from GH₵60 patient subscription), WebRTC audio/video with ticket-authenticated signalling, appointments with availability checks,
vitals + abnormal alerts + summaries + CSV, EHR with patient-controlled access grants and patient-visible access log, **field-level encryption of health data and encrypted file storage**,
medications + interaction check + scheduled reminders, labs, facility finder, emergency info, notifications, deterministic emergency screening + guarded AI assistant,
speech/translation provider layer with number-fidelity guard and human-interpreter escalation, contribution credits (append-only ledger, 0.8/approval, duplicate/quality rules, reversal,
120-unit renewal computed server-side), Paystack payments (hosted checkout for MoMo/card, server-side verify, HMAC-SHA512 webhooks, idempotency, duplicate-payment protection, refunds,
commission/settlements, reconciliation), Alembic migrations, CI workflow, Docker Compose deployment, installable PWA, 6-language UI.
