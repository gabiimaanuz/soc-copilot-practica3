import { expect, test } from "@playwright/test";

import { apiUrl, loginViaUI, seedUser } from "./_helpers";

test("login → header con email + rol, logout limpia sesión, password mal muestra error", async ({
  page,
  request,
}) => {
  const user = await seedUser(request);

  await loginViaUI(page, user.email, user.password);
  await expect(page.getByText(user.email)).toBeVisible();
  await expect(page.getByText("analyst", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Salir" }).click();
  await expect(page).toHaveURL(/\/login/);

  // /api/auth/me must return 401 once cookies are cleared.
  const me = await page.request.get(`${apiUrl()}/api/auth/me`);
  expect(me.status()).toBe(401);

  // Wrong password → inline error.
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Contraseña").fill("wrong-password-x");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByText("Credenciales inválidas.")).toBeVisible();
});
