const { chromium } = require('playwright');
const U = 'http://localhost:5173', PW = 'Demo-Passw0rd!';
const step = (n) => console.log('✔', n);
(async () => {
  const b = await chromium.launch(); const errs = [];
  const mk = async (email) => { const c = await b.newContext({ viewport: { width: 1280, height: 900 } }); const p = await c.newPage();
    p.on('pageerror', e => errs.push(email + ' PAGEERROR ' + e.message)); p.on('dialog', d => d.accept());
    p.on('response', r => { if (r.url().includes('/api/v1') && r.status() >= 400) errs.push(`${email} HTTP ${r.status()} ${r.request().method()} ${r.url().replace(/.*v1/, '')}`); });
    await p.goto(U + '/login'); await p.fill('#em', email); await p.fill('#pw', PW); await p.click('button[type=submit]'); await p.waitForSelector('nav a'); return p; };
  const pat = await mk('patient@example.com');
  // 1. subscribe (simulated checkout)
  await pat.click('text=Subscribe — GH₵60/month'); await pat.waitForSelector('.badge:has-text("Active")'); step('patient subscription active after server-verified payment');
  // 2. request doctor
  await pat.goto(U + '/app/consult?role=doctor'); await pat.waitForSelector('article:has-text("Esi Owusu")');
  await pat.click('article:has-text("Esi Owusu") >> text=Request'); await pat.fill('#cc', 'Persistent cough for two weeks');
  await pat.check('text=Share my health record'); await pat.click('text=Continue to payment'); await pat.waitForTimeout(1500);
  step('doctor consultation requested + paid (GH₵200)');
  await pat.goto(U + '/app/consult'); await pat.waitForSelector('td:has-text("requested")'); step('consultation status moved awaiting_payment → requested only after verification');
  // 3. doctor accepts
  const doc = await mk('doctor@example.com'); await doc.goto(U + '/pro/consultations'); await doc.waitForSelector('text=Accept'); await doc.click('button:has-text("Accept")'); await doc.waitForTimeout(500); step('doctor accepted');
  // 4. chat
  await pat.goto(U + '/app/consult'); await pat.click('td a:has-text("#")'); await pat.waitForSelector('input[aria-label=Message]');
  await pat.fill('input[aria-label=Message]', 'Hello doctor, the cough is worse at night'); await pat.click('button:has-text("Send")'); await pat.waitForSelector('.msg.user:has-text("worse at night")'); step('patient message sent');
  await doc.click('a:has-text("#1"), td a'); await doc.waitForSelector('.msg:has-text("worse at night")', { timeout: 8000 }); step('doctor sees patient message');
  await doc.fill('input[aria-label=Message]', 'Thanks. Any fever?'); await doc.click('button:has-text("Send")');
  // 5. complete + prescribe
  await doc.fill('#n', 'Likely viral bronchitis; chest clear.'); await doc.fill('#r', 'Rest, fluids; review if fever or breathlessness.');
  for (const [k, v] of [['drug', 'Amoxicillin'], ['dose', '500mg'], ['frequency', 'TDS'], ['duration', '5 days']]) await doc.fill(`input[aria-label=${k}]`, v);
  await doc.click('button:has-text("Issue prescription")'); await doc.waitForSelector('text=Prescriptions'); step('doctor issued prescription (authorised prescriber)');
  await doc.click('button:has-text("Complete consultation")'); await doc.waitForSelector('text=Clinical summary'); step('consultation completed with documented assessment');
  // 6. patient sees + rates
  await pat.reload(); await pat.waitForSelector('text=Clinical summary'); await pat.waitForSelector('text=Amoxicillin'); await pat.click('button:has-text("Submit rating")'); step('patient sees summary + prescription, rated');
  // 7. earnings
  await doc.goto(U + '/pro/earnings'); await doc.waitForSelector('td:has-text("GH₵170.00")'); step('doctor earnings: GH₵200 − 15% = GH₵170 net');
  // 8. abnormal vital
  await pat.goto(U + '/app/monitoring'); await pat.fill('#v', '182'); await pat.fill('#v2', '112'); await pat.click('button:has-text("Save")'); await pat.waitForSelector('[role=alert]:has-text("Outside usual range")'); step('abnormal BP flagged');
  // 9. emergency AI
  await pat.goto(U + '/app/assistant'); await pat.fill('#q', 'I have chest pain and cannot breathe'); await pat.click('button:has-text("Send")'); await pat.waitForSelector('.msg.emergency:has-text("112")'); step('AI emergency screening shows emergency instructions');
  // 10. records visible to doctor via grant + audit visible to patient
  await doc.goto(U + '/pro/patients'); await doc.click('button:has-text("Kofi")'); await doc.waitForSelector('text=penicillin'); step('doctor sees shared patient summary (allergy: penicillin)');
  await pat.goto(U + '/app/records'); await pat.waitForSelector('td:has-text("patient.summary_read"), td:has-text("record.read")'); step('patient sees access log of who viewed their data');
  console.log(errs.length ? 'ERRORS:\n' + errs.join('\n') : 'No page errors / failed API calls'); await b.close();
})().catch(e => { console.error('FAILED:', e.message.split('\n')[0]); process.exit(1); });
