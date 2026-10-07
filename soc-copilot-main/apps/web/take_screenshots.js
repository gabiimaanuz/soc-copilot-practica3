const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 }
  });
  const page = await context.newPage();

  console.log("Navigating to login...");
  await page.goto('http://localhost:13500/login');
  
  // Wait for login form
  await page.fill('input[type="email"]', 'admin@prueba.com');
  await page.fill('input[type="password"]', '123456789');
  await page.click('button[type="submit"]');

  console.log("Waiting for dashboard to load...");
  // Wait until we are on dashboard or network is idle
  await page.waitForURL('**/dashboard', { timeout: 10000 }).catch(() => {});
  await page.waitForTimeout(3000); // give it time to render charts

  // Take dashboard screenshot
  console.log("Screenshotting dashboard...");
  const destDir = path.resolve('../../docs/assets');
  await page.screenshot({ path: path.join(destDir, 'dashboard_mockup.png'), fullPage: false });

  // Alerts Explainer
  console.log("Navigating to alerts...");
  await page.evaluate(() => {
    sessionStorage.setItem('soc_copilot_imported_logs', 'Mar 15 14:32:10 srv-web-01 sshd[12345]: Failed password for invalid user admin from 192.168.1.100 port 54321 ssh2');
  });
  await page.goto('http://localhost:13500/alerts?import=true');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(destDir, 'alert_explainer_mockup.png'), fullPage: false });

  // Chat IA
  console.log("Navigating to chat...");
  await page.goto('http://localhost:13500/chat');
  await page.waitForTimeout(2000);
  // Optional: type something into the chat to show interaction
  try {
    await page.fill('textarea', '¿Qué es T1059.001?');
    await page.click('button[type="submit"]');
    await page.waitForTimeout(3000);
  } catch(e) {}
  await page.screenshot({ path: path.join(destDir, 'chat_ia_mockup.png'), fullPage: false });

  // Next Step Recommender
  console.log("Navigating to respond...");
  await page.goto('http://localhost:13500/respond');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(destDir, 'next_step_recommender_mockup.png'), fullPage: false });

  await browser.close();
  console.log("Done!");
})();
