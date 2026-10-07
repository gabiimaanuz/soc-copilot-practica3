import { defineConfig, devices } from "@playwright/test";

// We deliberately do NOT spawn `next dev` from Playwright: the full stack
// (Postgres + Chroma + API + Next) is brought up by docker compose from the
// repo root before the tests run. Locally:
//   docker compose -f infra/docker-compose.yml up -d
// Then: cd apps/web && npm run e2e
//
// Both URLs below are the loopback ports exposed by infra/docker-compose.yml.
const isCI = !!process.env.CI;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: isCI,
  retries: isCI ? 1 : 0,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  reporter: isCI ? [["list"]] : [["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_WEB_URL ?? "http://localhost:13500",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
