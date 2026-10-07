import { expect, test } from "@playwright/test";

import { loginViaUI, seedUser } from "./_helpers";

// Nota: NO probamos el flujo de API key porque no podemos validar contra
// Gemini en CI sin una clave real. El backend valida la key antes de
// guardarla y rechaza claves inválidas. Sólo cubrimos la persistencia del
// modelo predeterminado.
test("analyst cambia el modelo predeterminado y persiste tras recargar", async ({ page, request }) => {
  const user = await seedUser(request);
  await loginViaUI(page, user.email, user.password);

  await page.goto("/settings/llm");
  await expect(page.getByRole("heading", { name: "Modelo predeterminado" })).toBeVisible();

  const select = page.locator("select").first();
  const options = await select.locator("option").allTextContents();
  // Pick a different option than the current selection.
  const current = await select.inputValue();
  const otherOptionText = options.find((t) => !t.includes("(servidor)"));
  if (!otherOptionText || options.length < 2) {
    test.skip(true, "Sólo hay un modelo disponible — no se puede probar el cambio");
    return;
  }

  // Match the option *value*, which equals the model id without the suffix.
  const otherValue = otherOptionText.trim().split(" ")[0];
  if (otherValue === current) {
    test.skip(true, "Modelo no-default coincide con el actual — sin cambio que verificar");
    return;
  }

  await select.selectOption(otherValue);
  await page.getByRole("button", { name: "Guardar modelo" }).click();
  await expect(page.getByText("Modelo predeterminado actualizado.")).toBeVisible();

  await page.reload();
  await expect(page.locator("select").first()).toHaveValue(otherValue);
});
