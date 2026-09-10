/**
 * Типизированный результат обращения к серверу.
 *
 * Три вида отказа различаются намеренно, потому что они требуют разного от
 * интерфейса и от разработчика:
 *
 * - `network` — до сервера не дошли. Повторить можно, данные не изменились.
 * - `http` — сервер ответил отказом. Повторять бессмысленно, у отказа есть код.
 * - `schema` — сервер ответил не тем, что обещает контракт. Это ошибка
 *   совместимости: чинить надо код, а не запрос.
 *
 * Отдельно стоит `aborted`: отмену нельзя показывать как сбой сети, иначе
 * пользователь получит «нет связи» там, где он сам ушел с экрана. И
 * `unsupported` — честный отказ источника, который такой операции не умеет.
 *
 * Молчаливого проглатывания нет: любая ветка возвращает `ApiResult`, ни одна
 * не отдает `undefined` и не бросает исключение наружу.
 *
 * Тексты в `message` — диагностика для разработчика и логов, а не готовая
 * подпись для экрана: пользовательский текст идет через копирайтера и
 * главреда (CLAUDE.md).
 */

export type NetworkReason = "fetch_failed" | "timeout";

export interface NetworkFailure {
  kind: "network";
  reason: NetworkReason;
  message: string;
  url: string;
  /** Сколько раз попробовали, включая первую попытку. */
  attempts: number;
}

export interface HttpFailure {
  kind: "http";
  status: number;
  /** Машинный код из конверта ошибки. `unparsable_error`, если тело не по контракту. */
  code: string;
  message: string;
  requestId: string | null;
  details: unknown;
  url: string;
}

export interface SchemaFailure {
  kind: "schema";
  message: string;
  /** Путь до поля, на котором ответ разошелся с контрактом. */
  path: string;
  url: string;
  requestId: string | null;
}

export interface AbortedFailure {
  kind: "aborted";
  message: string;
  url: string;
}

export interface UnsupportedFailure {
  kind: "unsupported";
  operation: string;
  message: string;
  /** Чего именно не хватает, чтобы операция заработала. Пустым не бывает. */
  missing: string[];
}

export type ApiFailure =
  | NetworkFailure
  | HttpFailure
  | SchemaFailure
  | AbortedFailure
  | UnsupportedFailure;

export type ApiResult<T> =
  | { ok: true; data: T; requestId: string | null }
  | { ok: false; error: ApiFailure };

export const ok = <T>(data: T, requestId: string | null = null): ApiResult<T> => ({
  ok: true,
  data,
  requestId,
});

export const fail = <T = never>(error: ApiFailure): ApiResult<T> => ({ ok: false, error });

/** Адрес объявлен, реализации еще нет. Не ошибка связи и не поломка клиента. */
export const isNotImplemented = (error: ApiFailure): boolean =>
  error.kind === "http" && (error.status === 501 || error.code === "not_implemented");

/** Отказ, после которого повтор того же запроса имеет смысл. */
export const isRetryable = (error: ApiFailure): boolean => error.kind === "network";

/**
 * Строка для лога и сообщения об ошибке в разработке. На экран не годится:
 * там нужен текст, прошедший копирайтера и главреда.
 */
export const describeFailure = (error: ApiFailure): string => {
  switch (error.kind) {
    case "network":
      return `сеть: ${error.reason}, попыток ${error.attempts}, ${error.url}`;
    case "http":
      return `сервер: ${error.status} ${error.code}${
        error.requestId ? ` (requestId ${error.requestId})` : ""
      }, ${error.url}`;
    case "schema":
      return `схема: поле «${error.path}» не соответствует контракту, ${error.url}`;
    case "aborted":
      return `запрос отменен: ${error.url}`;
    case "unsupported":
      return `операция «${error.operation}» не поддерживается источником: не хватает ${error.missing.join(", ")}`;
  }
};

/** Честный отказ источника, который такой операции не умеет. */
export const unsupported = (operation: string, missing: string[], message: string): ApiFailure => {
  if (missing.length === 0) {
    throw new Error("Отказ обязан называть, чего не хватает: missing пустой.");
  }
  return { kind: "unsupported", operation, missing, message };
};
