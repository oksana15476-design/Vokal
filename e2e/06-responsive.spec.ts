import { expect, test } from "@playwright/test";
import { clearStorage, openDemo, openTab } from "./helpers";

test.describe("Раскладка и доступность", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  test("страница не разъезжается ни на одной ширине", async ({ page }) => {
    await openDemo(page);

    for (const width of [360, 390, 480, 640, 768, 900, 1024, 1180, 1280, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(120);
      const overflow = await page.evaluate(() => ({
        scrollW: document.documentElement.scrollWidth,
        clientW: document.documentElement.clientWidth,
      }));
      expect(overflow.scrollW, `ширина ${width}px: страница шире экрана`).toBeLessThanOrEqual(overflow.clientW + 1);
    }
  });

  test("контраст текста не ниже нормы на всех вкладках", async ({ page }) => {
    await openDemo(page);

    const measure = () =>
      page.evaluate(() => {
        const lum = (c: number[]) => {
          const [r, g, b] = c.map((v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
          });
          return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        };
        const parse = (s: string) => (s.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
        const bgOf = (el: Element) => {
          let node: Element | null = el;
          while (node && node !== document.documentElement) {
            const bg = getComputedStyle(node).backgroundColor;
            const alpha = (bg.match(/[\d.]+/g) || [])[3];
            if (bg !== "rgba(0, 0, 0, 0)" && alpha !== "0") return parse(bg);
            node = node.parentElement;
          }
          return [255, 255, 255];
        };
        const ratio = (a: number[], b: number[]) => {
          const l1 = lum(a);
          const l2 = lum(b);
          return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        };

        const bad: string[] = [];
        for (const el of document.querySelectorAll("p,span,strong,small,li,label,h1,h2,h3,button,em,i,b")) {
          const text = (el.textContent || "").trim();
          if (!text || el.children.length > 0) continue;
          const cs = getComputedStyle(el);
          if (cs.visibility === "hidden" || cs.display === "none" || el.getBoundingClientRect().width === 0) continue;
          const size = parseFloat(cs.fontSize);
          const need = size >= 24 || (size >= 18.66 && parseInt(cs.fontWeight, 10) >= 700) ? 3 : 4.5;
          const value = ratio(parse(cs.color), bgOf(el));
          if (value < need - 0.05) bad.push(`${value.toFixed(2)} < ${need}: ${text.slice(0, 40)}`);
        }
        return bad;
      });

    for (const tab of [/Обзор/, /Материалы/, /Состав/, /Проверка/, /AI-директор/, /Выдача/]) {
      await openTab(page, tab);
      expect(await measure(), `вкладка ${tab}`).toEqual([]);
    }
  });

  test("каждый контрол подсвечивается при навигации клавишей", async ({ page }) => {
    await openDemo(page);

    const invisible: string[] = [];
    for (let i = 0; i < 30; i += 1) {
      await page.keyboard.press("Tab");
      const result = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const cs = getComputedStyle(el);
        const hasOutline = cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0;
        const hasShadow = cs.boxShadow !== "none";
        return hasOutline || hasShadow
          ? null
          : (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40);
      });
      if (result) invisible.push(result);
    }
    expect(invisible).toEqual([]);
  });
});
