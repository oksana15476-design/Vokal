import { expect, test } from "@playwright/test";
import { clearStorage, openDemo, openDemoByTitle } from "./helpers";

test.describe("Список песен и сохранение", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  test("пустой список объясняет пустоту и дает выход", async ({ page }) => {
    await page.getByRole("button", { name: /^Песни$/ }).click();
    await expect(page.getByText(/Пока ни одной песни/)).toBeVisible();
    await page.getByRole("button", { name: /Загрузить песню/ }).click();
    await expect(page.getByRole("heading", { name: /От выбора песни/ })).toBeVisible();
  });

  test("открытые песни собираются в список, недавняя первой", async ({ page }) => {
    await openDemo(page);
    await page.getByRole("button", { name: /На главный экран/ }).click();
    await openDemoByTitle(page, /School Hall: ансамбль учеников/);

    await page.getByRole("button", { name: /^Песни$/ }).click();
    const rows = page.locator(".song-row");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("School Hall");
  });

  test("песня переживает перезагрузку вместе с историей версий", async ({ page }) => {
    await openDemo(page);
    await page.getByRole("tab", { name: /AI-директор/ }).click();
    await page.locator(".suggestions-grid button").first().click();
    const versions = await page.locator(".version-row").count();

    await page.reload();
    await page.getByRole("button", { name: /Вернуться к песне/ }).click();
    await page.getByRole("tab", { name: /AI-директор/ }).click();
    await expect(page.locator(".version-row")).toHaveCount(versions);
  });

  test("говорит, где лежит сохраненная песня", async ({ page }) => {
    await openDemo(page);
    await page.getByRole("button", { name: /На главный экран/ }).click();
    await expect(page.locator(".resume-row")).toContainText(/Сохранена в этом браузере/);
  });

  test("удаление песни требует подтверждения", async ({ page }) => {
    await openDemo(page);
    await page.getByRole("button", { name: /^Песни$/ }).click();

    await page.locator(".song-row").first().getByRole("button", { name: /Удалить/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(page.locator(".song-row")).toHaveCount(1);

    await dialog.getByRole("checkbox").check();
    await dialog.getByRole("button", { name: /Удалить навсегда/ }).click();
    await expect(page.locator(".song-row")).toHaveCount(0);
  });

  test("песня из списка открывается в рабочую область", async ({ page }) => {
    await openDemo(page);
    await page.getByRole("button", { name: /^Песни$/ }).click();
    await page.locator(".song-row").first().getByRole("button", { name: /Открыть/ }).click();
    await expect(page.getByRole("tab", { name: /Материалы/ })).toBeVisible();
  });

  test("демо не перетирает выбранное пользователем задание", async ({ page }) => {
    await page.getByRole("radio", { name: /Школьный ансамбль/ }).click();
    await expect(page.getByRole("radio", { name: /Школьный ансамбль/ })).toHaveAttribute("aria-checked", "true");

    await openDemo(page);
    await page.getByRole("button", { name: /На главный экран/ }).click();
    await expect(page.getByRole("radio", { name: /Школьный ансамбль/ })).toHaveAttribute("aria-checked", "true");
  });
});
