import { expect, type Page } from "@playwright/test";

/** Обработка идёт по таймеру: около шести секунд на демо-пути. */
export const PROCESSING_MS = 12_000;

export const openDemo = async (page: Page, name = /Открыть демо-разбор/) => {
  await page.getByRole("button", { name }).click();
  await expect(page.getByRole("tab", { name: /Материалы/ })).toBeVisible({ timeout: PROCESSING_MS });
};

export const openDemoByTitle = async (page: Page, title: string | RegExp) => {
  await page.getByRole("button", { name: title }).click();
  await expect(page.getByRole("tab", { name: /Материалы/ })).toBeVisible({ timeout: PROCESSING_MS });
};

/** Загружает файл песни: маленький валидный WAV собираем прямо здесь, чтобы
 *  не тащить бинарник в репозиторий. */
export const pickOwnFile = async (page: Page, fileName = "moya-pesnya.wav") => {
  const seconds = 3;
  const sampleRate = 44100;
  const samples = seconds * sampleRate;
  const buffer = Buffer.alloc(44 + samples * 4);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + samples * 4, 4);
  buffer.write("WAVEfmt ", 8);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(2, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 4, 28);
  buffer.writeUInt16LE(4, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(samples * 4, 40);
  for (let i = 0; i < samples; i += 1) {
    const value = Math.round(Math.sin((i / sampleRate) * 440 * 2 * Math.PI) * 12000);
    buffer.writeInt16LE(value, 44 + i * 4);
    buffer.writeInt16LE(value, 46 + i * 4);
  }

  await page.setInputFiles('input[type="file"]', { name: fileName, mimeType: "audio/wav", buffer });
  await expect(page.getByText(fileName)).toBeVisible();
};

export const startOwnFileJob = async (page: Page) => {
  await pickOwnFile(page);
  await page.getByRole("checkbox").first().check();
  await page.getByRole("button", { name: /Разобрать мой файл/ }).click();
};

/** Полный проход загрузки до рабочей области. */
export const uploadPath = async (page: Page) => {
  await startOwnFileJob(page);
  await expect(page.getByRole("tab", { name: /Материалы/ })).toBeVisible({ timeout: PROCESSING_MS });
};

export const openTab = async (page: Page, name: RegExp) => {
  await page.getByRole("tab", { name }).click();
  await expect(page.getByRole("tab", { name, selected: true })).toBeVisible();
};

/** Хранилище локальное: между сценариями его надо чистить, иначе песня
 *  предыдущего теста подменяет состояние следующего. */
export const clearStorage = async (page: Page) => {
  await page.goto("/");
  await page.evaluate(() => window.localStorage.clear());
  await page.reload();
};
