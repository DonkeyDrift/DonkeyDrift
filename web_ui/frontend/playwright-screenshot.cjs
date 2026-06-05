const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  // HashRouter: use #/trainer
  await page.goto('http://localhost:5189/#/trainer', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(8000);

  await page.screenshot({ path: '/tmp/trainer-collapsed.png', fullPage: true });

  // Click Training Log to expand
  const logHeader = page.locator('button').filter({ hasText: /Training Log/i });
  await logHeader.click();
  await page.waitForTimeout(500);

  await page.screenshot({ path: '/tmp/trainer-expanded.png', fullPage: true });

  console.log('Screenshots saved');
  await browser.close();
})();
