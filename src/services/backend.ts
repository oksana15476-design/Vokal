/**
 * Единый вход к данным для экранов.
 *
 * Смысл слоя: вызывающий код не знает, откуда пришел проект — из моков или с
 * сервера. Это прямо записано в `docs/architecture.md`: «компоненты не знают,
 * был ли результат получен из мока, AudioShake, Klangio или нашего backend».
 *
 * Источник выбирается один раз, по `VITE_API_BASE` (см. `api/config.ts`).
 * Пусто — моки, задано — сервер.
 *
 * `mockServices.ts` не переписан и не продублирован: моковый источник вызывает
 * его функции как есть. Там лежат доменные правила продукта, и второй их
 * экземпляр разошелся бы с первым на первой же правке.
 *
 * Два правила честности, которые тут важнее удобства:
 *
 * 1. **Источник, который чего-то не умеет, говорит об этом.** Моки не умеют
 *    загружать файл и обрабатывать звук; на сервере нет адреса для заметки
 *    после занятия. Все три случая возвращают отказ `unsupported` с перечнем
 *    недостающего, а не правдоподобную выдумку.
 * 2. **Домен не подгоняется под ответ сервера.** Там, где доменная модель
 *    фронтенда не умеет выразить ответ (состояние загрузки, состояние
 *    удаления, отозванная ссылка), значение уезжает в `extras`, а не
 *    подменяется похожим.
 */
import type {
  DirectorActionId,
  Project,
  ProcessingGoalId,
  ReviewStatus,
  Scenario,
  UploadProjectInput,
} from "../domain/types";
import { currentConsent } from "../domain/consent";
import {
  addReviewComment as mockAddReviewComment,
  addSessionNote as mockAddSessionNote,
  addUnderstoodNothingReply as mockUnderstoodNothing,
  applyDirectorAction as mockApplyDirectorAction,
  applyDirectorActions as mockApplyDirectorActions,
  createProjectFromUpload as mockCreateProjectFromUpload,
  createShareLinks as mockCreateShareLinks,
  deleteProjectResults as mockDeleteResults,
  deleteProjectSource as mockDeleteSource,
  listDemoProjects,
  maxUploadBytes,
  rebuildExportBundle as mockRebuildExportBundle,
  rollbackToVersion as mockRollbackToVersion,
  supportedUploadExtensions,
  updateReviewIssue as mockUpdateReviewIssue,
  validateUploadFile,
} from "./mockServices";
import { type ApiClient, createApiClient } from "./api/client";
import { type ApiEnvLike, resolveApiBase } from "./api/config";
import type {
  WireProcessingJob,
  WireProject,
  WireUploadConstraints,
} from "./api/contract";
import { type ApiFailure, type ApiResult, fail, ok, unsupported } from "./api/errors";
import type { ApiRuntime, RequestOptions } from "./api/http";
import {
  type ProjectView,
  emptyExtras,
  toProjectView,
} from "./api/mapping";
import { type PollJobOptions, pollJob } from "./api/poll";
import { type UploadProgress, uploadFileToTarget } from "./api/upload";

export type BackendMode = "mock" | "server";

export interface ProjectListItem {
  id: string;
  name: string;
  scenario: Scenario;
  goalId: ProcessingGoalId;
  fileName: string;
  sourceDeleted: boolean;
  resultsDeleted: boolean;
}

export interface DeletionAcceptedView {
  projectId: string;
  /** `purge_requested` — задача принята; `purged` — хранилище отчиталось. */
  state: "present" | "purge_requested" | "purged" | "purge_failed";
  requestedAt: string;
  revokedLinksCount: number | null;
}

export interface UploadedFileView {
  uploadId: string;
  fileName: string;
  sizeBytes: number | null;
}

export interface JobView {
  jobId: string;
  projectId: string;
  status: WireProcessingJob["status"];
  progressPercent: number;
  warnings: string[];
  errorCode: string | null;
}

export interface ConsentView {
  id: string;
  text: string;
}

export interface CreateProjectInput {
  input: UploadProjectInput;
  /** Идентификатор принятой загрузки. Серверу без него создавать проект не из чего. */
  uploadId?: string;
}

export interface DirectorActionOptions {
  baseVersionId?: string;
  userCommand?: string;
  comment?: string;
}

export interface UploadFileOptions {
  signal?: AbortSignal;
  onProgress?: (progress: UploadProgress) => void;
  facts?: { durationSeconds?: number; sampleRate?: number; channels?: number };
}

export interface Backend {
  readonly mode: BackendMode;
  readonly baseUrl: string | null;

  /** Локальная проверка файла до отправки. Одинакова у обоих источников. */
  validateFile(file: { name: string; size: number }): string | null;

  getConsent(options?: RequestOptions): Promise<ApiResult<ConsentView>>;
  getUploadConstraints(options?: RequestOptions): Promise<ApiResult<WireUploadConstraints>>;

  listProjects(options?: RequestOptions): Promise<ApiResult<ProjectListItem[]>>;
  getProject(projectId: string, options?: RequestOptions): Promise<ApiResult<ProjectView>>;
  createProject(input: CreateProjectInput, options?: RequestOptions): Promise<ApiResult<ProjectView>>;
  renameProject(
    projectId: string,
    name: string,
    options?: RequestOptions,
  ): Promise<ApiResult<ProjectView>>;

  uploadFile(file: File, options?: UploadFileOptions): Promise<ApiResult<UploadedFileView>>;
  startProcessing(
    projectId: string,
    options?: { goalId?: ProcessingGoalId; idempotencyKey?: string; signal?: AbortSignal },
  ): Promise<ApiResult<JobView>>;
  watchProcessing(jobId: string, options?: PollJobOptions): Promise<ApiResult<JobView>>;

  applyDirectorAction(
    projectId: string,
    actionId: DirectorActionId,
    options?: DirectorActionOptions,
  ): Promise<ApiResult<ProjectView>>;
  applyDirectorActions(
    projectId: string,
    actionIds: DirectorActionId[],
    options?: DirectorActionOptions,
  ): Promise<ApiResult<ProjectView>>;
  sendDirectorChat(projectId: string, text: string): Promise<ApiResult<ProjectView>>;
  rollbackToVersion(projectId: string, versionId: string): Promise<ApiResult<ProjectView>>;
  updateReviewIssue(
    projectId: string,
    issueId: string,
    status: ReviewStatus,
  ): Promise<ApiResult<ProjectView>>;
  addReviewComment(projectId: string, issueId: string, text: string): Promise<ApiResult<ProjectView>>;
  createShareLink(projectId: string, recipientId: string): Promise<ApiResult<ProjectView>>;
  rebuildExportBundle(projectId: string): Promise<ApiResult<ProjectView>>;
  addSessionNote(projectId: string, note: string): Promise<ApiResult<ProjectView>>;

  deleteSource(projectId: string): Promise<ApiResult<DeletionAcceptedView>>;
  deleteResults(projectId: string): Promise<ApiResult<DeletionAcceptedView>>;
}

export interface BackendOptions {
  env?: ApiEnvLike;
  runtime?: Partial<ApiRuntime>;
  headers?: Record<string, string>;
}

const nowIso = () => new Date().toISOString();

/* ------------------------------------------------------------------ */
/* Моковый источник                                                    */
/* ------------------------------------------------------------------ */

/**
 * Реестр песен для моков — на время сессии, в памяти.
 *
 * Это не подмена `projectStorage.ts`: тот хранит песни между перезагрузками
 * для экрана, а здесь нужен адресуемый по идентификатору набор, чтобы фасад
 * умел `getProject(id)` так же, как сервер. Когда экраны переедут на фасад,
 * реестр можно будет свести с хранилищем — отдельной задачей.
 */
const createRegistry = () => {
  const projects = new Map<string, Project>();
  for (const project of listDemoProjects()) {
    projects.set(project.id, project);
  }
  return projects;
};

const notFound = (projectId: string): ApiFailure => ({
  kind: "http",
  status: 404,
  code: "not_found",
  message: `Песня «${projectId}» не найдена в моковом источнике.`,
  requestId: null,
  details: null,
  url: `mock://projects/${projectId}`,
});

const mockView = (project: Project): ProjectView => ({ project, extras: emptyExtras });

const createMockBackend = (): Backend => {
  const registry = createRegistry();

  const change = (
    projectId: string,
    apply: (project: Project) => Project,
  ): Promise<ApiResult<ProjectView>> => {
    const project = registry.get(projectId);
    if (!project) {
      return Promise.resolve(fail<ProjectView>(notFound(projectId)));
    }
    const updated = apply(project);
    registry.set(projectId, updated);
    return Promise.resolve(ok(mockView(updated)));
  };

  return {
    mode: "mock",
    baseUrl: null,

    validateFile: validateUploadFile,

    getConsent: async () => {
      const consent = currentConsent();
      return ok({ id: consent.id, text: consent.text });
    },

    getUploadConstraints: async () =>
      ok<WireUploadConstraints>({
        maxSizeBytes: maxUploadBytes,
        allowedExtensions: [...supportedUploadExtensions],
        allowedContentTypes: [],
        maxDurationSeconds: null,
        note: "Ограничения мокового источника: проверяется расширение и размер файла.",
      }),

    listProjects: async () =>
      ok(
        [...registry.values()].map((project) => ({
          id: project.id,
          name: project.name,
          scenario: project.scenario,
          goalId: project.processingGoal.id,
          fileName: project.upload.fileName,
          sourceDeleted: project.dataRetention.sourceDeleted,
          resultsDeleted: project.dataRetention.resultsDeleted,
        })),
      ),

    getProject: async (projectId) => {
      const project = registry.get(projectId);
      return project ? ok(mockView(project)) : fail<ProjectView>(notFound(projectId));
    },

    createProject: async ({ input }) => {
      const project = mockCreateProjectFromUpload(input);
      registry.set(project.id, project);
      return ok(mockView(project));
    },

    renameProject: (projectId, name) => change(projectId, (project) => ({ ...project, name })),

    uploadFile: async () =>
      fail<UploadedFileView>(
        unsupported(
          "uploadFile",
          ["объектное хранилище", "адрес POST /api/uploads"],
          "Моковый источник не отправляет файл: хранилища нет, файл остается на устройстве.",
        ),
      ),

    startProcessing: async () =>
      fail<JobView>(
        unsupported(
          "startProcessing",
          ["обработка звука на сервере", "очередь заданий"],
          "Моковый источник не обрабатывает звук: шаги обработки показывает экран, результата за ними нет.",
        ),
      ),

    watchProcessing: async () =>
      fail<JobView>(
        unsupported(
          "watchProcessing",
          ["обработка звука на сервере", "очередь заданий"],
          "Спрашивать статус нечего: задания в моках не существует.",
        ),
      ),

    applyDirectorAction: (projectId, actionId, options) =>
      change(projectId, (project) => mockApplyDirectorAction(project, actionId, options?.userCommand)),

    applyDirectorActions: (projectId, actionIds, options) =>
      change(projectId, (project) =>
        mockApplyDirectorActions(project, actionIds, options?.userCommand),
      ),

    sendDirectorChat: (projectId, text) =>
      change(projectId, (project) => mockUnderstoodNothing(project, text)),

    rollbackToVersion: (projectId, versionId) =>
      change(projectId, (project) => mockRollbackToVersion(project, versionId)),

    updateReviewIssue: (projectId, issueId, status) =>
      change(projectId, (project) => mockUpdateReviewIssue(project, issueId, status)),

    addReviewComment: (projectId, issueId, text) =>
      change(projectId, (project) => mockAddReviewComment(project, issueId, text)),

    createShareLink: (projectId, recipientId) =>
      change(projectId, (project) => mockCreateShareLinks(project, [recipientId])),

    rebuildExportBundle: (projectId) => change(projectId, mockRebuildExportBundle),

    addSessionNote: (projectId, note) =>
      change(projectId, (project) => mockAddSessionNote(project, note)),

    deleteSource: async (projectId) => {
      const project = registry.get(projectId);
      if (!project) {
        return fail<DeletionAcceptedView>(notFound(projectId));
      }
      registry.set(projectId, mockDeleteSource(project));
      // В моках удалять нечего, поэтому состояние сразу конечное. На сервере
      // так не будет: там до подтверждения хранилища состояние промежуточное.
      return ok<DeletionAcceptedView>({
        projectId,
        state: "purged",
        requestedAt: nowIso(),
        revokedLinksCount: null,
      });
    },

    deleteResults: async (projectId) => {
      const project = registry.get(projectId);
      if (!project) {
        return fail<DeletionAcceptedView>(notFound(projectId));
      }
      const updated = mockDeleteResults(project);
      registry.set(projectId, updated);
      return ok<DeletionAcceptedView>({
        projectId,
        state: "purged",
        requestedAt: nowIso(),
        revokedLinksCount: updated.shareLinks.length,
      });
    },
  };
};

/* ------------------------------------------------------------------ */
/* Серверный источник                                                  */
/* ------------------------------------------------------------------ */

const toJobView = (wire: WireProcessingJob): JobView => ({
  jobId: wire.id,
  projectId: wire.projectId,
  status: wire.status,
  progressPercent: wire.progressPercent,
  warnings: wire.warnings,
  errorCode: wire.errorCode ?? null,
});

const createServerBackend = (client: ApiClient): Backend => {
  /**
   * Правка на сервере возвращает свой узкий результат (версию, место
   * проверки, ссылку), а экрану нужна карточка целиком. Поэтому после правки
   * идет повторное чтение проекта — один лишний запрос вместо сборки
   * состояния из кусков на клиенте. Собранное из кусков состояние однажды
   * разойдется с серверным, и разойдется молча.
   */
  const reload = async <T>(
    projectId: string,
    result: ApiResult<T>,
  ): Promise<ApiResult<ProjectView>> => {
    if (!result.ok) {
      return fail<ProjectView>(result.error);
    }
    return withView(await client.getProject(projectId));
  };

  const withView = (result: ApiResult<WireProject>): ApiResult<ProjectView> =>
    result.ok ? ok(toProjectView(result.data), result.requestId) : fail<ProjectView>(result.error);

  return {
    mode: "server",
    baseUrl: client.baseUrl,

    validateFile: validateUploadFile,

    getConsent: async (options) => {
      const result = await client.getCurrentConsent(options);
      return result.ok
        ? ok({ id: result.data.id, text: result.data.text }, result.requestId)
        : fail<ConsentView>(result.error);
    },

    getUploadConstraints: (options) => client.getUploadConstraints(options),

    listProjects: async (options) => {
      const result = await client.listProjects(undefined, options);
      return result.ok
        ? ok(
            result.data.items.map((item) => ({
              id: item.id,
              name: item.name,
              scenario: item.scenario,
              goalId: item.goalId,
              fileName: item.fileName,
              sourceDeleted: item.sourceDeleted,
              resultsDeleted: item.resultsDeleted,
            })),
            result.requestId,
          )
        : fail<ProjectListItem[]>(result.error);
    },

    getProject: async (projectId, options) => withView(await client.getProject(projectId, options)),

    createProject: async ({ input, uploadId }, options) => {
      if (!uploadId) {
        return fail<ProjectView>(
          unsupported(
            "createProject",
            ["идентификатор принятой загрузки"],
            "Сервер создает проект из уже принятого файла: сначала uploadFile, потом createProject.",
          ),
        );
      }
      if (!input.setup) {
        return fail<ProjectView>(
          unsupported(
            "createProject",
            ["типизированная настройка сценария (ProjectSetup)"],
            "Сервер не принимает проект без настройки сценария: сводка для показа ее не заменяет.",
          ),
        );
      }

      const result = await client.createProject(
        {
          uploadId,
          scenario: input.scenario,
          goalId: input.goalId,
          setup: input.setup,
          setupSnapshot: input.setupSnapshot ?? null,
          consent: { accepted: input.acceptedConsent, versionId: currentConsent().id },
        },
        { ...options, idempotencyKey: options?.idempotencyKey ?? `create-project-${uploadId}` },
      );
      return withView(result);
    },

    renameProject: async (projectId, name, options) =>
      withView(await client.renameProject(projectId, name, options)),

    uploadFile: async (file, options) => {
      const created = await client.createUpload(
        {
          fileName: file.name,
          sizeBytes: file.size,
          contentType: file.type || null,
          durationSeconds: options?.facts?.durationSeconds ?? null,
          sampleRate: options?.facts?.sampleRate ?? null,
          channels: options?.facts?.channels ?? null,
        },
        { signal: options?.signal },
      );
      if (!created.ok) {
        return fail<UploadedFileView>(created.error);
      }

      const sent = await uploadFileToTarget(created.data.target, file, {
        signal: options?.signal,
        onProgress: options?.onProgress,
      });
      if (!sent.ok) {
        return fail<UploadedFileView>(sent.error);
      }

      const completed = await client.completeUpload(
        created.data.upload.id,
        { sizeBytes: file.size },
        { signal: options?.signal, idempotencyKey: `complete-${created.data.upload.id}` },
      );
      return completed.ok
        ? ok<UploadedFileView>({
            uploadId: completed.data.id,
            fileName: completed.data.fileName,
            sizeBytes: completed.data.sizeBytes ?? null,
          })
        : fail<UploadedFileView>(completed.error);
    },

    startProcessing: async (projectId, options) => {
      const result = await client.startJob(
        projectId,
        { goalId: options?.goalId ?? null },
        { signal: options?.signal, idempotencyKey: options?.idempotencyKey },
      );
      return result.ok ? ok(toJobView(result.data), result.requestId) : fail<JobView>(result.error);
    },

    watchProcessing: async (jobId, options) => {
      const result = await pollJob(client, jobId, options);
      return result.ok ? ok(toJobView(result.data), result.requestId) : fail<JobView>(result.error);
    },

    applyDirectorAction: async (projectId, actionId, options) => {
      if (!options?.baseVersionId) {
        return fail<ProjectView>(
          unsupported(
            "applyDirectorAction",
            ["идентификатор версии, к которой применяется действие"],
            "Сервер требует базовую версию: иначе правка ляжет на версию, которой пользователь уже не видит.",
          ),
        );
      }
      return reload(
        projectId,
        await client.applyDirectorAction(projectId, {
          actionId,
          baseVersionId: options.baseVersionId,
          comment: options.comment ?? null,
        }),
      );
    },

    applyDirectorActions: async (projectId, actionIds, options) => {
      if (!options?.baseVersionId) {
        return fail<ProjectView>(
          unsupported(
            "applyDirectorActions",
            ["идентификатор версии, к которой применяются действия"],
            "Сервер требует базовую версию для сборки одной версии из нескольких действий.",
          ),
        );
      }
      return reload(
        projectId,
        await client.applyDirectorActions(projectId, {
          actionIds,
          baseVersionId: options.baseVersionId,
          comment: options.comment ?? null,
        }),
      );
    },

    sendDirectorChat: async (projectId, text) =>
      reload(projectId, await client.sendDirectorChat(projectId, text)),

    rollbackToVersion: async (projectId, versionId) =>
      reload(projectId, await client.rollbackVersion(projectId, versionId)),

    updateReviewIssue: async (projectId, issueId, status) =>
      reload(projectId, await client.updateReviewIssue(projectId, issueId, { status })),

    addReviewComment: async (projectId, issueId, text) =>
      reload(projectId, await client.addReviewComment(projectId, issueId, { text })),

    createShareLink: async (projectId, recipientId) =>
      reload(projectId, await client.createShareLink(projectId, { recipientId })),

    rebuildExportBundle: async (projectId) =>
      reload(projectId, await client.createExportBundle(projectId, {})),

    addSessionNote: async () =>
      fail<ProjectView>(
        unsupported(
          "addSessionNote",
          ["адрес в контракте: заметки «После репетиции» и «После урока» в нем нет"],
          "Сервер не умеет сохранять заметку после занятия: такого адреса в контракте нет.",
        ),
      ),

    deleteSource: async (projectId) => {
      const result = await client.deleteSource(
        projectId,
        { confirm: true },
        { idempotencyKey: `delete-source-${projectId}` },
      );
      return result.ok
        ? ok<DeletionAcceptedView>({
            projectId: result.data.projectId,
            state: result.data.state,
            requestedAt: result.data.requestedAt,
            revokedLinksCount: result.data.revokedLinksCount ?? null,
          })
        : fail<DeletionAcceptedView>(result.error);
    },

    deleteResults: async (projectId) => {
      const result = await client.deleteResults(
        projectId,
        { confirm: true },
        { idempotencyKey: `delete-results-${projectId}` },
      );
      return result.ok
        ? ok<DeletionAcceptedView>({
            projectId: result.data.projectId,
            state: result.data.state,
            requestedAt: result.data.requestedAt,
            revokedLinksCount: result.data.revokedLinksCount ?? null,
          })
        : fail<DeletionAcceptedView>(result.error);
    },
  };
};

/* ------------------------------------------------------------------ */
/* Сборка                                                              */
/* ------------------------------------------------------------------ */

const envFromBuild = (): ApiEnvLike =>
  (import.meta as unknown as { env?: ApiEnvLike }).env ?? {};

export const createBackend = (options: BackendOptions = {}): Backend => {
  const baseUrl = resolveApiBase(options.env ?? envFromBuild());
  if (!baseUrl) {
    return createMockBackend();
  }

  return createServerBackend(
    createApiClient({ baseUrl, runtime: options.runtime, headers: options.headers }),
  );
};

let shared: Backend | null = null;

/**
 * Общий экземпляр для приложения.
 *
 * Ленивая сборка, а не константа модуля: разбор адреса умеет бросить
 * исключение на неверном значении, и пусть это случится в момент первого
 * обращения, а не при загрузке любого модуля, который случайно потянул этот
 * файл за собой.
 */
export const getBackend = (): Backend => {
  if (!shared) {
    shared = createBackend();
  }
  return shared;
};

export type { ProjectView } from "./api/mapping";
export type { ApiFailure, ApiResult } from "./api/errors";
