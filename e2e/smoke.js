const { chromium } = require('playwright');
const PW = 'Demo-Passw0rd!';
const roles = [['patient@example.com'], ['doctor@example.com'], ['pharmacist@example.com'], ['lab@example.com'], ['facility@example.com'], ['pending.doctor@example.com'], ['admin@example.com']];
(async () => {
  const browser = await chromium.launch();
  let problems = 0;
  for (const [email] of roles) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    const issues = [];
    page.on('pageerror', e => issues.push('PAGEERROR ' + e.message));
    page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) issues.push('CONSOLE ' + m.text().slice(0, 160)); });
    page.on('response', r => { if (r.url().includes('/api/v1') && r.status() >= 400) issues.push(`HTTP ${r.status()} ${r.request().method()} ${r.url().replace(/.*\/api\/v1/, '')}`); });
    await page.goto('http://localhost:5173/login');
    await page.fill('#em', email); await page.fill('#pw', PW); await page.click('button[type=submit]');
    await page.waitForSelector('nav a', { timeout: 8000 }).catch(() => issues.push('NO NAV after login'));
    const links = await page.$$eval('nav a', as => as.map(a => a.getAttribute('href')));
    for (const href of links) {
      await page.goto('http://localhost:5173' + href); await page.waitForTimeout(500);
      const h1 = await page.$eval('h1', e => e.textContent).catch(() => null);
      if (!h1) issues.push('NO H1 on ' + href);
      const body = await page.evaluate(() => document.body.innerText);
      if (/Something went wrong|undefined|\[object Object\]|NaN/.test(body)) issues.push('BAD TEXT on ' + href + ': ' + (body.match(/.{20}(undefined|\[object Object\]|NaN).{10}/) || [''])[0]);
    }
    const uniq = [...new Set(issues)];
    console.log(`${email.padEnd(30)} pages=${links.length} issues=${uniq.length}`); uniq.forEach(i => console.log('   - ' + i)); problems += uniq.length;
    if (email.startsWith('patient')) { await page.goto('http://localhost:5173/app'); await page.screenshot({ path: 'patient-home.png' }); await page.setViewportSize({ width: 390, height: 800 }); await page.screenshot({ path: 'patient-mobile.png' }); }
    if (email.startsWith('admin')) { await page.goto('http://localhost:5173/admin/verification'); await page.waitForTimeout(500); await page.screenshot({ path: 'admin-verif.png' }); }
    await ctx.close();
  }
  await browser.close();
  console.log('TOTAL ISSUES', problems);
})();
