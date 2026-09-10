import { describe, expect, it } from "vitest";
import { createApiClient } from "./client";
import { isJobFailed, isJobTerminal, pollJob } from "./poll";
import { fakeRuntime, jsonResponse, networkError, stubFetch } from "./testing";

const job = (over: Record<string, unknown> = {}) => ({
  id: "job-1",
  projectId: "project-1",
  status: "running",
  steps: [],
  warnings: [],
  progressPercent: 40,
  errorCode: null,
  retryCount: 0,
  createdAt: null,
  updatedAt: null,
  pollAfterMs: 500,
  ...over,
});

const clientWith = (fetchImpl: ReturnType<typeof stubFetch>) => {
  const runtime = fakeRuntime(fetchImpl);
  return { client: createApiClient({ baseUrl: "http://api/api", runtime }), runtime };
};

describe("поллинг статуса задания", () => {
  it("спрашивает, пока задание не завершится, и берет паузу у сервера", async () => {
    const fetchImpl = stubFetch([
      jsonResponse(job({ status: "queued", progressPercent: 0, pollAfterMs: 300 })),
      jsonResponse(job({ status: "running", pollAfterMs: 700 })),
      jsonResponse(job({ status: "ready", progressPercent: 100, pollAfterMs: null })),
    ]);
    const { client, runtime } = clientWith(fetchImpl);
    const seen: string[] = [];

    const result = await pollJob(client, "job-1", { onUpdate: (state) => seen.push(state.status) });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.status).toBe("ready");
    expect(fetchImpl.calls).toHaveLength(3);
    expect(runtime.sleeps).toEqual([300, 700]);
    expect(seen).toEqual(["queued", "running", "ready"]);
  });

  it("останавливается на упавшем задании и не выдает его за успех", async () => {
    const fetchImpl = stubFetch([
      jsonResponse(job({ status: "running" })),
      jsonResponse(job({ status: "error", errorCode: "failed_separation", pollAfterMs: null })),
    ]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1");

    expect(fetchImpl.calls).toHaveLength(2);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(isJobTerminal(result.data)).toBe(true);
    expect(isJobFailed(result.data)).toBe(true);
    expect(result.data.errorCode).toBe("failed_separation");
  });

  it("останавливается на отказе сервера и возвращает его как есть", async () => {
    const fetchImpl = stubFetch([
      jsonResponse(
        { error: { code: "not_implemented", message: "Обработки еще нет.", requestId: "r", details: null } },
        { status: 501 },
      ),
    ]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1");

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("http");
    expect(fetchImpl.calls).toHaveLength(1);
  });

  it("переживает одиночный обрыв связи и продолжает спрашивать", async () => {
    const fetchImpl = stubFetch([
      networkError(),
      jsonResponse(job({ status: "ready", pollAfterMs: null })),
    ]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1");

    expect(result.ok).toBe(true);
    expect(fetchImpl.calls).toHaveLength(2);
  });

  it("сдается, когда связь пропала насовсем", async () => {
    const fetchImpl = stubFetch([networkError()]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1", { maxNetworkFailures: 2 });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
    expect(fetchImpl.calls).toHaveLength(2);
  });

  it("отмена останавливает опрос", async () => {
    const controller = new AbortController();
    const fetchImpl = stubFetch([
      () => {
        controller.abort();
        return jsonResponse(job({ status: "running" }));
      },
    ]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1", { signal: controller.signal });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("aborted");
  });

  it("не крутится вечно: предел числа опросов виден в ответе", async () => {
    const fetchImpl = stubFetch([jsonResponse(job({ status: "running" }))]);
    const { client } = clientWith(fetchImpl);

    const result = await pollJob(client, "job-1", { maxAttempts: 3 });

    expect(fetchImpl.calls).toHaveLength(3);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
    if (result.error.kind !== "network") return;
    expect(result.error.reason).toBe("timeout");
  });
});
