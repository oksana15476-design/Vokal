/**
 * Отправка файла по выданному адресу — с прогрессом.
 *
 * Почему `XMLHttpRequest`, а не `fetch`: у `fetch` нет события прогресса
 * отправки. Песня весит десятки мегабайт, и полоса, которая не двигается, —
 * это интерфейс, про который пользователь думает, что он завис.
 *
 * Куда именно уходит файл, этот модуль не знает и знать не должен: метод,
 * адрес и заголовки приходят с сервера в `UploadTarget`
 * (`server/app/api/schemas/uploads.py`).
 *
 * Сейчас там стоит адрес нашего же API — `PUT /api/uploads/{upload_id}/content`.
 * Файл идет **через приложение**, а не мимо него по подписанной ссылке:
 * развилка закрыта решением от 2026-09-10 в `server/app/storage/base.py`.
 * Причина — провайдер объектного хранения не выбран, а presign против
 * невыбранного провайдера снаружи выглядит работающим, внутри пуст.
 *
 * Цена решения названа там же и принята осознанно: сервер читает тело в
 * память процесса целиком (`await request.body()` в
 * `server/app/api/routes/uploads.py`), и на время передачи песня занимает
 * этот процесс. Когда провайдер будет выбран, в `UploadTarget` встанет
 * подписанная ссылка — код ниже менять не придется, он и сейчас отправляет
 * туда, куда сказано.
 */
import { type ApiResult, fail, ok, unsupported } from "./errors";

export interface XhrProgressEvent {
  loaded: number;
  total: number;
  lengthComputable: boolean;
}

/** Минимальная часть `XMLHttpRequest`, которой мы пользуемся. */
export interface XhrLike {
  status: number;
  responseText: string;
  upload: {
    addEventListener: (type: "progress", handler: (event: XhrProgressEvent) => void) => void;
  };
  open: (method: string, url: string) => void;
  setRequestHeader: (name: string, value: string) => void;
  send: (body: unknown) => void;
  abort: () => void;
  addEventListener: (
    type: "load" | "error" | "abort" | "timeout",
    handler: (event: XhrProgressEvent) => void,
  ) => void;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  /** 0..100. Ноль, если размер неизвестен: выдуманного процента здесь нет. */
  percent: number;
}

export interface UploadTargetLike {
  method: string;
  url: string;
  headers?: Record<string, string>;
}

export interface UploadFileOptions {
  signal?: AbortSignal;
  onProgress?: (progress: UploadProgress) => void;
  headers?: Record<string, string>;
  /** Подмена транспорта для тестов и для сред без XHR. */
  xhrFactory?: () => XhrLike | null;
}

const defaultXhrFactory = (): XhrLike | null => {
  const global = globalThis as { XMLHttpRequest?: new () => XhrLike };
  return global.XMLHttpRequest ? new global.XMLHttpRequest() : null;
};

export const uploadFileToTarget = (
  target: UploadTargetLike,
  file: Blob,
  options: UploadFileOptions = {},
): Promise<ApiResult<null>> => {
  const xhr = (options.xhrFactory ?? defaultXhrFactory)();

  if (!xhr) {
    return Promise.resolve(
      fail<null>(
        unsupported(
          "uploadFileToTarget",
          ["XMLHttpRequest"],
          "В этой среде нет XMLHttpRequest: отправить файл с прогрессом нечем.",
        ),
      ),
    );
  }

  if (options.signal?.aborted) {
    return Promise.resolve(
      fail<null>({ kind: "aborted", message: "Отправка отменена до начала.", url: target.url }),
    );
  }

  return new Promise<ApiResult<null>>((resolve) => {
    let settled = false;
    const finish = (result: ApiResult<null>) => {
      if (settled) return;
      settled = true;
      options.signal?.removeEventListener("abort", onAbortSignal);
      resolve(result);
    };

    const onAbortSignal = () => {
      xhr.abort();
      finish(fail<null>({ kind: "aborted", message: "Отправка отменена.", url: target.url }));
    };

    xhr.upload.addEventListener("progress", (event) => {
      const total = event.lengthComputable ? event.total : 0;
      options.onProgress?.({
        loaded: event.loaded,
        total,
        percent: total > 0 ? Math.round((event.loaded / total) * 100) : 0,
      });
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        finish(ok<null>(null));
        return;
      }
      // Тело ответа не разбираем и наружу не отдаем: формат ошибки у
      // принимающей стороны свой. Сейчас адрес наш
      // (`PUT /api/uploads/{upload_id}/content`), и в теле лежит наш конверт,
      // но читать его здесь нельзя — тот же код обязан работать и с
      // подписанной ссылкой провайдера, когда она появится.
      // Слово «хранилище» в тексте ниже, пока адрес наш, неточно; текст
      // пользовательский, и его правка идет через копирайтера и главреда.
      finish(
        fail<null>({
          kind: "http",
          status: xhr.status,
          code: "storage_rejected",
          message: "Хранилище отказалось принять файл.",
          requestId: null,
          details: null,
          url: target.url,
        }),
      );
    });

    xhr.addEventListener("error", () => {
      finish(
        fail<null>({
          kind: "network",
          reason: "fetch_failed",
          message: "Файл не дошел до хранилища.",
          url: target.url,
          attempts: 1,
        }),
      );
    });

    xhr.addEventListener("timeout", () => {
      finish(
        fail<null>({
          kind: "network",
          reason: "timeout",
          message: "Хранилище не ответило за отведенное время.",
          url: target.url,
          attempts: 1,
        }),
      );
    });

    xhr.addEventListener("abort", () => {
      finish(fail<null>({ kind: "aborted", message: "Отправка отменена.", url: target.url }));
    });

    options.signal?.addEventListener("abort", onAbortSignal, { once: true });

    xhr.open(target.method || "PUT", target.url);
    for (const [name, value] of Object.entries({ ...(target.headers ?? {}), ...(options.headers ?? {}) })) {
      xhr.setRequestHeader(name, value);
    }
    xhr.send(file);
  });
};
