// Captura screenshots del manual de usuario.
// Uso: npx playwright install chromium && node scripts/capture_docs_screenshots.mjs
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const BASE = process.env.SOC_BASE ?? "http://localhost:13500";
const API = process.env.SOC_API ?? "http://localhost:8080";
const EMAIL = process.env.SOC_EMAIL ?? "admin@prueba.com";
const PASSWORD = process.env.SOC_PASSWORD ?? "Capturas2026!ok";
const ALERT_ID = process.env.SOC_ALERT_ID ?? "21";
const OUT = path.resolve(process.cwd(), "docs/assets");

const TARGETS = [
  { name: "dashboard_mockup.png", url: `${BASE}/dashboard` },
  { name: "alert_explainer_mockup.png", url: `${BASE}/alerts` },
  { name: "next_step_recommender_mockup.png", url: `${BASE}/respond?alert_id=${ALERT_ID}` },
  { name: "chat_ia_mockup.png", url: `${BASE}/chat` },
];

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // Login via API to capture the httpOnly session cookie.
  const loginResp = await ctx.request.post(`${API}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
    headers: { "Content-Type": "application/json" },
  });
  if (!loginResp.ok()) {
    throw new Error(`Login failed: ${loginResp.status()} ${await loginResp.text()}`);
  }
  console.log("Login OK as", EMAIL);

  for (const t of TARGETS) {
    console.log("→", t.url);
    await page.goto(t.url, { waitUntil: "networkidle", timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const file = path.join(OUT, t.name);
    await page.screenshot({ path: file, fullPage: true });
    console.log("   saved", file);
  }

  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
