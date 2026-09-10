/**
 * Клиент REST API Vokal Director.
 *
 * Один метод — один адрес контракта (`docs/architecture.md`, «Основные API»,
 * и роутеры `server/app/api/routes/*`). Каждый метод возвращает `ApiResult`:
 * ошибок наружу не бросаем, потому что обрыв связи и отказ сервера — это
 * состояния экрана, а не исключения.
 *
 * Клиент ничего не знает про моки. Подмена источника живет уровнем выше, в
 * `src/services/backend.ts`.
 */
import type { ReviewStatus } from "../../domain/types";
import {
  type DeletionRequest,
  type JobCreateRequest,
  type JobRetryRequest,
  type ProjectCreateRequest,
  type UploadCompleteRequest,
  type UploadCreateRequest,
  type WireArrangementVersion,
  type WireArtifact,
  type WireArtifactDownload,
  type WireArtifactList,
  type WireConsentVersion,
  type WireConsentVersionList,
  type WireDeletionAccepted,
  type WireDeletionStatus,
  type WireDirectorActionResponse,
  type WireDirectorChatResponse,
  type WireDirectorSuggestionList,
  type WireExportBundle,
  type WireProcessingJob,
  type WireProject,
  type WireProjectList,
  type WireReviewComment,
  type WireReviewIssue,
  type WireShareLink,
  type WireShareRecipient,
  type WireStagePackResponse,
  type WireUpload,
  type WireUploadConstraints,
  type WireUploadCreateResponse,
  type WireVersionList,
  type WireVersionRollback,
  artifactDecoder,
  artifactDownloadDecoder,
  artifactListDecoder,
  arrangementVersionDecoder,
  consentVersionDecoder,
  consentVersionListDecoder,
  deletionAcceptedDecoder,
  deletionStatusDecoder,
  directorActionResponseDecoder,
  directorChatResponseDecoder,
  directorSuggestionListDecoder,
  exportBundleDecoder,
  listOf,
  processingJobDecoder,
  projectDecoder,
  projectListDecoder,
  reviewCommentDecoder,
  reviewIssueDecoder,
  shareLinkDecoder,
  shareRecipientDecoder,
  stagePackResponseDecoder,
  uploadConstraintsDecoder,
  uploadCreateResponseDecoder,
  uploadDecoder,
  versionListDecoder,
  versionRollbackDecoder,
} from "./contract";
import { empty } from "./decode";
import type { ApiResult } from "./errors";
import {
  type ApiClientConfig,
  type ApiRuntime,
  type RequestOptions,
  requestJson,
  resolveRuntime,
} from "./http";

/** Действия директора: одно или пакетом. */
export interface DirectorActionRequest {
  actionId: string;
  baseVersionId: string;
  comment?: string | null;
}

export interface DirectorActionBatchRequest {
  actionIds: string[];
  baseVersionId: string;
  label?: string | null;
  comment?: string | null;
}

export interface ShareLinkCreateRequest {
  recipientId: string;
  artifactIds?: string[];
  expiresInHours?: number | null;
  label?: string | null;
}

export interface ExportBundleCreateRequest {
  audience?: string | null;
  artifactIds?: string[];
  label?: string | null;
}

export interface ListQuery {
  limit?: number;
  offset?: number;
  scenario?: string;
}

export interface ApiClient {
  readonly baseUrl: string;
  /** Окружение клиента. Нужно опросу задания: пауза берется отсюда, а не из глобального таймера. */
  readonly runtime: ApiRuntime;

  /* согласие */
  getCurrentConsent(options?: RequestOptions): Promise<ApiResult<WireConsentVersion>>;
  listConsentVersions(options?: RequestOptions): Promise<ApiResult<WireConsentVersionList>>;

  /* загрузка */
  getUploadConstraints(options?: RequestOptions): Promise<ApiResult<WireUploadConstraints>>;
  createUpload(
    body: UploadCreateRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireUploadCreateResponse>>;
  completeUpload(
    uploadId: string,
    body: UploadCompleteRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireUpload>>;
  getUpload(uploadId: string, options?: RequestOptions): Promise<ApiResult<WireUpload>>;

  /* проекты */
  listProjects(query?: ListQuery, options?: RequestOptions): Promise<ApiResult<WireProjectList>>;
  createProject(
    body: ProjectCreateRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireProject>>;
  getProject(projectId: string, options?: RequestOptions): Promise<ApiResult<WireProject>>;
  renameProject(
    projectId: string,
    name: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireProject>>;

  /* обработка */
  startJob(
    projectId: string,
    body: JobCreateRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireProcessingJob>>;
  getJob(jobId: string, options?: RequestOptions): Promise<ApiResult<WireProcessingJob>>;
  retryJob(
    jobId: string,
    body: JobRetryRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireProcessingJob>>;

  /* материалы */
  getStagePack(
    projectId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireStagePackResponse>>;
  listArtifacts(
    projectId: string,
    query?: ListQuery,
    options?: RequestOptions,
  ): Promise<ApiResult<WireArtifactList>>;
  getArtifact(
    projectId: string,
    artifactId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireArtifact>>;
  getArtifactDownload(
    projectId: string,
    artifactId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireArtifactDownload>>;

  /* версии */
  listVersions(projectId: string, options?: RequestOptions): Promise<ApiResult<WireVersionList>>;
  getVersion(
    projectId: string,
    versionId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireArrangementVersion>>;
  selectVersion(
    projectId: string,
    versionId: string,
    comment?: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireArrangementVersion>>;
  rollbackVersion(
    projectId: string,
    versionId: string,
    body?: { comment?: string | null; label?: string | null },
    options?: RequestOptions,
  ): Promise<ApiResult<WireVersionRollback>>;

  /* директор */
  listSuggestions(
    projectId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDirectorSuggestionList>>;
  applyDirectorAction(
    projectId: string,
    body: DirectorActionRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDirectorActionResponse>>;
  applyDirectorActions(
    projectId: string,
    body: DirectorActionBatchRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDirectorActionResponse>>;
  sendDirectorChat(
    projectId: string,
    text: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDirectorChatResponse>>;

  /* проверка */
  listReviewIssues(
    projectId: string,
    query?: ListQuery,
    options?: RequestOptions,
  ): Promise<ApiResult<{ items: WireReviewIssue[]; total: number }>>;
  updateReviewIssue(
    projectId: string,
    issueId: string,
    body: { status: ReviewStatus; comment?: string | null },
    options?: RequestOptions,
  ): Promise<ApiResult<WireReviewIssue>>;
  addReviewComment(
    projectId: string,
    issueId: string,
    body: { text: string; author?: string | null },
    options?: RequestOptions,
  ): Promise<ApiResult<WireReviewComment>>;

  /* выдача */
  listRecipients(
    projectId: string,
    query?: ListQuery,
    options?: RequestOptions,
  ): Promise<ApiResult<{ items: WireShareRecipient[]; total: number }>>;
  createRecipient(
    projectId: string,
    body: { name: string; role: string; material?: string | null },
    options?: RequestOptions,
  ): Promise<ApiResult<WireShareRecipient>>;
  updateRecipient(
    projectId: string,
    recipientId: string,
    body: { name?: string; role?: string; material?: string | null },
    options?: RequestOptions,
  ): Promise<ApiResult<WireShareRecipient>>;
  listShareLinks(
    projectId: string,
    query?: ListQuery,
    options?: RequestOptions,
  ): Promise<ApiResult<{ items: WireShareLink[]; total: number }>>;
  createShareLink(
    projectId: string,
    body: ShareLinkCreateRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireShareLink>>;
  revokeShareLink(
    projectId: string,
    linkId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<null>>;
  listExportBundles(
    projectId: string,
    query?: ListQuery,
    options?: RequestOptions,
  ): Promise<ApiResult<{ items: WireExportBundle[]; total: number }>>;
  createExportBundle(
    projectId: string,
    body: ExportBundleCreateRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireExportBundle>>;
  getExportBundle(
    projectId: string,
    bundleId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireExportBundle>>;

  /* удаление */
  deleteSource(
    projectId: string,
    body: DeletionRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDeletionAccepted>>;
  deleteResults(
    projectId: string,
    body: DeletionRequest,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDeletionAccepted>>;
  getDeletionStatus(
    projectId: string,
    options?: RequestOptions,
  ): Promise<ApiResult<WireDeletionStatus>>;
}

const encode = (value: string): string => encodeURIComponent(value);

export const createApiClient = (config: ApiClientConfig): ApiClient => {
  const get = <T>(path: string, decoder: Parameters<typeof requestJson<T>>[1]["decoder"], options?: RequestOptions) =>
    requestJson<T>(config, { method: "GET", path, decoder }, options);

  const send = <T>(
    method: "POST" | "PATCH" | "DELETE",
    path: string,
    decoder: Parameters<typeof requestJson<T>>[1]["decoder"],
    body?: unknown,
    options?: RequestOptions,
  ) => requestJson<T>(config, { method, path, decoder, body }, options);

  return {
    baseUrl: config.baseUrl,
    runtime: resolveRuntime(config.runtime),

    getCurrentConsent: (options) => get("/consent/current", consentVersionDecoder, options),
    listConsentVersions: (options) => get("/consent/versions", consentVersionListDecoder, options),

    getUploadConstraints: (options) => get("/uploads/constraints", uploadConstraintsDecoder, options),
    createUpload: (body, options) => send("POST", "/uploads", uploadCreateResponseDecoder, body, options),
    completeUpload: (uploadId, body, options) =>
      send("POST", `/uploads/${encode(uploadId)}/complete`, uploadDecoder, body, options),
    getUpload: (uploadId, options) => get(`/uploads/${encode(uploadId)}`, uploadDecoder, options),

    listProjects: (query, options) =>
      get("/projects", projectListDecoder, { ...options, query: { ...query, ...options?.query } }),
    createProject: (body, options) => send("POST", "/projects", projectDecoder, body, options),
    getProject: (projectId, options) => get(`/projects/${encode(projectId)}`, projectDecoder, options),
    renameProject: (projectId, name, options) =>
      send("PATCH", `/projects/${encode(projectId)}`, projectDecoder, { name }, options),

    startJob: (projectId, body, options) =>
      send("POST", `/projects/${encode(projectId)}/jobs`, processingJobDecoder, body, options),
    getJob: (jobId, options) => get(`/jobs/${encode(jobId)}`, processingJobDecoder, options),
    retryJob: (jobId, body, options) =>
      send("POST", `/jobs/${encode(jobId)}/retry`, processingJobDecoder, body, options),

    getStagePack: (projectId, options) =>
      get(`/projects/${encode(projectId)}/stage-pack`, stagePackResponseDecoder, options),
    listArtifacts: (projectId, query, options) =>
      get(`/projects/${encode(projectId)}/artifacts`, artifactListDecoder, {
        ...options,
        query: { ...query, ...options?.query },
      }),
    getArtifact: (projectId, artifactId, options) =>
      get(`/projects/${encode(projectId)}/artifacts/${encode(artifactId)}`, artifactDecoder, options),
    getArtifactDownload: (projectId, artifactId, options) =>
      get(
        `/projects/${encode(projectId)}/artifacts/${encode(artifactId)}/download`,
        artifactDownloadDecoder,
        options,
      ),

    listVersions: (projectId, options) =>
      get(`/projects/${encode(projectId)}/versions`, versionListDecoder, options),
    getVersion: (projectId, versionId, options) =>
      get(
        `/projects/${encode(projectId)}/versions/${encode(versionId)}`,
        arrangementVersionDecoder,
        options,
      ),
    selectVersion: (projectId, versionId, comment, options) =>
      send(
        "PATCH",
        `/projects/${encode(projectId)}/versions/${encode(versionId)}/select`,
        arrangementVersionDecoder,
        { comment: comment ?? null },
        options,
      ),
    rollbackVersion: (projectId, versionId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/versions/${encode(versionId)}/rollback`,
        versionRollbackDecoder,
        body ?? {},
        options,
      ),

    listSuggestions: (projectId, options) =>
      get(`/projects/${encode(projectId)}/director/suggestions`, directorSuggestionListDecoder, options),
    applyDirectorAction: (projectId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/director/actions`,
        directorActionResponseDecoder,
        body,
        options,
      ),
    applyDirectorActions: (projectId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/director/actions/batch`,
        directorActionResponseDecoder,
        body,
        options,
      ),
    sendDirectorChat: (projectId, text, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/director/chat`,
        directorChatResponseDecoder,
        { text },
        options,
      ),

    listReviewIssues: (projectId, query, options) =>
      get(`/projects/${encode(projectId)}/review-issues`, listOf(reviewIssueDecoder), {
        ...options,
        query: { ...query, ...options?.query },
      }),
    updateReviewIssue: (projectId, issueId, body, options) =>
      send(
        "PATCH",
        `/projects/${encode(projectId)}/review-issues/${encode(issueId)}`,
        reviewIssueDecoder,
        body,
        options,
      ),
    addReviewComment: (projectId, issueId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/review-issues/${encode(issueId)}/comments`,
        reviewCommentDecoder,
        body,
        options,
      ),

    listRecipients: (projectId, query, options) =>
      get(`/projects/${encode(projectId)}/recipients`, listOf(shareRecipientDecoder), {
        ...options,
        query: { ...query, ...options?.query },
      }),
    createRecipient: (projectId, body, options) =>
      send("POST", `/projects/${encode(projectId)}/recipients`, shareRecipientDecoder, body, options),
    updateRecipient: (projectId, recipientId, body, options) =>
      send(
        "PATCH",
        `/projects/${encode(projectId)}/recipients/${encode(recipientId)}`,
        shareRecipientDecoder,
        body,
        options,
      ),
    listShareLinks: (projectId, query, options) =>
      get(`/projects/${encode(projectId)}/share-links`, listOf(shareLinkDecoder), {
        ...options,
        query: { ...query, ...options?.query },
      }),
    createShareLink: (projectId, body, options) =>
      send("POST", `/projects/${encode(projectId)}/share-links`, shareLinkDecoder, body, options),
    revokeShareLink: (projectId, linkId, options) =>
      send(
        "DELETE",
        `/projects/${encode(projectId)}/share-links/${encode(linkId)}`,
        empty,
        undefined,
        options,
      ),
    listExportBundles: (projectId, query, options) =>
      get(`/projects/${encode(projectId)}/export-bundles`, listOf(exportBundleDecoder), {
        ...options,
        query: { ...query, ...options?.query },
      }),
    createExportBundle: (projectId, body, options) =>
      send("POST", `/projects/${encode(projectId)}/export-bundles`, exportBundleDecoder, body, options),
    getExportBundle: (projectId, bundleId, options) =>
      get(
        `/projects/${encode(projectId)}/export-bundles/${encode(bundleId)}`,
        exportBundleDecoder,
        options,
      ),

    deleteSource: (projectId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/delete-source`,
        deletionAcceptedDecoder,
        body,
        options,
      ),
    deleteResults: (projectId, body, options) =>
      send(
        "POST",
        `/projects/${encode(projectId)}/delete-results`,
        deletionAcceptedDecoder,
        body,
        options,
      ),
    getDeletionStatus: (projectId, options) =>
      get(`/projects/${encode(projectId)}/deletion-status`, deletionStatusDecoder, options),
  };
};
