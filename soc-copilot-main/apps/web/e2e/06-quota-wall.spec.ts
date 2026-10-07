import { expect, test } from "@playwright/test";

import { loginViaUI, seedUser } from "./_helpers";

/**
 * Quota wall — comportamiento de la UI ante un 429 del backend.
 *
 * El tracker server-side ya está cubierto por tests Python en
 * apps/api/tests/test_byo_llm.py. Aquí solo validamos que cuando
 * /api/explain devuelve 429 con el detail de cuota, el frontend
 * muestra un error reconocible para el analista. Mockeamos el 429
 * con page.route() para no acoplar el e2e al estado del backend.
 */
test("frontend muestra mensaje de error cuando /api/explain devuelve 429 quota", async ({
  page,
  request,
}) => {
  const user = await seedUser(request);
  await loginViaUI(page, user.email, user.password);

  await page.route("**/api/explain", (route) =>
    route.fulfill({
      status: 429,
      contentType: "application/json",
      body: JSON.stringify({
        detail:
          "Daily AI call quota exhausted. Configure your own Gemini key in /settings/llm.",
      }),
    }),
  );

  await page.goto("/alerts");
  await page
    .getByRole("textbox")
    .last()
    .fill("Failed password for root from 1.2.3.4 port 5555 ssh2");
  await page.getByRole("button", { name: "Analizar" }).click();

  // The page renders an error banner with the API detail message.
  await expect(page.getByText(/quota/i)).toBeVisible();
});
