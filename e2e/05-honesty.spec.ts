import { expect, test } from "@playwright/test";
import { clearStorage, openDemo, openTab, uploadPath } from "./helpers";

/**
 * Продукт не обещает того, чего не делает. Органы управления, за которыми
 * ничего нет, выключены и говорят почему.
 */
test.describe("Честность интерфейса", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  const forbidden = [
    /бесплатн/i,
    /подписк/i,
    /\bPro\b/,
    /\bFree\b/,
    /\d+\s*[-–—]?\s*\d*\s*(секунд|минут|час)/i,
    /₽|(?<!\p{L})руб|(?<!\p{L})цен[аыуе]|стоимост|тариф|кредит/iu,
    /(?<!\p{L})мок/iu,
    /ё/,
  ];

  const assertClean = async (page: import("@playwright/test").Page, where: string) => {
    const text = await page.locator("body").innerText();
    for (const pattern of forbidden) {
      expect(text, `${where}: ${pattern}`).not.toMatch(pattern);
    }
  };

  test("не обещает цен и сроков ни на одном экране", async ({ page }) => {
    await assertClean(page, "первый экран");
    await page.getByRole("button", { name: /^Песни$/ }).click();
    await assertClean(page, "песни");

    await page.getByRole("button", { name: /Загрузить песню/ }).click();
    await openDemo(page);
    for (const tab of [/Обзор/, /Материалы/, /Состав/, /Проверка/, /AI-директор/, /Выдача/]) {
      await openTab(page, tab);
      await assertClean(page, `вкладка ${tab}`);
    }
  });

  test("воспроизведение выключено и говорит почему", async ({ page }) => {
    await openDemo(page);
    const play = page.locator(".console-play");
    await expect(play).toBeDisabled();
    await expect(play).toHaveAttribute("aria-label", /звука/i);
    await expect(page.locator(".console-modes .mono-chip")).toHaveCount(1);
  });

  test("Solo и Mute выключены", async ({ page }) => {
    await openDemo(page);
    const controls = page.locator(".track-controls button").filter({ hasText: /^[MS]$/ });
    const count = await controls.count();
    expect(count).toBeGreaterThan(0);
    for (let i = 0; i < count; i += 1) {
      await expect(controls.nth(i)).toBeDisabled();
    }
  });

  test("скачивание ZIP выключено и говорит почему", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Материалы/);
    const zip = page.getByRole("button", { name: /Скачать ZIP/ });
    await expect(zip).toBeDisabled();
    await expect(zip).toHaveAttribute("title", /файл/i);
  });

  test("раскрытия на первом экране на месте", async ({ page }) => {
    const text = await page.locator("body").innerText();
    expect(text).toMatch(/[Зз]вук не обрабатывается/);
    expect(text).toMatch(/[Фф]айл останется на устройстве/);
    expect(text).toMatch(/вправе обработать этот материал/);
  });

  test("на своем файле говорит, что разбор не создается", async ({ page }) => {
    await uploadPath(page);
    await expect(page.getByLabel("Состояние песни")).toContainText(/разбора песни нет/);
  });

  test("на экране не больше одной графитовой кнопки", async ({ page }) => {
    await expect(page.locator("button.btn-primary")).toHaveCount(1);
    await openDemo(page);
    expect(await page.locator("button.btn-primary").count()).toBeLessThanOrEqual(1);
    await openTab(page, /AI-директор/);
    expect(await page.locator("button.btn-primary").count()).toBeLessThanOrEqual(1);
  });
});
