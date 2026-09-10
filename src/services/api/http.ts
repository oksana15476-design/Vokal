/**
 * Ядро обращений к серверу: один запрос, одна классификация отказа, один
 * набор правил повтора.
 *
 * Здесь же живет решение про повторы, и оно узкое намеренно. Повторяем только
 * то, что не дошло до сервера (`network`), и только там, где повтор не создает
 * второй сущности. Ответ сервера — даже `500` — не повторяем: сервер уже
 * что-то сделал, и вторая попытка может сделать это дважды.
 */
import { DecodeError, type Decoder } from "./decode";
import {
  type ApiFailure,
  type ApiResult,
  fail,
  ok,
} from "./errors";

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface ApiRuntime {
  fetch: FetchLike;
  /** Пауза между попытками. Отдельной зависимостью, чтобы тест не ждал вживую. */
  sleep: (ms: number, signal?: AbortSignal) => Promise<void>;
  random: () => number;
}

export interface RetryPolicy {
  /** Всего попыток, включая первую. */
  attempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  factor: number;
}

export const defaultRetryPolicy: RetryPolicy = {
  attempts: 3,
  baseDelayMs: 300,
  maxDelayMs: 4000,
  factor: 2,
};

export const DEFAULT_TIMEOUT_MS = 15000;

export interface RequestOptions {
  signal?: AbortSignal;
  /**
   * Ключ повтора. Без него запись не повторяется: повторный `POST` без ключа —
   * это второй проект, второе списание и второе задание в очереди. Сервер
   * принимает `Idempotency-Key` ровно для этого (`server/app/api/routes/*`).
   */
  idempotencyKey?: string;
  timeoutMs?: number;
  /** `false` — без повторов; объект — переопределение отдельных полей политики. */
  retry?: Partial<RetryPolicy> | false;
  headers?: Record<string, string>;
  query?: Record<string, string | number | boolean | null | undefined>;
}

export interface ApiClientConfig {
  baseUrl: string;
  runtime?: Partial<ApiRuntime>;
  timeoutMs?: number;
  headers?: Record<string, string>;
}

export interface RequestSpec<T> {
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  path: string;
  decoder: Decoder<T>;
  body?: unknown;
}

export const realRuntime: ApiRuntime = {
  fetch: (input, init) => fetch(input, init),
  sleep: (ms, signal) =>
    new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      }, ms);
      const onAbort = () => {
        clearTimeout(timer);
        reject(abortError());
      };
      if (signal?.aborted) {
        clearTimeout(timer);
        reject(abortError());
        return;
      }
      signal?.addEventListener("abort", onAbort, { once: true });
    }),
  random: () => Math.random(),
};

const abortError = (): Error => {
  const error = new Error("Запрос отменен.");
  error.name = "AbortError";
  return error;
};

const isAbort = (error: unknown): boolean =>
  error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError");

const buildUrl = (baseUrl: string, path: string, query?: RequestOptions["query"]): string => {
  const url = `${baseUrl}${path}`;
  if (!query) {
    return url;
  }
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) {
      search.append(key, String(value));
    }
  }
  const rendered = search.toString();
  return rendered ? `${url}?${rendered}` : url;
};

/**
 * Связывает сигнал вызывающего с внутренним сроком ожидания.
 *
 * Собрано руками, а не через `AbortSignal.any`: метод новый, и падение на
 * старом браузере выглядело бы как поломка приложения, а не как отсутствие
 * возможности.
 */
const linkSignals = (
  outer: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; timedOut: () => boolean; dispose: () => void } => {
  const controller = new AbortController();
  let timedOut = false;

  const timer =
    timeoutMs > 0
      ? setTimeout(() => {
          timedOut = true;
          controller.abort();
        }, timeoutMs)
      : null;

  const onOuterAbort = () => controller.abort();
  if (outer?.aborted) {
    controller.abort();
  } else {
    outer?.addEventListener("abort", onOuterAbort, { once: true });
  }

  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    dispose: () => {
      if (timer) clearTimeout(timer);
      outer?.removeEventListener("abort", onOuterAbort);
    },
  };
};

const resolvePolicy = (retry: RequestOptions["retry"]): RetryPolicy | null => {
  if (retry === false) return null;
  return { ...defaultRetryPolicy, ...(retry ?? {}) };
};

/**
 * Повторяем только чтение и только явно идемпотентную запись.
 *
 * `DELETE` по букве HTTP идемпотентен, но у нас он гасит выданную ссылку и
 * пишет строку в аудит-лог; повтор без ключа даст вторую запись о событии,
 * которого не было. Поэтому общее правило одно: `GET`/`HEAD` — можно, все
 * остальное — только с ключом идемпотентности.
 */
const mayRetry = (method: RequestSpec<unknown>["method"], idempotencyKey?: string): boolean =>
  method === "GET" || Boolean(idempotencyKey);

const delayFor = (policy: RetryPolicy, attemptIndex: number, random: () => number): number => {
  const raw = policy.baseDelayMs * policy.factor ** attemptIndex;
  const capped = Math.min(raw, policy.maxDelayMs);
  // Разброс: без него все вкладки, потерявшие связь одновременно, возвращаются
  // к серверу тоже одновременно.
  return Math.round(capped * random());
};

const requestIdOf = (response: Response): string | null =>
  response.headers.get("X-Request-ID") ?? response.headers.get("x-request-id");

const readErrorEnvelope = (
  payload: unknown,
): { code: string; message: string; requestId: string | null; details: unknown } | null => {
  if (typeof payload !== "object" || payload === null) return null;
  const envelope = (payload as { error?: unknown }).error;
  if (typeof envelope !== "object" || envelope === null) return null;
  const body = envelope as Record<string, unknown>;
  if (typeof body.code !== "string" || typeof body.message !== "string") return null;
  return {
    code: body.code,
    message: body.message,
    requestId: typeof body.requestId === "string" ? body.requestId : null,
    details: body.details ?? null,
  };
};

const failureFromResponse = async (response: Response, url: string): Promise<ApiFailure> => {
  const requestId = requestIdOf(response);
  let payload: unknown = null;
  let parsed = false;
  try {
    const text = await response.text();
    payload = text ? JSON.parse(text) : null;
    parsed = true;
  } catch {
    parsed = false;
  }

  const envelope = parsed ? readErrorEnvelope(payload) : null;
  if (envelope) {
    return {
      kind: "http",
      status: response.status,
      code: envelope.code,
      message: envelope.message,
      requestId: envelope.requestId ?? requestId,
      details: envelope.details,
      url,
    };
  }

  // Тело не по контракту: страница прокси, шлюза или другого сервиса. Само
  // тело наружу не отдаем — в нем бывает чужая диагностика.
  return {
    kind: "http",
    status: response.status,
    code: "unparsable_error",
    message: "Сервер ответил отказом в формате, которого нет в контракте.",
    requestId,
    url,
    details: null,
  };
};

const decodeBody = async <T>(
  response: Response,
  decoder: Decoder<T>,
  url: string,
): Promise<ApiResult<T>> => {
  const requestId = requestIdOf(response);
  let payload: unknown;
  try {
    const text = await response.text();
    payload = text ? JSON.parse(text) : null;
  } catch {
    return fail({
      kind: "schema",
      message: "Ответ сервера не является JSON.",
      path: "",
      url,
      requestId,
    });
  }

  try {
    return ok(decoder(payload, ""), requestId);
  } catch (error) {
    if (error instanceof DecodeError) {
      return fail({ kind: "schema", message: error.message, path: error.path, url, requestId });
    }
    throw error;
  }
};

/** Живое окружение, поверх которого положены подмены вызывающего. */
export const resolveRuntime = (partial?: Partial<ApiRuntime>): ApiRuntime => ({
  ...realRuntime,
  ...(partial ?? {}),
});

export const requestJson = async <T>(
  config: ApiClientConfig,
  spec: RequestSpec<T>,
  options: RequestOptions = {},
): Promise<ApiResult<T>> => {
  const runtime = resolveRuntime(config.runtime);
  const url = buildUrl(config.baseUrl, spec.path, options.query);
  const policy = resolvePolicy(options.retry);
  const attemptsAllowed =
    policy && mayRetry(spec.method, options.idempotencyKey) ? Math.max(1, policy.attempts) : 1;

  let attempt = 0;
  let lastFailure: ApiFailure | null = null;

  while (attempt < attemptsAllowed) {
    attempt += 1;

    if (options.signal?.aborted) {
      return fail({ kind: "aborted", message: "Запрос отменен до отправки.", url });
    }

    const link = linkSignals(options.signal, options.timeoutMs ?? config.timeoutMs ?? DEFAULT_TIMEOUT_MS);

    try {
      const headers: Record<string, string> = {
        Accept: "application/json",
        ...(config.headers ?? {}),
        ...(options.headers ?? {}),
      };
      if (spec.body !== undefined) {
        headers["Content-Type"] = "application/json";
      }
      if (options.idempotencyKey) {
        headers["Idempotency-Key"] = options.idempotencyKey;
      }

      const response = await runtime.fetch(url, {
        method: spec.method,
        headers,
        body: spec.body === undefined ? undefined : JSON.stringify(spec.body),
        signal: link.signal,
      });

      if (!response.ok) {
        // Ответ получен: сервер уже отработал запрос. Повторять нечего.
        return fail(await failureFromResponse(response, url));
      }

      return await decodeBody(response, spec.decoder, url);
    } catch (error) {
      if (options.signal?.aborted) {
        return fail({ kind: "aborted", message: "Запрос отменен.", url });
      }

      if (link.timedOut()) {
        lastFailure = {
          kind: "network",
          reason: "timeout",
          message: "Сервер не ответил за отведенное время.",
          url,
          attempts: attempt,
        };
      } else if (isAbort(error)) {
        return fail({ kind: "aborted", message: "Запрос отменен.", url });
      } else {
        lastFailure = {
          kind: "network",
          reason: "fetch_failed",
          message: error instanceof Error ? error.message : "Запрос не дошел до сервера.",
          url,
          attempts: attempt,
        };
      }
    } finally {
      link.dispose();
    }

    if (attempt < attemptsAllowed && policy) {
      try {
        await runtime.sleep(delayFor(policy, attempt - 1, runtime.random), options.signal);
      } catch {
        return fail({ kind: "aborted", message: "Ожидание повтора отменено.", url });
      }
    }
  }

  return fail(
    lastFailure ?? {
      kind: "network",
      reason: "fetch_failed",
      message: "Запрос не дошел до сервера.",
      url,
      attempts: attempt,
    },
  );
};
