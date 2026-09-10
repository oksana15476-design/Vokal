import { describe, expect, it } from "vitest";
import { resolveApiBase } from "./config";
import { createApiClient } from "./client";
import { isNotImplemented } from "./errors";
import {
  abortError,
  fakeRuntime,
  hangingFetch,
  jsonResponse,
  networkError,
  stubFetch,
  textResponse,
} from "./testing";

const constraints = {
  maxSizeBytes: 52428800,
  allowedExtensions: ["mp3", "wav", "flac", "m4a"],
  allowedContentTypes: ["audio/mpeg"],
  maxDurationSeconds: null,
  note: "Проверяется расширение, не MIME.",
};

const notImplemented = {
  error: {
    code: "not_implemented",
    message: "Проекты пока не сохраняются на сервере.",
    requestId: "rid-501",
    details: { endpoint: "GET /api/uploads/constraints", missing: ["слой данных"], docs: "docs/api/README.md" },
  },
};

const clientWith = (fetchImpl: ReturnType<typeof stubFetch>, random = 1) => {
  const runtime = fakeRuntime(fetchImpl, random);
  return { client: createApiClient({ baseUrl: "http://127.0.0.1:8000/api", runtime }), runtime };
};

describe("переключатель источника данных", () => {
  it("пустая переменная означает моки, а не адрес по умолчанию", () => {
    expect(resolveApiBase({})).toBeNull();
    expect(resolveApiBase({ VITE_API_BASE: "" })).toBeNull();
    expect(resolveApiBase({ VITE_API_BASE: "   " })).toBeNull();
  });

  it("снимает хвостовой слеш, чтобы адрес не собирался с двойным", () => {
    expect(resolveApiBase({ VITE_API_BASE: "http://127.0.0.1:8000/api/" })).toBe(
      "http://127.0.0.1:8000/api",
    );
  });

  it("падает на непонятном адресе вместо тихого отката на моки", () => {
    // Тихий откат — худший исход: разработчик думает, что смотрит на сервер,
    // а видит моки.
    expect(() => resolveApiBase({ VITE_API_BASE: "не адрес" })).toThrow(/VITE_API_BASE/);
  });

  it("новое имя переменной сильнее прежнего VITE_API_BASE_URL", () => {
    expect(
      resolveApiBase({ VITE_API_BASE: "http://a/api", VITE_API_BASE_URL: "http://b/api" }),
    ).toBe("http://a/api");
    expect(resolveApiBase({ VITE_API_BASE_URL: "http://b/api" })).toBe("http://b/api");
  });
});

describe("успешный ответ", () => {
  it("разбирается по схеме и отдает идентификатор запроса", async () => {
    const fetchImpl = stubFetch([jsonResponse(constraints, { requestId: "rid-1" })]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.maxSizeBytes).toBe(52428800);
    expect(result.data.allowedExtensions).toEqual(["mp3", "wav", "flac", "m4a"]);
    expect(result.requestId).toBe("rid-1");
    expect(fetchImpl.calls[0].url).toBe("http://127.0.0.1:8000/api/uploads/constraints");
  });
});

describe("разбор ошибок", () => {
  it("обрыв связи — это «сеть недоступна», а не пустой ответ", async () => {
    const fetchImpl = stubFetch([networkError()]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints({ retry: false });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
    if (result.error.kind !== "network") return;
    expect(result.error.reason).toBe("fetch_failed");
    expect(result.error.attempts).toBe(1);
  });

  it("501 доезжает кодом и перечнем недостающего, а не молчанием", async () => {
    const fetchImpl = stubFetch([jsonResponse(notImplemented, { status: 501, requestId: "rid-501" })]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("http");
    if (result.error.kind !== "http") return;
    expect(result.error.status).toBe(501);
    expect(result.error.code).toBe("not_implemented");
    expect(result.error.requestId).toBe("rid-501");
    expect(isNotImplemented(result.error)).toBe(true);
  });

  it("ошибка не в формате конверта остается ошибкой сервера, а не схемы", async () => {
    // Страница прокси или шлюза: код ответа известен, тело — нет.
    const fetchImpl = stubFetch([textResponse("<html>502 Bad Gateway</html>", 502)]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints({ retry: false });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("http");
    if (result.error.kind !== "http") return;
    expect(result.error.status).toBe(502);
    expect(result.error.code).toBe("unparsable_error");
  });

  it("несоответствие схемы называет поле, а не «что-то пошло не так»", async () => {
    const fetchImpl = stubFetch([jsonResponse({ ...constraints, maxSizeBytes: "много" })]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("schema");
    if (result.error.kind !== "schema") return;
    expect(result.error.path).toBe("maxSizeBytes");
  });

  it("не-JSON в успешном ответе — тоже несоответствие схемы", async () => {
    const fetchImpl = stubFetch([textResponse("<html>hello</html>", 200)]);
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("schema");
  });
});

describe("отмена запроса", () => {
  it("отмена отличается от обрыва связи", async () => {
    const controller = new AbortController();
    const fetchImpl = stubFetch([abortError()]);
    const { client } = clientWith(fetchImpl);
    controller.abort();

    const result = await client.getUploadConstraints({ signal: controller.signal });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("aborted");
  });

  it("сигнал доезжает до fetch, а не проверяется только на входе", async () => {
    const controller = new AbortController();
    const fetchImpl = stubFetch([jsonResponse(constraints)]);
    const { client } = clientWith(fetchImpl);

    await client.getUploadConstraints({ signal: controller.signal });

    expect(fetchImpl.calls[0].signalAborted).toBe(false);
    controller.abort();
  });
});

describe("срок ожидания ответа", () => {
  it("молчащий сервер дает сетевой отказ, а не вечное ожидание", async () => {
    const fetchImpl = hangingFetch();
    const { client } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints({ timeoutMs: 5, retry: false });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
    if (result.error.kind !== "network") return;
    expect(result.error.reason).toBe("timeout");
  });
});

describe("повтор с экспоненциальной задержкой", () => {
  it("повторяет чтение после сетевого сбоя и растит паузу", async () => {
    const fetchImpl = stubFetch([networkError(), networkError(), jsonResponse(constraints)]);
    const { client, runtime } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(true);
    expect(fetchImpl.calls).toHaveLength(3);
    expect(runtime.sleeps).toEqual([300, 600]);
  });

  it("на ошибку сервера повтора нет: ответ получен, повторять нечего", async () => {
    const fetchImpl = stubFetch([jsonResponse(notImplemented, { status: 501 })]);
    const { client, runtime } = clientWith(fetchImpl);

    await client.getUploadConstraints();

    expect(fetchImpl.calls).toHaveLength(1);
    expect(runtime.sleeps).toEqual([]);
  });

  it("запись без ключа идемпотентности не повторяется", async () => {
    const fetchImpl = stubFetch([networkError()]);
    const { client } = clientWith(fetchImpl);

    const result = await client.startJob("project-1", {});

    expect(fetchImpl.calls).toHaveLength(1);
    expect(result.ok).toBe(false);
  });

  it("запись с ключом идемпотентности повторяется и шлет тот же ключ", async () => {
    const fetchImpl = stubFetch([
      networkError(),
      jsonResponse({
        id: "job-1",
        projectId: "project-1",
        status: "queued",
        steps: [],
        warnings: [],
        progressPercent: 0,
        retryCount: 0,
      }),
    ]);
    const { client } = clientWith(fetchImpl);

    const result = await client.startJob("project-1", {}, { idempotencyKey: "key-1" });

    expect(result.ok).toBe(true);
    expect(fetchImpl.calls).toHaveLength(2);
    expect(fetchImpl.calls.map((call) => call.headers["idempotency-key"])).toEqual([
      "key-1",
      "key-1",
    ]);
  });

  it("сдается после исчерпания попыток и говорит, сколько их было", async () => {
    const fetchImpl = stubFetch([networkError()]);
    const { client, runtime } = clientWith(fetchImpl);

    const result = await client.getUploadConstraints();

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
    if (result.error.kind !== "network") return;
    expect(result.error.attempts).toBe(3);
    expect(runtime.sleeps).toHaveLength(2);
  });

  it("пауза не растет бесконечно: есть предел", async () => {
    const fetchImpl = stubFetch([networkError()]);
    const { client, runtime } = clientWith(fetchImpl);

    await client.getUploadConstraints({ retry: { attempts: 6, maxDelayMs: 1000 } });

    expect(runtime.sleeps).toEqual([300, 600, 1000, 1000, 1000]);
  });
});
