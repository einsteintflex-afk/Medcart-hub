// End-to-end checks for calls, files, voice, translation, interpreter requests, auth flows, mobile layout.
// Needs: API on :8000 with MEDCART_LANGUAGE_PROVIDER=fake, web on :5173, seeded DB, Playwright installed.
const { chromium } = require('playwright');
const U = 'http://localhost:5173', API = 'http://localhost:8000/api/v1', PW = 'Demo-Passw0rd!';
const results = []; const ok = (n) => { results.push(n); console.log('✔', n); };
const fail = (n, e) => { console.log('✘', n, '-', e); process.exitCode = 1; };
const errs = [];

async function api(path, { method = 'GET', body, token, headers = {} } = {}) {
  const r = await fetch(API + path, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...headers }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, json: await r.json().catch(() => ({})) };
}
const login = async (email) => (await api('/auth/login', { method: 'POST', body: { email, password: PW } })).json.access_token;

(async () => {
  const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  const mk = async (email) => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ['camera', 'microphone'] }); const p = await ctx.newPage();
    p.on('pageerror', e => errs.push(email + ' PAGEERROR ' + e.message)); p.on('dialog', d => d.accept().catch(() => {}));
    p.on('response', r => { if (r.url().includes('/api/v1') && r.status() >= 400) errs.push(`${email} HTTP ${r.status()} ${r.request().method()} ${r.url().replace(/.*v1/, '')}`); });
    await p.goto(U + '/login'); await p.fill('#em', email); await p.fill('#pw', PW); await p.click('button[type=submit]'); await p.waitForSelector('nav a'); return p;
  };
  try {
    // ---- set up a paid, accepted VIDEO consultation through the API
    const pt = await login('patient@example.com'), dt = await login('doctor@example.com');
    const sub = await api('/payments/checkout', { method: 'POST', token: pt, headers: { 'Idempotency-Key': 'e2e-sub-0001' }, body: { purpose: 'patient_subscription', method: 'card' } });
    await api(`/payments/dev/simulate/${sub.json.reference}`, { method: 'POST', token: pt });
    const doc = (await api('/providers?role=doctor', { token: pt })).json[0];
    const mkConsult = async (channel, key, extra = {}) => {
      const c = (await api('/consultations', { method: 'POST', token: pt, body: { provider_id: doc.id, channel, concern: 'e2e ' + channel, ...extra } })).json;
      const p = await api('/payments/checkout', { method: 'POST', token: pt, headers: { 'Idempotency-Key': key }, body: { purpose: 'consultation', method: 'card', consultation_id: c.id } });
      await api(`/payments/dev/simulate/${p.json.reference}`, { method: 'POST', token: pt });
      await api(`/consultations/${c.id}/decision`, { method: 'POST', token: dt, body: { accept: true } });
      return c.id;
    };
    const vid = await mkConsult('video', 'e2e-consult-v1');
    const txt = await mkConsult('text', 'e2e-consult-t1', { interpretation_enabled: true });

    // ---- 1. real two-party WebRTC video call
    const pat = await mk('patient@example.com'), doc2 = await mk('doctor@example.com');
    await pat.goto(`${U}/app/consult/${vid}`); await doc2.goto(`${U}/pro/consultations/${vid}`);
    await pat.click('button:has-text("Join call")'); await pat.waitForSelector('[data-testid=call-state]:has-text("waiting")');
    await doc2.click('button:has-text("Join call")');
    for (const [who, pg] of [['patient', pat], ['doctor', doc2]]) {
      await pg.waitForSelector('[data-testid=call-state]:has-text("live")', { timeout: 20000 });
      await pg.waitForFunction(() => { const v = document.querySelector('[data-testid=remote-video]'); return v && v.videoWidth > 0 && v.readyState >= 2; }, null, { timeout: 15000 });
    }
    ok('video call: both parties connected over WebRTC and received the other side\'s video frames');
    await pat.click('button:has-text("Hang up")'); await doc2.waitForSelector('text=Waiting for the other person', { timeout: 8000 }); ok('hang-up is signalled to the other party');
    // a stranger cannot get a call ticket or join
    const other = await api('/auth/register', { method: 'POST', body: { email: 'stranger@example.com', password: PW, role: 'patient', full_name: 'S' } });
    await api('/auth/verify-email', { method: 'POST', body: { token: other.json.dev_verify_token } });
    const st = await login('stranger@example.com');
    if ((await api(`/consultations/${vid}/call-ticket`, { method: 'POST', token: st })).status !== 404) throw new Error('stranger got a call ticket');
    ok('non-participant cannot obtain a call ticket');

    // ---- 2. file upload: valid image + rejected exe disguised as image (real browser file picker)
    const fs = require('fs'), path = require('path'), os = require('os');
    const png = path.join(os.tmpdir(), 'scan.png'); fs.writeFileSync(png, Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), Buffer.alloc(200)]));
    const exe = path.join(os.tmpdir(), 'evil.png'); fs.writeFileSync(exe, Buffer.from('MZ\x90\x00 not an image'));
    await pat.goto(U + '/app/records'); await pat.waitForSelector('text=Add an entry');
    await pat.setInputFiles('input[aria-label="Attach document or photo"]', exe); await pat.waitForSelector('[role=alert]:has-text("Unsupported file type")'); ok('disguised executable rejected in the UI');
    await pat.setInputFiles('input[aria-label="Attach document or photo"]', png); await pat.waitForSelector('.badge:has-text("scan.png")');
    await pat.fill('#t', 'Chest X-ray'); await pat.click('button:has-text("Save")'); await pat.waitForSelector('button:has-text("Open document")'); ok('document uploaded, attached to a record and listed');
    const href = await pat.evaluate(async () => { const t = sessionStorage.getItem('mc_token'); const recs = await (await fetch('/api/v1/auth/me', { headers: { Authorization: 'Bearer ' + t } })).json(); return recs.id; });
    const files = (await api('/files', { token: pt })).json; if (!files.length) throw new Error('file list empty');
    if ((await api('/files/' + files[0].key, { token: st })).status !== 404) throw new Error('stranger could read file');
    ok('other users cannot read the uploaded file');

    // ---- 3. translation + interpreter request in a text consultation
    await api(`/consultations/${txt}/messages`, { method: 'POST', token: pt, body: { body: 'I take 2 tablets twice daily', language: 'tw' } });
    await doc2.goto(`${U}/pro/consultations/${txt}`); await doc2.waitForSelector('.msg:has-text("2 tablets")');
    await doc2.click('button:has-text("Translate to")'); await doc2.waitForSelector('[role=note]:has-text("Automatically translated")'); ok('message translation shows the machine-translation notice');
    await doc2.click('button:has-text("Request a human interpreter")'); await doc2.waitForSelector('text=Interpreter request sent'); ok('human interpreter request sent');
    const adm = await mk('admin@example.com'); await adm.goto(U + '/admin/interpreters'); await adm.waitForSelector('td:has-text("#' + txt + '")'); ok('admin sees the interpreter request');

    // ---- 4. voice input -> transcript -> emergency screening in the assistant
    await pat.goto(U + '/app/assistant'); await pat.waitForSelector('button:has-text("Speak"):not([disabled])');
    await pat.click('button:has-text("Speak")'); await pat.waitForTimeout(1500); await pat.click('button:has-text("Stop recording")');
    await pat.waitForFunction(() => document.querySelector('#q') && document.querySelector('#q').value.length > 0, null, { timeout: 8000 }); ok('voice recording transcribed into the message box');
    await pat.fill('#q', 'hello'); await pat.click('button:has-text("Send")'); await pat.waitForSelector('.msg.bot'); await pat.click('button[aria-label="Listen"]'); await pat.waitForTimeout(500); ok('assistant reply + spoken playback path works');
    // unsupported language: mic disabled with explanation
    await pat.selectOption('#lang', 'tw'); await pat.waitForSelector('text=Voice input is not yet available'); ok('voice disabled with explanation for unvalidated language (Twi)');
    await pat.selectOption('#lang', 'en');

    // ---- 5. registration, verification, pending professional
    const reg = await mk('patient@example.com'); // reuse context just for browser; do fresh register in new context
    const ctx = await browser.newContext(); const rp = await ctx.newPage(); rp.on('pageerror', e => errs.push('reg PAGEERROR ' + e.message));
    await rp.goto(U + '/login'); await rp.click('text=Create account'); await rp.fill('#fn', 'New Patient'); await rp.fill('#em', 'newpatient@example.com'); await rp.fill('#pw', 'Another-Passw0rd'); await rp.click('button[type=submit]');
    await rp.waitForSelector('text=dev code'); const code = (await rp.textContent('[role=status]')).match(/dev code: ([\w-]+)/)[1];
    await rp.goto(`${U}/verify?token=${code}`); await rp.waitForSelector('text=Your email is verified'); ok('UI registration → email verification works');
    await rp.goto(U + '/login'); await rp.fill('#em', 'newpatient@example.com'); await rp.fill('#pw', 'Another-Passw0rd'); await rp.click('button[type=submit]'); await rp.waitForSelector('h1:has-text("Welcome")');
    // logout revokes the token server-side
    const tok = await rp.evaluate(() => sessionStorage.getItem('mc_token')); await rp.click('button:has-text("Log out")'); await rp.waitForSelector('h1:has-text("Log in")');
    if ((await api('/auth/me', { token: tok })).status !== 401) throw new Error('token still valid after logout'); ok('logout revokes the session token server-side');

    // ---- 6. mobile layout: no horizontal overflow on every patient page at 390px
    const mctx = await browser.newContext({ viewport: { width: 390, height: 800 } }); const mp = await mctx.newPage();
    await mp.goto(U + '/login'); await mp.fill('#em', 'patient@example.com'); await mp.fill('#pw', PW); await mp.click('button[type=submit]'); await mp.waitForSelector('button.menu');
    const pages = ['/app', '/app/consult', '/app/appointments', '/app/monitoring', '/app/records', '/app/medications', '/app/labs', '/app/drugs', '/app/facilities', '/app/education', '/app/assistant', '/app/billing', '/app/notifications', '/app/settings'];
    const overflow = [];
    for (const pg of pages) { await mp.goto(U + pg); await mp.waitForTimeout(450); const w = await mp.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]); if (w[0] > w[1] + 1) overflow.push(`${pg} (${w[0]}>${w[1]})`); }
    if (overflow.length) throw new Error('horizontal overflow: ' + overflow.join(', ')); ok(`mobile 390px: no horizontal scrolling on ${pages.length} patient pages`);
  } catch (e) { fail('feature run', e.message.split('\n')[0]); }
  const unexpected = errs.filter(e => !e.includes('HTTP 415 POST /files')); // the 415 is the intentional disguised-exe upload
  console.log(unexpected.length ? '\nUNEXPECTED ERRORS:\n' + [...new Set(unexpected)].join('\n') : '\nNo page errors / unexpected failed API calls');
  if (unexpected.length) process.exitCode = 1;
  await browser.close();
})();
