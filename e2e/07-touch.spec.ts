import { expect, test } from "@playwright/test";
import { clearStorage, openDemo } from "./helpers";

/** Мобильные требования проверяем только в мобильном проекте. */
test.describe("Мобильная раскладка", () => {
  test.skip(({ isMobile }) => !isMobile, "только для мобильного проекта");

  test.beforeEach(async ({ page }) => clearStorage(page));

  test("тач-цели не меньше 44 px", async ({ page }) => {
    await openDemo(page);

    const small = await page.evaluate(() => {
      const bad: string[] = [];
      for (const el of document.querySelectorAll("button:not([disabled]),a[href],input[type=checkbox],input[type=radio]")) {
        const rect = el.getBoundingClientRect();
        if (rect.width === 0) continue;
        if (rect.height < 44) {
          bad.push(`${Math.round(rect.height)}px: ${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)}`);
        }
      }
      return bad;
    });
    expect(small).toEqual([]);
  });

  test("вкладки и форма песни листаются, а не обрезаются", async ({ page }) => {
    await openDemo(page);

    for (const selector of [".workspace-tabs", ".console-sections"]) {
      const scrollable = await page.locator(selector).evaluate((el) => ({
        scrollW: el.scrollWidth,
        clientW: el.clientWidth,
        overflowX: getComputedStyle(el).overflowX,
      }));
      if (scrollable.scrollW > scrollable.clientW) {
        expect(scrollable.overflowX, `${selector} обрезан без прокрутки`).toMatch(/auto|scroll/);
      }
    }
  });

  test("дорожка пульта читается: полоса и процент на месте", async ({ page }) => {
    await openDemo(page);
    const row = page.locator(".console-track-row").first();
    await expect(row.locator(".track-confidence")).toBeVisible();
    await expect(row.locator(".track-percent")).toHaveText(/^\d+%$/);
  });
});
