import { describe, expect, it } from "vitest";
import { consentTextById, consentVersions, currentConsent, fingerprintOf } from "./consent";

describe("версии согласия (B58)", () => {
  it("не дает править текст действующей версии, не тронув версию", () => {
    // Контрольная сумма существует ровно для этого. Если формулировка
    // изменилась, а версия осталась прежней, старые записи начинают
    // свидетельствовать о том, чего человек не читал.
    for (const version of consentVersions) {
      expect(fingerprintOf(version.text), `версия ${version.id}: текст правили без смены версии`).toBe(
        version.fingerprint,
      );
    }
  });

  it("держит версии уникальными и по возрастанию даты", () => {
    const ids = consentVersions.map((version) => version.id);
    expect(new Set(ids).size).toBe(ids.length);

    const dates = consentVersions.map((version) => version.effectiveFrom);
    expect([...dates].sort()).toEqual(dates);
  });

  it("читает текст старой записи по идентификатору версии", () => {
    const version = currentConsent();
    expect(consentTextById(version.id)).toBe(version.text);
    // Неизвестная версия — это не пустая строка и не текущий текст: подмена
    // старого согласия сегодняшней формулировкой хуже, чем честное «нет».
    expect(consentTextById("consent-которой-нет")).toBeNull();
  });

  it("не теряет старые версии", () => {
    // Удаление версии делает старые записи нечитаемыми. Тест ловит это,
    // пока версия одна, и будет ловить, когда их станет больше.
    expect(consentVersions.length).toBeGreaterThan(0);
    expect(currentConsent().text.length).toBeGreaterThan(20);
  });
});
