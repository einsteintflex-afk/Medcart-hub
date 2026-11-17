# MedCart — Digital Healthcare Platform (Ghana-first)

FastAPI + PostgreSQL backend, React/TypeScript frontend. ## Run locally
```
cd backend && pip install -r requirements.txt
export MEDCART_DATABASE_URL=sqlite:///./dev.db MEDCART_PAYSTACK_SECRET_KEY=sk_test_x   # simulator payments
python -m scripts.seed            # DEV demo data (password for all: Demo-Passw0rd!)
uvicorn app.main:app --port 8000
cd ../frontend && npm i && npm run dev   # http://localhost:5173
```
Demo logins (`@example.com`): `patient@`, `doctor@`, `pharmacist@`, `lab@`, `facility@`, `pending.doctor@`, `admin@`.
In simulator mode the "Pay" buttons show a confirm dialog standing in for the Paystack checkout page.

**Tests:** `cd backend && pytest` (32 API tests). Browser tests (need Playwright, both servers running + seeded DB):
`node e2e/smoke.js` (every page, every role) and `node e2e/journey.js` (subscribe → pay → consult → prescribe → earnings → emergency AI).

## Dashboards
- **Patient** (13 pages): home overview, consultations (search/filter/compare, request, chat, rate), appointments, health monitoring (charts, weekly/monthly
  summaries, CSV), health record + sharing controls + access history, medications (+interactions, refill flags), labs, facility finder, health education,
  AI assistant, billing/receipts, notifications, settings (language, profile, complaints).
- **Professional** (role-specific menus for doctor, pharmacist, nurse, lab, facility admin): overview, consultations workspace (chat, notes, prescriptions,
  referrals, follow-ups), appointments, patients (only with patient consent), availability, profile & verification status, earnings & subscription,
  contributions + credit ledger + renewal, lab results queue, facility management. Unverified professionals see only their application.
- **Admin** (16 pages): overview, credential verification, users, content moderation, transactions (+refunds, reconciliation, settlements), subscriptions,
  consultations, appointments, facilities, labs, credits ledger/adjustments, complaints, languages, reports, audit log, settings.

## Implemented
Auth (register/verify/login/lockout/reset/RBAC), admin-gated professional verification, provider search, consultations
(doctor GH₵200 separate from GH₵60 patient subscription), appointments with availability checks, vitals + abnormal alerts +
summaries + CSV, EHR with patient-controlled access grants and patient-visible access log, medications + interaction check,
labs, facility finder, emergency info, notifications, deterministic emergency screening + guarded AI assistant,
contribution credits (append-only ledger, 0.8/approval, duplicate/quality rules, reversal, 120-unit renewal computed server-side),
Paystack payments (hosted checkout for MoMo/card, server-side verify, HMAC-SHA512 webhooks, idempotency, refunds, commission/settlements, reconciliation),
admin dashboards/reports/audit logs, 6-language UI shell.

## NOT production-ready yet — required before launch
1. **Paystack go-live**: set `MEDCART_PAYMENT_MODE=live` and `MEDCART_PAYSTACK_SECRET_KEY`; in the Paystack dashboard set the webhook URL to
   `https://<api-host>/api/v1/payments/webhooks/paystack` and enable Ghana mobile money (MTN, Telecel, AT) and cards on your business.
   The live client was written from Paystack's public docs and has only been tested against a simulator: run it end-to-end with
   `sk_test_` keys first. Provider payouts are tracked in our `settlements` table and paid out manually/by transfer for now
   (Paystack Transfers or split subaccounts could automate this). The simulator is blocked when `MEDCART_ENV=production`.
2. **Regulatory/legal**: Ghana Data Protection Act 2012 (registration with the Data Protection Commission), telemedicine rules of the
   Medical & Dental Council / Pharmacy Council, e-prescribing legality, consent text, terms. Needs counsel.
3. **Clinical sign-off**: vital thresholds, emergency keyword lists, and the drug-interaction table are illustrative. Use a licensed
   interaction database; have clinicians review. Twi/Fante/Hausa emergency lexicons and UI strings need native clinical review.
4. **Unbuilt**: WebRTC video/audio (consultation rows carry `room_id`), STT/TTS and translation vendors (endpoints return 503),
   file-upload storage (`document_key` fields expect object-storage keys), React Native app, Bluetooth devices, SMS/email vendors,
   Alembic migrations, Redis-backed rate limiting/reminder jobs, field-level encryption of PHI at rest, pen-test.
5. **Assumptions to confirm**: platform commission 15%, professional subscription GH₵100/mo, pharmacist consult fee GH₵0.
   All are env-configurable (`MEDCART_*`).
