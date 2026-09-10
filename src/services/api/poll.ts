/**
 * Опрос состояния задания обработки.
 *
 * Realtime-канала пока нет, и контракт устроен так, что он не понадобится:
 * ответ задания самодостаточен, а паузу между вопросами называет сервер
 * (`pollAfterMs`). Клиент не выдумывает интервал сам — иначе очередь получает
 * либо шквал запросов, либо задержку показа готового результата.
 *
 * Две остановки обязательны и обе реализованы: по завершении задания и по
 * ошибке. Третья — по отмене: пользователь ушел с экрана, спрашивать не о чем.
 *
 * Важно для вызывающего: `ok` означает «задание дошло до конечного
 * состояния», а не «все получилось». Упавшее задание — это `ok` со статусом
 * `error`. Иначе пришлось бы прятать причину падения в отказ транспорта.
 */
import type { ApiClient } from "./client";
import type { WireProcessingJob } from "./contract";
import { type ApiFailure, type ApiResult, fail } from "./errors";

export const jobTerminalStatuses = ["ready", "warning", "error"] as const;

export const isJobTerminal = (job: WireProcessingJob): boolean =>
  (jobTerminalStatuses as readonly string[]).includes(job.status);

export const isJobFailed = (job: WireProcessingJob): boolean => job.status === "error";

export interface PollJobOptions {
  signal?: AbortSignal;
  /** Вызывается на каждый полученный снимок, включая последний. */
  onUpdate?: (job: WireProcessingJob) => void;
  /** Пауза, если сервер ее не назвал. */
  fallbackIntervalMs?: number;
  /** Предел числа вопросов. Защита от вечного цикла на зависшем задании. */
  maxAttempts?: number;
  /** Сколько подряд обрывов связи терпим, прежде чем сдаться. */
  maxNetworkFailures?: number;
}

export const pollJob = async (
  client: ApiClient,
  jobId: string,
  options: PollJobOptions = {},
): Promise<ApiResult<WireProcessingJob>> => {
  const fallbackIntervalMs = options.fallbackIntervalMs ?? 1500;
  const maxAttempts = options.maxAttempts ?? 240;
  const maxNetworkFailures = options.maxNetworkFailures ?? 5;

  const aborted = (): ApiResult<WireProcessingJob> =>
    fail({ kind: "aborted", message: "Опрос задания отменен.", url: `${client.baseUrl}/jobs/${jobId}` });

  const pause = async (ms: number): Promise<boolean> => {
    try {
      await client.runtime.sleep(ms, options.signal);
      return true;
    } catch {
      return false;
    }
  };

  let attempts = 0;
  let networkFailures = 0;
  let lastNetworkFailure: ApiFailure | null = null;

  while (attempts < maxAttempts) {
    if (options.signal?.aborted) {
      return aborted();
    }

    attempts += 1;
    // Повтор внутри запроса выключен намеренно: цикл опроса и есть повтор,
    // а два уровня повторов дают непредсказуемую задержку показа.
    const result = await client.getJob(jobId, { signal: options.signal, retry: false });

    if (!result.ok) {
      if (result.error.kind !== "network") {
        return result;
      }

      networkFailures += 1;
      lastNetworkFailure = { ...result.error, attempts: networkFailures };
      if (networkFailures >= maxNetworkFailures) {
        return fail(lastNetworkFailure);
      }

      if (!(await pause(fallbackIntervalMs))) {
        return aborted();
      }
      continue;
    }

    networkFailures = 0;
    options.onUpdate?.(result.data);

    if (isJobTerminal(result.data)) {
      return result;
    }

    if (options.signal?.aborted) {
      return aborted();
    }

    if (!(await pause(result.data.pollAfterMs ?? fallbackIntervalMs))) {
      return aborted();
    }
  }

  return fail({
    kind: "network",
    reason: "timeout",
    message: `Задание не завершилось за ${maxAttempts} вопросов подряд.`,
    url: `${client.baseUrl}/jobs/${jobId}`,
    attempts,
  });
};
