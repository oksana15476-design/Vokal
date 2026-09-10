/**
 * Точка входа слоя доступа к серверу.
 *
 * Экраны сюда не ходят: им нужен фасад `src/services/backend.ts`, который сам
 * выбирает источник. Этот файл — для кода, которому нужен именно клиент:
 * тестов, отладочных страниц и будущих служебных экранов.
 */
export { createApiClient, type ApiClient } from "./client";
export { apiModeOf, readEnvApiBase, resolveApiBase, type ApiEnvLike, type ApiMode } from "./config";
export {
  describeFailure,
  isNotImplemented,
  isRetryable,
  unsupported,
  type ApiFailure,
  type ApiResult,
  type HttpFailure,
  type NetworkFailure,
  type SchemaFailure,
} from "./errors";
export {
  DEFAULT_TIMEOUT_MS,
  defaultRetryPolicy,
  type ApiClientConfig,
  type ApiRuntime,
  type RequestOptions,
  type RetryPolicy,
} from "./http";
export { isJobFailed, isJobTerminal, pollJob, type PollJobOptions } from "./poll";
export { uploadFileToTarget, type UploadProgress } from "./upload";
export {
  toProjectView,
  type ProjectExtras,
  type ProjectView,
} from "./mapping";
