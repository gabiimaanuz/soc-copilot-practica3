import { expect, type APIRequestContext, type Page, type Route } from "@playwright/test";

/** Where the FastAPI service is reachable from the host running Playwright. */
export function apiUrl(): string {
  return process.env.E2E_API_URL ?? "http://localhost:8080";
}

export type Role = "analyst" | "admin";

export interface SeededUser {
  email: string;
  password: string;
  name: string;
}

function uniqEmail(prefix = "e2e"): string {
  // crypto.randomUUID is available in Node 18+ and CI runners.
  return `${prefix}-${crypto.randomUUID().slice(0, 8)}@e2e.local`;
}

/**
 * Create a user via the public registration endpoint. The first user the
 * backend ever sees is auto-promoted to admin; subsequent ones are analysts
 * unless an admin creates them explicitly. For analyst users this is fine
 * regardless of whether an admin already exists.
 */
export async function seedUser(
  request: APIRequestContext,
  opts: { role?: Role; admin?: SeededUser } = {},
): Promise<SeededUser> {
  const email = uniqEmail(opts.role ?? "analyst");
  const password = "Test123456!";
  const name = "E2E";

  // For admin role, if there is already an admin in the DB the registration
  // endpoint will give us an analyst — promote via /api/admin/users instead.
  if (opts.role === "admin" && opts.admin) {
    const login = await request.post(`${apiUrl()}/api/auth/login`, {
      data: { email: opts.admin.email, password: opts.admin.password },
    });
    expect(login.ok(), `admin login failed: ${login.status()}`).toBeTruthy();
    const created = await request.post(`${apiUrl()}/api/admin/users`, {
      data: { name, email, password, role: "admin" },
    });
    expect(created.ok(), `admin create failed: ${await created.text()}`).toBeTruthy();
    return { email, password, name };
  }

  const res = await request.post(`${apiUrl()}/api/auth/register`, {
    data: { email, password, name },
  });
  expect(res.ok(), `register failed: ${res.status()} ${await res.text()}`).toBeTruthy();
  return { email, password, name };
}

/** Fill the /login form and wait for redirection to the home page. */
export async function loginViaUI(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Contraseña").fill(password);
  const meRequest = page.waitForResponse(
    (r) => r.url().endsWith("/api/auth/login") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await meRequest;
  // The shell topbar only renders once auth refreshes — wait for the logout button.
  await expect(page.getByRole("button", { name: "Salir" })).toBeVisible();
}

/** Build a fake ExplainResponse — matches apps/web/src/lib/api.ts shape. */
export function fakeExplainBody() {
  return {
    id: 1,
    summary: "Intento de fuerza bruta SSH detectado en el servidor.",
    risk_level: "high" as const,
    mitre_techniques: ["T1110"],
    reasoning:
      "Múltiples fallos de autenticación en una ventana corta sugieren brute-force.",
  };
}

export function fakeChatBody() {
  return {
    reply: "Respuesta del mentor SOC para el test E2E.",
    sources: ["mitre:T1110"],
  };
}

export function fakeKbStatusBody() {
  return { total: 700, mitre: 600, owasp: 100, unknown: 0 };
}

/**
 * Intercept LLM-bound endpoints with synthetic responses so tests stay
 * independent of Gemini availability and the per-user quota.
 *
 * Use selectively per spec: pass the keys of the endpoints you actually
 * exercise.
 */
export async function mockLLM(
  page: Page,
  which: { explain?: boolean; recommend?: boolean; chat?: boolean; kb?: boolean } = {
    explain: true,
    recommend: true,
    chat: true,
    kb: true,
  },
): Promise<void> {
  const json = (route: Route, body: unknown) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });

  if (which.explain)
    await page.route("**/api/explain", (route) => json(route, fakeExplainBody()));
  if (which.recommend)
    await page.route("**/api/recommend", (route) =>
      json(route, {
        id: 1,
        alert_id: 1,
        actions: [
          { title: "Bloquear IP origen", detail: "Aplicar regla en firewall.", rationale: "Detener el ataque." },
        ],
        priority: "high",
        learning_notes: "Notas para el analista junior.",
      }),
    );
  if (which.chat)
    await page.route("**/api/chat", (route) => json(route, fakeChatBody()));
  if (which.kb)
    await page.route("**/api/kb/status", (route) => json(route, fakeKbStatusBody()));
}
