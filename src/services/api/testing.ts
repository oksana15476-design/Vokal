/**
 * Подставные части окружения для тестов клиента.
 *
 * Лежит рядом с кодом, а не в тестовом файле, потому что подставной fetch
 * нужен трем наборам тестов сразу. В сборку приложения модуль не попадает:
 * его никто не импортирует из `client.ts` и `backend.ts`.
 */
import type { ApiRuntime } from "./http";

export interface StubCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: string | null;
  signalAborted: boolean;
}

export interface StubFetch {
  (input: string | URL | Request, init?: RequestInit): Promise<Response>;
  calls: StubCall[];
}

type Reply = Response | Error | (() => Response | Error | Promise<Response | Error>);

/**
 * Очередь ответов. Последний ответ повторяется, если запросов больше, чем
 * заготовок: иначе тест на повторы пришлось бы кормить копиями одного ответа.
 */
export const stubFetch = (replies: Reply[]): StubFetch => {
  const calls: StubCall[] = [];
  let index = 0;

  const impl = async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const headers: Record<string, string> = {};
    new Headers(init?.headers ?? {}).forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });

    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers,
      body: typeof init?.body === "string" ? init.body : null,
      signalAborted: init?.signal?.aborted ?? false,
    });

    if (init?.signal?.aborted) {
      throw abortError();
    }

    const reply = replies[Math.min(index, replies.length - 1)];
    index += 1;
    const resolved = typeof reply === "function" ? await reply() : reply;
    if (resolved instanceof Error) {
      throw resolved;
    }

    // Клон обязателен: тело `Response` читается один раз, а очередь повторяет
    // последний ответ. Без клона второй вопрос получал бы «пустое тело» и
    // тест ловил бы ошибку помощника, а не поведение клиента.
    return resolved.clone();
  };

  const stub = impl as StubFetch;
  stub.calls = calls;
  return stub;
};

/** Запрос, который не ответит никогда: живет до отмены. Нужен для срока ожидания. */
export const hangingFetch = (): StubFetch => {
  const calls: StubCall[] = [];
  const impl = (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      headers: {},
      body: null,
      signalAborted: init?.signal?.aborted ?? false,
    });
    return new Promise<Response>((_, reject) => {
      init?.signal?.addEventListener("abort", () => reject(abortError()), { once: true });
    });
  };
  const stub = impl as StubFetch;
  stub.calls = calls;
  return stub;
};

export const abortError = (): Error => {
  const error = new Error("The operation was aborted.");
  error.name = "AbortError";
  return error;
};

/** Обрыв связи так, как его сообщает браузер: `TypeError: Failed to fetch`. */
export const networkError = (): Error => new TypeError("Failed to fetch");

export const jsonResponse = (
  body: unknown,
  init: { status?: number; requestId?: string } = {},
): Response =>
  new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: {
      "Content-Type": "application/json",
      ...(init.requestId ? { "X-Request-ID": init.requestId } : {}),
    },
  });

export const textResponse = (body: string, status = 200): Response =>
  new Response(body, { status, headers: { "Content-Type": "text/html" } });

/** Часы теста: сон записывается, а не проживается. */
export interface FakeRuntime extends ApiRuntime {
  sleeps: number[];
}

export const fakeRuntime = (fetchImpl: StubFetch, random = 1): FakeRuntime => {
  const sleeps: number[] = [];
  const runtime: FakeRuntime = {
    fetch: fetchImpl,
    sleep: async (ms: number, signal?: AbortSignal) => {
      sleeps.push(ms);
      if (signal?.aborted) {
        throw abortError();
      }
    },
    random: () => random,
    sleeps,
  };
  return runtime;
};

/* ------------------------------------------------------------------ */
/* Подставной XMLHttpRequest для загрузки файла с прогрессом            */
/* ------------------------------------------------------------------ */

import type { XhrLike, XhrProgressEvent } from "./upload";

export interface FakeXhr extends XhrLike {
  /** Что записали в открытом запросе. */
  opened: { method: string; url: string } | null;
  sentBody: unknown;
  requestHeaders: Record<string, string>;
  emitProgress: (loaded: number, total: number) => void;
  emitLoad: (status: number, responseText?: string) => void;
  emitError: () => void;
  emitAbort: () => void;
}

export const fakeXhr = (): FakeXhr => {
  const handlers: Record<string, Array<(event: XhrProgressEvent) => void>> = {};
  const uploadHandlers: Record<string, Array<(event: XhrProgressEvent) => void>> = {};

  const xhr: FakeXhr = {
    opened: null,
    sentBody: undefined,
    requestHeaders: {},
    status: 0,
    responseText: "",
    upload: {
      addEventListener: (type, handler) => {
        uploadHandlers[type] = [...(uploadHandlers[type] ?? []), handler];
      },
    },
    open: (method, url) => {
      xhr.opened = { method, url };
    },
    setRequestHeader: (name, value) => {
      xhr.requestHeaders[name.toLowerCase()] = value;
    },
    send: (body) => {
      xhr.sentBody = body;
    },
    abort: () => {
      (handlers.abort ?? []).forEach((handler) => handler({ loaded: 0, total: 0, lengthComputable: false }));
    },
    addEventListener: (type, handler) => {
      handlers[type] = [...(handlers[type] ?? []), handler];
    },
    emitProgress: (loaded, total) => {
      (uploadHandlers.progress ?? []).forEach((handler) =>
        handler({ loaded, total, lengthComputable: total > 0 }),
      );
    },
    emitLoad: (status, responseText = "") => {
      xhr.status = status;
      xhr.responseText = responseText;
      (handlers.load ?? []).forEach((handler) => handler({ loaded: 0, total: 0, lengthComputable: false }));
    },
    emitError: () => {
      (handlers.error ?? []).forEach((handler) => handler({ loaded: 0, total: 0, lengthComputable: false }));
    },
    emitAbort: () => {
      (handlers.abort ?? []).forEach((handler) => handler({ loaded: 0, total: 0, lengthComputable: false }));
    },
  };

  return xhr;
};
