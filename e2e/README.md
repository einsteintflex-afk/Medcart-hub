# Browser tests (Playwright)
Prereqs: API on :8000 (`MEDCART_LANGUAGE_PROVIDER=fake`), web on :5173 (`npm run dev`), a **freshly seeded** DB (`python -m scripts.seed`), `npm i playwright`.
- `smoke.js`    every page for every role: no crashes, no failed API calls
- `journey.js`  subscribe → pay → consult → prescribe → earnings → emergency AI (run on a fresh DB)
- `features.js` real 2-party WebRTC video call, file upload rules, voice, translation, interpreter requests, registration, logout, 390px mobile layout
