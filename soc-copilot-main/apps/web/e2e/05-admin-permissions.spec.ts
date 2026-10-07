import { expect, test } from "@playwright/test";

import { apiUrl, loginViaUI, seedUser } from "./_helpers";

/**
 * Admin login + acceso al panel de administración.
 *
 * Asume que el primer usuario creado por el workflow CI (env
 * E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD) ya es admin, porque el backend
 * promueve automáticamente al primer registro. Si las variables no están
 * presentes, sembramos un admin nuevo asumiendo que esta DB está vacía
 * (caso de ejecución local con `docker compose down -v`).
 *
 * El test no flipea permisos (la matriz mezcla cells locked y un guardado
 * masivo es delicado de validar end-to-end). Se queda en "puede entrar al
 * panel y ver la matriz", que cubre la ruta y los gates de auth/role.
 */
test("admin entra al panel y ve la matriz de permisos", async ({ page, request }) => {
  let adminEmail = process.env.E2E_ADMIN_EMAIL;
  let adminPassword = process.env.E2E_ADMIN_PASSWORD;

  if (!adminEmail || !adminPassword) {
    // Local fallback: register the very first user, which the backend
    // auto-promotes to admin. Only safe on a fresh DB.
    const probe = await request.post(`${apiUrl()}/api/auth/register`, {
      data: {
        name: "AutoAdmin",
        email: `admin-${Date.now()}@e2e.local`,
        password: "Test123456!",
      },
      failOnStatusCode: false,
    });
    if (!probe.ok()) {
      test.skip(true, "No hay admin sembrado y /register no está disponible");
      return;
    }
    const body = await probe.json();
    adminEmail = body.email;
    adminPassword = "Test123456!";
    if (body.role !== "admin") {
      test.skip(true, "El usuario sembrado no quedó como admin (DB no vacía)");
      return;
    }
  }

  await loginViaUI(page, adminEmail!, adminPassword!);
  await page.goto("/admin");

  await expect(page.getByRole("heading", { name: "Administración" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Usuarios Registrados" })).toBeVisible();

  // Ensure the admin can see at least their own row.
  await expect(page.getByText(adminEmail!)).toBeVisible();

  // Switch to the permisos tab and confirm the matrix renders.
  await page.getByRole("button", { name: "permisos" }).click();
  await expect(page.getByRole("heading", { name: "Matriz de Permisos" })).toBeVisible();

  // Analyst seeded after admin should not be allowed into /admin.
  const analyst = await seedUser(request);
  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page).toHaveURL(/\/login/);
  await loginViaUI(page, analyst.email, analyst.password);
  const adminUsers = await page.request.get(`${apiUrl()}/api/admin/users`);
  expect([401, 403]).toContain(adminUsers.status());
});
