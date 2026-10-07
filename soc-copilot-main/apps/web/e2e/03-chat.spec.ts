import { expect, test } from "@playwright/test";

import { loginViaUI, mockLLM, seedUser } from "./_helpers";

test("analyst envía mensaje al chat y ve respuesta + source pill", async ({ page, request }) => {
  const user = await seedUser(request);
  await loginViaUI(page, user.email, user.password);

  await mockLLM(page, { chat: true, kb: true });

  await page.goto("/chat");
  await page.getByPlaceholder("Escribe tu pregunta…").fill("¿Qué es T1110?");
  await page.getByRole("button", { name: "Enviar" }).click();

  await expect(page.getByText("¿Qué es T1110?")).toBeVisible();
  await expect(page.getByText("Respuesta del mentor SOC para el test E2E.")).toBeVisible();
  // Source pill renders the technique ref ("T1110") with a link.
  await expect(page.getByRole("link", { name: /T1110/ })).toBeVisible();
});
