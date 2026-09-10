// @vitest-environment node
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * Типы клиента генерируются из контракта сервера — решение записано в
 * docs/architecture.md. Файл `schema.d.ts` создается машиной, но лежит в
 * репозитории, чтобы сборка не зависела от генератора.
 *
 * Отсюда риск: контракт поправят, а файл забудут перегенерировать, и клиент
 * молча разойдется с сервером. Ровно так это уже случилось однажды — клиент
 * на 1117 строк был написан руками против записанного решения и разошелся с
 * сервером в 24 местах.
 */
describe("типы клиента соответствуют контракту сервера", () => {
  it("schema.d.ts перегенерируется из openapi.json без изменений", () => {
    const current = readFileSync("src/services/api/schema.d.ts", "utf8");
    const fresh = execFileSync(
      "npx",
      ["openapi-typescript", "docs/api/openapi.json"],
      { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 },
    );

    expect(
      fresh.trim(),
      "контракт изменился, а типы клиента — нет. Выполните `npm run api:types`.",
    ).toBe(current.trim());
  }, 120_000);
});
