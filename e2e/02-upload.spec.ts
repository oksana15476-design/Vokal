import { expect, test } from "@playwright/test";
import { PROCESSING_MS, clearStorage, pickOwnFile, startOwnFileJob, uploadPath, openTab } from "./helpers";

test.describe("Сценарий «свой файл»: правда о том, что сделано", () => {
  test.beforeEach(async ({ page }) => clearStorage(page));

  test("читает свойства выбранного файла", async ({ page }) => {
    await pickOwnFile(page);
    // Длительность, каналы и частота читаются в браузере — это единственное,
    // что прототип действительно делает со звуком.
    await expect(page.locator(".job-card")).toContainText(/WAV/i);
  });

  test("не дает запустить разбор без согласия", async ({ page }) => {
    await pickOwnFile(page);
    await expect(page.getByRole("button", { name: /Разобрать мой файл/ })).toBeDisabled();
    await page.getByRole("checkbox").first().check();
    await expect(page.getByRole("button", { name: /Разобрать мой файл/ })).toBeEnabled();
  });

  test("не рапортует о шагах, которых не было", async ({ page }) => {
    await startOwnFileJob(page);
    await expect(page.getByRole("heading", { name: /Читаем ваш файл/ })).toBeVisible();

    // Утверждаем положительно. Отрицания вида «готовых вех ноль» проходили
    // и после того, как экран сменился на Stage Pack: там нулю равно всё.
    // Все четыре вехи обязаны быть именно пропущенными, а не отсутствующими.
    await expect(page.locator(".processing-milestone")).toHaveCount(4);
    await expect(page.locator(".processing-milestone.skipped")).toHaveCount(4);
    await expect(page.locator(".processing-milestone.skipped").first()).toContainText("не выполняется");

    await expect(page.getByText(/Разбор не создается/)).toBeVisible();
    const disclaimer = await page.locator(".processing-disclaimer").innerText();
    expect(disclaimer).toContain("Звук не обрабатывается");
    expect(disclaimer).not.toContain("Шаги идут по таймеру");
    await expect(page.getByLabel("Прогресс 100%")).toBeVisible({ timeout: PROCESSING_MS });
  });

  test("не оценивает работу, которая не будет выполнена", async ({ page }) => {
    await startOwnFileJob(page);
    // Экран обработки на этом пути живет доли секунды, поэтому сначала
    // убеждаемся, что он на месте и показывает свое содержимое, и только
    // потом — что оценки на нем нет. Иначе проверка «ноль» проходила бы
    // просто потому, что экран уже сменился.
    await expect(page.locator(".processing-focus")).toContainText("Разбор не создается");
    const card = await page.locator(".processing-card").innerText();
    expect(card).not.toContain("Оценка сложности");
    expect(card).not.toContain("условных единиц");
  });

  test("полоса метрик не показывает нули вместо состояния", async ({ page }) => {
    await uploadPath(page);
    const strip = page.getByLabel("Состояние песни");
    await expect(strip).toContainText("разбора песни нет");
    await expect(strip).not.toContainText("0/0");
  });

  test("не выдает чужой разбор и чужой состав за ваши", async ({ page }) => {
    await uploadPath(page);
    await expect(page.locator("body")).not.toContainText("Оксана");
    await expect(page.locator("body")).not.toContainText("Nord Stage");

    await openTab(page, /Состав/);
    await expect(page.getByText(/Нечего адаптировать/)).toBeVisible();
    await expect(page.locator(".empty-reason")).toContainText(/состав не заполнен/i);
  });

  test("объясняет пустоту на каждой вкладке, а не показывает нули", async ({ page }) => {
    await uploadPath(page);

    for (const [tab, text] of [
      [/Материалы/, /собирать их не из чего/i],
      [/Проверка/, /Сомнительных мест нет/i],
      [/AI-директор/, /Предложений пока нет/i],
    ] as const) {
      await openTab(page, tab);
      await expect(page.getByText(text).first()).toBeVisible();
    }
  });

  test("записывает согласие тем же текстом, что показан", async ({ page }) => {
    const shown = (await page.locator(".consent-row span").first().innerText()).trim();
    await uploadPath(page);
    await openTab(page, /Выдача/);
    await expect(page.locator(".privacy-note").filter({ hasText: shown })).toBeVisible();
  });

  test("отклоняет файл неподходящего формата", async ({ page }) => {
    await page.setInputFiles('input[type="file"]', {
      name: "dokument.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 not audio"),
    });
    await expect(page.locator(".job-card")).toContainText(/mp3|wav|flac|m4a/i);
    await expect(page.getByRole("button", { name: /Разобрать мой файл/ })).toBeDisabled();
  });
});
