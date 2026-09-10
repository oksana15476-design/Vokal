import { expect, test } from "@playwright/test";
import { PROCESSING_MS, clearStorage, openDemo, openTab } from "./helpers";

test.describe("Сценарий «Для группы»: от демо-разбора до выдачи", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  test("демо-разбор доходит до Stage Pack и показывает полосу метрик", async ({ page }) => {
    await openDemo(page);

    const strip = page.getByLabel("Состояние песни");
    await expect(strip).toBeVisible();
    await expect(strip.locator(".metric-card")).toHaveCount(4);
    await expect(strip).toContainText("BPM");
    await expect(strip).toContainText("материалов готово");
  });

  test("пультовая панель собирает весь звук на одной поверхности", async ({ page }) => {
    await openDemo(page);
    const console_ = page.locator(".console-panel");
    await expect(console_).toBeVisible();

    for (const part of [".console-transport", ".console-wave", ".console-sections", ".console-tracks", ".console-chords"]) {
      await expect(console_.locator(part), `нет ${part} внутри пульта`).toBeVisible();
    }
  });

  test("точность разбора подписана процентом, а не только цветом", async ({ page }) => {
    await openDemo(page);
    const rows = page.locator(".console-track-row");
    const count = await rows.count();
    expect(count).toBeGreaterThan(2);

    for (let i = 0; i < count; i += 1) {
      await expect(rows.nth(i).locator(".track-confidence b")).toBeVisible();
      await expect(rows.nth(i).locator(".track-percent")).toHaveText(/^\d+%$/);
    }
  });

  test("аккорд под вопросом отличается знаком и рамкой", async ({ page }) => {
    await openDemo(page);
    const uncertain = page.locator(".console-chords .chord-chip.uncertain");
    await expect(uncertain.first()).toBeVisible();
    await expect(uncertain.first()).toContainText("?");
  });

  test("форма песни переключается по секциям", async ({ page }) => {
    await openDemo(page);
    const sections = page.locator(".console-section");
    await expect(sections.first()).toHaveClass(/active/);
    await sections.nth(2).click();
    await expect(sections.nth(2)).toHaveClass(/active/);
    await expect(sections.first()).not.toHaveClass(/active/);
  });

  test("состав показывает людей и их ограничения", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Состав/);

    const rows = page.locator(".musician-row");
    expect(await rows.count()).toBeGreaterThan(2);
    await expect(rows.first().locator(".musician-name")).not.toBeEmpty();
    await expect(rows.first().locator(".musician-constraint")).not.toBeEmpty();
    await expect(page.locator(".lineup-list")).toContainText("A2-G4");
  });

  test("материалы листаются страницами и фильтруются по формату", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Материалы/);

    const rows = page.locator(".artifact-row");
    const onFirstPage = await rows.count();
    expect(onFirstPage).toBeGreaterThan(0);
    await expect(page.locator(".pane-footer")).toContainText(`Показаны ${onFirstPage} из`);

    await page.getByRole("button", { name: "Следующая страница" }).click();
    expect(await rows.count()).toBeGreaterThan(0);

    await page.getByRole("button", { name: /Только PDF/ }).click();
    const filtered = await rows.count();
    expect(filtered).toBeGreaterThan(0);
    for (let i = 0; i < filtered; i += 1) {
      await expect(rows.nth(i).locator(".artifact-format")).toHaveText("PDF");
    }
  });

  test("превью материала меняется при выборе другого", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Материалы/);

    const pane = page.locator(".material-preview-pane");
    const first = await pane.innerText();
    await page.locator(".artifact-row").nth(2).click();
    await expect(pane).not.toHaveText(first);
  });

  test("проверка: пять статусов и свой комментарий", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Проверка/);

    const item = page.locator(".review-item").first();
    await expect(item.getByRole("button", { name: "сомнительно" })).toBeVisible();

    await item.getByRole("button", { name: "проверено" }).click();
    await expect(item).toContainText("проверено");
    await item.getByRole("button", { name: "нужно проверить" }).click();
    await expect(item).toContainText("нужно проверить");

    await item.getByLabel("Комментарий к месту").fill("Гитарист играет иначе, оставили");
    await item.getByRole("button", { name: /Записать/ }).click();
    await expect(item).toContainText("Гитарист играет иначе, оставили");
  });

  test("действие директора создает версию и предлагает отменить", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    await page.locator(".suggestions-grid button").first().click();
    await expect(versions).toHaveCount(before + 1);

    const toast = page.getByRole("status").first();
    await expect(toast).toBeVisible();
    await toast.getByRole("button", { name: /Отменить/ }).click();
    // Отмена возвращает предыдущую версию, историю не удаляет.
    await expect(versions).toHaveCount(before + 1);
  });

  test("несколько предложений собираются в одну версию", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    const boxes = page.locator(".suggestion-card input[type=checkbox]");
    await boxes.nth(0).check();
    await boxes.nth(1).check();

    await page.getByRole("button", { name: /Собрать версию из 2/ }).click();
    await expect(versions).toHaveCount(before + 1);
  });

  test("непонятая команда не выполняется как чужая", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    await page.getByLabel("Команда AI-директору").fill("сделай красиво и по-своему");
    await page.getByRole("button", { name: /Применить в демо/ }).click();

    const thread = page.getByLabel("Разговор с AI-директором");
    await expect(thread).toContainText("сделай красиво и по-своему");
    await expect(thread).toContainText("Не разобрал команду");
    await expect(versions).toHaveCount(before);
  });

  test("распознанная команда выполняется и попадает в переписку", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    await page.getByLabel("Команда AI-директору").fill("транспонируй ниже");
    await page.getByRole("button", { name: /Применить в демо/ }).click();

    await expect(versions).toHaveCount(before + 1);
    await expect(page.getByLabel("Разговор с AI-директором")).toContainText("транспонируй ниже");
  });

  test("откат возвращает материалы на любую глубину", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    // Первая строка списка — самая ранняя версия. Активной в демо стоит не
    // она: проверка сравнивала с изначально активной и падала законно.
    const firstLabel = await versions.first().locator("span").first().innerText();

    const before = await versions.count();
    await page.locator(".suggestions-grid button").first().click();
    await expect(versions).toHaveCount(before + 1);
    await page.locator(".suggestions-grid button").first().click();
    await expect(versions).toHaveCount(before + 2);

    // Возврат к самой ранней версии, а не на шаг назад.
    await versions.first().click();
    await expect(page.locator(".version-row.active span").first()).toHaveText(firstLabel);
    // История вперед остается на месте: откат не удаляет версии.
    await expect(versions).toHaveCount(before + 2);
  });

  test("выдача: получатели, ссылки и приватность", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Выдача/);

    await expect(page.getByText(/Формат: DEMO/)).toBeVisible();
    await expect(page.getByText(/Исходник: сохранен/)).toBeVisible();
    await expect(page.getByText(/Результаты: сохранены/)).toBeVisible();
  });

  test("удаление результатов требует подтверждения и доходит до состояния", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /Выдача/);

    await page.getByRole("button", { name: /Удалить результаты/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();

    const confirm = dialog.getByRole("button", { name: /Удалить навсегда/ });
    await expect(confirm).toBeDisabled();
    await dialog.getByRole("checkbox").check();
    await expect(confirm).toBeEnabled();

    await dialog.getByRole("button", { name: /Оставить/ }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByText(/Результаты: сохранены/)).toBeVisible();

    await page.getByRole("button", { name: /Удалить результаты/ }).click();
    await page.getByRole("dialog").getByRole("checkbox").check();
    await page.getByRole("dialog").getByRole("button", { name: /Удалить навсегда/ }).click();
    await expect(page.getByText(/Результаты: удалены/)).toBeVisible();
  });

  test("цикл после репетиции создает следующую версию", async ({ page }) => {
    await openDemo(page);
    await openTab(page, /AI-директор/);

    const versions = page.locator(".version-row");
    const before = await versions.count();
    await page.locator(".session-note").fill("Припев просел, нужна плотнее");
    await page.getByRole("button", { name: /Создать следующую версию/ }).click();
    await expect(versions).toHaveCount(before + 1);
  });

  test("обработка на демо-пути доходит до конца", async ({ page }) => {
    await page.getByRole("button", { name: /Открыть демо-разбор/ }).click();
    await expect(page.getByRole("heading", { name: /Собираем демо-разбор/ })).toBeVisible();
    await expect(page.getByLabel("Прогресс 100%")).toBeVisible({ timeout: PROCESSING_MS });
    await expect(page.locator(".processing-milestone.skipped")).toHaveCount(0);
  });
});
