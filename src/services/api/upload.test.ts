import { describe, expect, it } from "vitest";
import { uploadFileToTarget } from "./upload";
import { fakeXhr } from "./testing";

const target = {
  method: "PUT",
  url: "https://storage.example/vokal/upload-1",
  headers: { "Content-Type": "audio/mpeg" },
  expiresAt: "2026-09-10T12:00:00Z",
};

const file = new Blob(["звук"], { type: "audio/mpeg" });

describe("загрузка файла с прогрессом", () => {
  it("сообщает прогресс и завершается успехом", async () => {
    const xhr = fakeXhr();
    const seen: number[] = [];

    const promise = uploadFileToTarget(target, file, {
      xhrFactory: () => xhr,
      onProgress: (progress) => seen.push(progress.percent),
    });

    xhr.emitProgress(25, 100);
    xhr.emitProgress(100, 100);
    xhr.emitLoad(200);

    const result = await promise;

    expect(result.ok).toBe(true);
    expect(seen).toEqual([25, 100]);
    expect(xhr.opened).toEqual({ method: "PUT", url: target.url });
    expect(xhr.requestHeaders["content-type"]).toBe("audio/mpeg");
  });

  it("обрыв связи при отправке — это сеть, а не отказ хранилища", async () => {
    const xhr = fakeXhr();
    const promise = uploadFileToTarget(target, file, { xhrFactory: () => xhr });

    xhr.emitError();
    const result = await promise;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
  });

  it("отказ хранилища доезжает кодом ответа", async () => {
    const xhr = fakeXhr();
    const promise = uploadFileToTarget(target, file, { xhrFactory: () => xhr });

    xhr.emitLoad(403, "<Error>AccessDenied</Error>");
    const result = await promise;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("http");
    if (result.error.kind !== "http") return;
    expect(result.error.status).toBe(403);
    expect(result.error.code).toBe("storage_rejected");
  });

  it("отмена отличается от сбоя", async () => {
    const xhr = fakeXhr();
    const controller = new AbortController();
    const promise = uploadFileToTarget(target, file, {
      xhrFactory: () => xhr,
      signal: controller.signal,
    });

    controller.abort();
    xhr.emitAbort();
    const result = await promise;

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("aborted");
  });

  it("без XMLHttpRequest говорит об этом прямо, а не делает вид, что загрузил", async () => {
    // Среда без XHR (тесты в node, серверный рендер): прогресс отправки
    // измерить нечем. Молчаливый успех здесь был бы худшим исходом.
    const result = await uploadFileToTarget(target, file, { xhrFactory: () => null });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("unsupported");
    if (result.error.kind !== "unsupported") return;
    expect(result.error.missing).toContain("XMLHttpRequest");
  });
});
