import { expect, test } from "@playwright/test";
import { clearStorage, openDemoByTitle, openTab } from "./helpers";

test.describe("Сценарий «Для обучения»", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  test("демо урока доходит до Stage Pack", async ({ page }) => {
    await openDemoByTitle(page, /Warm Lights: урок гитары/);
    await expect(page.getByLabel("Состояние песни")).toBeVisible();
  });

  test("каждая партия урока получает свою команду", async ({ page }) => {
    await openDemoByTitle(page, /Warm Lights: урок гитары/);

    const commands = await page.locator(".console-track-row .track-command").allInnerTexts();
    expect(commands.length).toBeGreaterThan(2);
    // Раньше все партии получали «усложнить», включая «Аккорды».
    expect(new Set(commands.map((c) => c.trim())).size).toBeGreaterThan(1);
    expect(commands.map((c) => c.trim())).toContain("разбор к уроку");

    for (const command of commands) {
      expect(command.trim().length, `ярлык «${command}» длиннее 14 знаков`).toBeLessThanOrEqual(14);
    }
  });

  test("школьный ансамбль показывает три уровня сложности", async ({ page }) => {
    await openDemoByTitle(page, /School Hall: ансамбль учеников/);
    await openTab(page, /Состав/);

    const levels = page.getByRole("radiogroup", { name: /Уровень сложности/ });
    await expect(levels.getByRole("radio")).toHaveCount(3);

    // Отрицательное сравнение не работало: innerText и textContent склеивают
    // блоки по-разному, «не равно» было истинно всегда. Собираем заголовок
    // на каждом уровне и требуем, чтобы все три различались.
    const title = page.locator(".level-detail strong");
    const seen: string[] = [];
    for (const level of [/Начинающий/, /Средний/, /Продвинутый/]) {
      await levels.getByRole("radio", { name: level }).click();
      await expect(levels.getByRole("radio", { name: level })).toHaveAttribute("aria-checked", "true");
      seen.push((await title.innerText()).trim());
    }
    expect(new Set(seen).size, `уровни показывают одно и то же: ${seen.join(" | ")}`).toBe(3);
  });

  test("уровни не показываются там, где учеников нет", async ({ page }) => {
    await openDemoByTitle(page, /Late Train Home/);
    await openTab(page, /Состав/);
    await expect(page.getByRole("radiogroup", { name: /Уровень сложности/ })).toHaveCount(0);
  });

  test("цикл после урока создает следующую версию", async ({ page }) => {
    await openDemoByTitle(page, /Warm Lights: урок гитары/);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    await page.locator(".session-note").fill("Ученик уверенно сыграл припев");
    await page.getByRole("button", { name: /Создать следующую версию/ }).click();
    await expect(versions).toHaveCount(before + 1);
  });
});
