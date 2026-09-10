import type { components } from "./schema";

/**
 * Типы приходят из контракта сервера, а не пишутся руками: источник правды —
 * OpenAPI (docs/architecture.md). Раньше они дублировались, и клиент успел
 * разойтись с сервером в 24 местах — например, объявлял обязательным поле,
 * которое сервер может не прислать.
 */
type Schemas = components["schemas"];

/**
 * Типы и проверки ответов сервера — ровно то, что объявлено в
 * `server/app/api/schemas/*`.
 *
 * Почему это отдельный слой, а не прямое использование `src/domain/types.ts`:
 * контракт и доменная модель фронтенда местами расходятся, и расхождение
 * осознанное. Сервер шлет устойчивые латинские ключи (`role: "guitar"`), а в
 * домене фронтенда на этих местах стоят русские подписи (`role: "гитара"`).
 * Сервер объясняет это в `server/app/api/schemas/enums.py`: через границу API
 * нельзя гонять отображаемую подпись как ключ данных — на этом продукт уже
 * обжигался.
 *
 * Здесь лежит форма провода. Перевод в домен — в `mapping.ts`, и он явный:
 * таблицей, которую видно и можно проверить тестом.
 */
import type {
  ProcessingGoal,
  ProcessingGoalId,
  Scenario,
} from "../../domain/types";
import {
  type Decoder,
  anything,
  arr,
  bool,
  nullable,
  num,
  obj,
  oneOf,
  record,
  str,
  withDefault,
} from "./decode";

/* ------------------------------------------------------------------ */
/* Закрытые списки контракта                                           */
/* ------------------------------------------------------------------ */

export const scenarios = ["band", "education"] as const;
export const goalIds = [
  "band-analysis",
  "band-rehearsal",
  "band-performance",
  "band-minus",
  "band-parts",
  "band-transpose",
  "band-adapt-lineup",
  "band-boost",
  "lesson-analysis",
  "lesson-easy",
  "lesson-original",
  "lesson-advanced",
  "lesson-concert",
  "lesson-ensemble",
  "lesson-homework",
  "lesson-practice-tracks",
] as const;
export const uploadFormats = ["MP3", "WAV", "FLAC", "M4A", "DEMO"] as const;
export const uploadQualities = ["good", "medium", "low"] as const;
export const uploadStates = ["awaiting_file", "stored", "rejected", "purged"] as const;
export const jobStatuses = ["queued", "running", "ready", "warning", "error"] as const;
export const stepStatuses = ["queued", "running", "done", "warning", "error", "skipped"] as const;
export const analysisSources = ["demo", "none"] as const;
export const versionKinds = [
  "original",
  "band",
  "easy",
  "original-like",
  "advanced",
  "concert",
  "ensemble",
  "after-rehearsal",
  "after-lesson",
] as const;
export const versionStatuses = ["draft", "needs_review", "approved", "distributed"] as const;
export const artifactTypes = [
  "score",
  "part",
  "tab",
  "chords",
  "lyrics",
  "midi",
  "stem",
  "minus",
  "click",
  "practice",
  "teacher",
  "student",
  "zip",
] as const;
export const artifactFormats = ["PDF", "MIDI", "WAV", "ZIP", "MusicXML", "VIEW"] as const;
export const artifactStatuses = [
  "ready",
  "draft",
  "needs_review",
  "rebuild_required",
  "pending",
] as const;
export const artifactAudiences = ["all", "band", "teacher", "student", "instrument"] as const;
export const previewKinds = ["notation", "waveform", "midi", "bundle", "text"] as const;
export const reviewStatuses = [
  "needs_review",
  "checked",
  "fixed",
  "uncertain",
  "accepted_for_rehearsal",
] as const;
export const directorActionIds = [
  "transpose-down-2",
  "merge-guitars",
  "move-strings-to-keys",
  "simplify-drums",
  "beginner-bass",
  "boost-chorus",
  "practice-without-bass",
  "education-version",
  "advanced-student-part",
  "student-ensemble",
  "lesson-analysis",
] as const;
export const suggestionScopes = ["band", "education", "both"] as const;
export const suggestionImpacts = ["arrangement", "education", "export", "review"] as const;
export const chatAuthors = ["user", "director"] as const;
export const musicianRoles = ["vocal", "guitar", "bass", "keys", "drums", "backing_vocal"] as const;
export const musicianLevels = ["beginner", "middle", "advanced"] as const;
export const bassStrings = ["4_strings", "5_strings"] as const;
export const studentLevels = ["starter", "middle", "strong"] as const;
export const notationReadings = ["none", "simple", "confident"] as const;
export const teacherFormats = ["individual", "group", "school_ensemble"] as const;
export const lessonDifficulties = ["easier", "original_like", "harder"] as const;
export const assignmentStatuses = [
  "assigned",
  "in_progress",
  "analyzed",
  "ready_for_concert",
] as const;
export const recipientRoles = [
  "vocalist",
  "guitarist",
  "bassist",
  "keys",
  "drummer",
  "teacher",
  "student",
  "parent",
] as const;
export const recipientStatuses = ["not_issued", "issued", "opened", "needs_fix"] as const;
export const shareLinkStatuses = ["active", "stale", "revoked", "expired"] as const;
export const exportBundleStatuses = ["ready", "stale", "pending"] as const;
export const costTiers = ["fast_draft", "accurate", "multi_version"] as const;
export const costComplexities = ["low", "medium", "high"] as const;
export const deletionStates = ["present", "purge_requested", "purged", "purge_failed"] as const;

export type WireUploadState = (typeof uploadStates)[number];
export type WireMusicianRole = (typeof musicianRoles)[number];
export type WireMusicianLevel = (typeof musicianLevels)[number];
export type WireBassStrings = (typeof bassStrings)[number];
export type WireStudentLevel = (typeof studentLevels)[number];
export type WireNotationReading = (typeof notationReadings)[number];
export type WireTeacherFormat = (typeof teacherFormats)[number];
export type WireLessonDifficulty = (typeof lessonDifficulties)[number];
export type WireShareLinkStatus = (typeof shareLinkStatuses)[number];
export type WireDeletionState = (typeof deletionStates)[number];
export type WireVersionStatus = (typeof versionStatuses)[number];

/* ------------------------------------------------------------------ */
/* Согласие                                                            */
/* ------------------------------------------------------------------ */

export type WireConsentVersion = Schemas["ConsentVersionOut"];

export const consentVersionDecoder: Decoder<WireConsentVersion> = obj({
  id: str,
  effectiveFrom: str,
  text: str,
  fingerprint: num,
});

export type WireConsentVersionList = Schemas["ConsentVersionListResponse"];

export const consentVersionListDecoder: Decoder<WireConsentVersionList> = obj({
  items: arr(consentVersionDecoder),
  currentId: str,
});

/* ------------------------------------------------------------------ */
/* Загрузка                                                            */
/* ------------------------------------------------------------------ */

export type WireUploadConstraints = Schemas["UploadConstraints"];

export const uploadConstraintsDecoder: Decoder<WireUploadConstraints> = obj({
  maxSizeBytes: num,
  allowedExtensions: arr(str),
  allowedContentTypes: arr(str),
  maxDurationSeconds: nullable(num),
  note: str,
});

export type WireUpload = Schemas["UploadOut"];

export const uploadDecoder: Decoder<WireUpload> = obj({
  id: str,
  fileName: str,
  format: oneOf(uploadFormats),
  state: oneOf(uploadStates),
  durationSeconds: num,
  quality: oneOf(uploadQualities),
  sourceNote: str,
  sizeBytes: nullable(num),
  sampleRate: nullable(num),
  channels: nullable(num),
  createdAt: str,
});

export type WireUploadTarget = Schemas["UploadTarget"];

export const uploadTargetDecoder: Decoder<WireUploadTarget> = obj({
  method: str,
  url: str,
  headers: withDefault(record(str), {}),
  expiresAt: str,
});

export type WireUploadCreateResponse = Schemas["UploadCreateResponse"];

export const uploadCreateResponseDecoder: Decoder<WireUploadCreateResponse> = obj({
  upload: uploadDecoder,
  target: uploadTargetDecoder,
});

export interface UploadCreateRequest {
  fileName: string;
  sizeBytes: number;
  contentType?: string | null;
  durationSeconds?: number | null;
  sampleRate?: number | null;
  channels?: number | null;
}

export interface UploadCompleteRequest {
  sizeBytes: number;
  checksum?: string | null;
}

/* ------------------------------------------------------------------ */
/* Обработка                                                           */
/* ------------------------------------------------------------------ */

export type WireProcessingStep = Schemas["ProcessingStepOut"];

export const processingStepDecoder: Decoder<WireProcessingStep> = obj({
  id: str,
  label: str,
  status: oneOf(stepStatuses),
  detail: withDefault(str, ""),
});

export type WireProcessingJob = Schemas["ProcessingJobOut"];

export const processingJobDecoder: Decoder<WireProcessingJob> = obj({
  id: str,
  projectId: str,
  status: oneOf(jobStatuses),
  steps: arr(processingStepDecoder),
  warnings: withDefault(arr(str), []),
  progressPercent: num,
  errorCode: nullable(str),
  retryCount: withDefault(num, 0),
  createdAt: nullable(str),
  updatedAt: nullable(str),
  pollAfterMs: nullable(num),
});

export interface JobCreateRequest {
  goalId?: ProcessingGoalId | null;
  forceRestart?: boolean;
}

export interface JobRetryRequest {
  fromStepId?: string | null;
}

/* ------------------------------------------------------------------ */
/* Разбор песни                                                        */
/* ------------------------------------------------------------------ */

export const processingGoalDecoder: Decoder<ProcessingGoal> = obj({
  id: oneOf(goalIds),
  scenario: oneOf(scenarios),
  label: str,
  description: str,
  expectedOutputs: arr(str),
});

export type WireSongAnalysis = Schemas["SongAnalysisOut"];

export const songAnalysisDecoder: Decoder<WireSongAnalysis> = obj({
  source: oneOf(analysisSources),
  title: str,
  artist: withDefault(str, ""),
  bpm: num,
  key: withDefault(str, ""),
  meter: withDefault(str, ""),
  duration: withDefault(str, ""),
  genre: withDefault(str, ""),
  sections: arr(obj({ id: str, label: str, startBar: num, endBar: num, note: withDefault(str, "") })),
  chords: arr(obj({ bar: num, beat: num, chord: str, confidence: num })),
  confidenceByPart: withDefault(record(num), {}),
  summary: withDefault(str, ""),
});

/* ------------------------------------------------------------------ */
/* Материалы                                                           */
/* ------------------------------------------------------------------ */

export type WireArtifactPreview = Schemas["ArtifactPreviewOut"];

export const artifactPreviewDecoder: Decoder<WireArtifactPreview> = obj({
  kind: oneOf(previewKinds),
  title: str,
  lines: withDefault(arr(str), []),
});

export type WireArtifact = Schemas["ArtifactOut"];

export const artifactDecoder: Decoder<WireArtifact> = obj({
  id: str,
  type: oneOf(artifactTypes),
  name: str,
  format: oneOf(artifactFormats),
  description: withDefault(str, ""),
  status: oneOf(artifactStatuses),
  confidence: num,
  audience: oneOf(artifactAudiences),
  isStale: bool,
  preview: nullable(artifactPreviewDecoder),
  updatedAt: nullable(str),
});

export type WireStagePack = Schemas["StagePackOut"];

export const stagePackDecoder: Decoder<WireStagePack> = obj({
  id: str,
  versionId: str,
  artifacts: arr(artifactDecoder),
});

export type WireReviewComment = Schemas["ReviewCommentOut"];

export const reviewCommentDecoder: Decoder<WireReviewComment> = obj({
  id: str,
  issueId: str,
  author: str,
  text: str,
  createdAt: str,
});

export type WireReviewIssue = Schemas["ReviewIssueOut"];

export const reviewIssueDecoder: Decoder<WireReviewIssue> = obj({
  id: str,
  title: str,
  sectionId: str,
  bar: num,
  part: str,
  reason: withDefault(str, ""),
  status: oneOf(reviewStatuses),
  confidence: num,
  comments: withDefault(arr(reviewCommentDecoder), []),
});

export type WireStagePackResponse = Schemas["StagePackResponse"];

export const stagePackResponseDecoder: Decoder<WireStagePackResponse> = obj({
  stagePack: stagePackDecoder,
  analysis: songAnalysisDecoder,
  reviewIssues: withDefault(arr(reviewIssueDecoder), []),
  warnings: withDefault(arr(str), []),
});

export type WireArtifactList = Schemas["ArtifactListResponse"];

export const artifactListDecoder: Decoder<WireArtifactList> = obj({
  items: arr(artifactDecoder),
  total: num,
});

export type WireArtifactDownload = Schemas["ArtifactDownloadOut"];

/*
 * Декодер читал два поля из пяти. Руками написанный тип это скрывал: он
 * объявлял ровно то, что декодер умеет, а сервер отдает больше. Сверка с
 * контрактом вскрыла расхождение.
 */
export const artifactDownloadDecoder: Decoder<WireArtifactDownload> = obj({
  artifactId: str,
  url: str,
  expiresAt: str,
  fileName: str,
  sizeBytes: nullable(num),
});

/* ------------------------------------------------------------------ */
/* Версии                                                              */
/* ------------------------------------------------------------------ */

export type WireArrangementVersion = Schemas["ArrangementVersionOut"];

export const arrangementVersionDecoder: Decoder<WireArrangementVersion> = obj({
  id: str,
  label: str,
  kind: oneOf(versionKinds),
  parentVersionId: nullable(str),
  createdAt: str,
  createdBy: str,
  status: oneOf(versionStatuses),
  changes: withDefault(arr(str), []),
  artifactsSnapshot: nullable(arr(artifactDecoder)),
  isCurrent: withDefault(bool, false),
});

export type WireVersionList = Schemas["VersionListResponse"];

export const versionListDecoder: Decoder<WireVersionList> = obj({
  items: arr(arrangementVersionDecoder),
  currentVersionId: nullable(str),
});

export type WireVersionRollback = Schemas["VersionRollbackResponse"];

export const versionRollbackDecoder: Decoder<WireVersionRollback> = obj({
  version: arrangementVersionDecoder,
  restoredFromVersionId: str,
  restoredArtifacts: withDefault(arr(artifactDecoder), []),
  staleArtifactIds: withDefault(arr(str), []),
});

/* ------------------------------------------------------------------ */
/* Директор                                                            */
/* ------------------------------------------------------------------ */

export type WireDirectorSuggestion = Schemas["DirectorSuggestionOut"];

export const directorSuggestionDecoder: Decoder<WireDirectorSuggestion> = obj({
  id: str,
  title: str,
  description: withDefault(str, ""),
  actionId: oneOf(directorActionIds),
  scenario: oneOf(suggestionScopes),
  impact: oneOf(suggestionImpacts),
});

export type WireDirectorSuggestionList = Schemas["DirectorSuggestionListResponse"];

export const directorSuggestionListDecoder: Decoder<WireDirectorSuggestionList> = obj({
  items: arr(directorSuggestionDecoder),
});

export type WireDirectorActionResult = Schemas["DirectorActionResultOut"];

export const directorActionResultDecoder: Decoder<WireDirectorActionResult> = obj({
  versionLabel: str,
  versionKind: oneOf(versionKinds),
  historyTitle: str,
  changes: withDefault(arr(str), []),
  staleArtifactTypes: withDefault(arr(oneOf(artifactTypes)), []),
});

export type WireDirectorActionResponse = Schemas["DirectorActionResponse"];

export const directorActionResponseDecoder: Decoder<WireDirectorActionResponse> = obj({
  version: arrangementVersionDecoder,
  result: directorActionResultDecoder,
  appliedActionIds: withDefault(arr(oneOf(directorActionIds)), []),
});

export type WireChatMessage = Schemas["ChatMessageOut"];

export const chatMessageDecoder: Decoder<WireChatMessage> = obj({
  id: str,
  author: oneOf(chatAuthors),
  text: str,
  createdAt: str,
});

export type WireDirectorChatResponse = Schemas["DirectorChatResponse"];

export const directorChatResponseDecoder: Decoder<WireDirectorChatResponse> = obj({
  message: chatMessageDecoder,
  reply: chatMessageDecoder,
  suggestedActionId: nullable(oneOf(directorActionIds)),
});

/* ------------------------------------------------------------------ */
/* Выдача                                                              */
/* ------------------------------------------------------------------ */

export type WireShareRecipient = Schemas["ShareRecipientOut"];

export const shareRecipientDecoder: Decoder<WireShareRecipient> = obj({
  id: str,
  name: str,
  role: oneOf(recipientRoles),
  material: withDefault(str, ""),
  status: oneOf(recipientStatuses),
});

export type WireShareLink = Schemas["ShareLinkOut"];

export const shareLinkDecoder: Decoder<WireShareLink> = obj({
  id: str,
  recipientId: str,
  label: str,
  url: str,
  status: oneOf(shareLinkStatuses),
  artifactIds: withDefault(arr(str), []),
  createdAt: str,
  expiresAt: nullable(str),
  revokedAt: nullable(str),
  openedAt: nullable(str),
});

export type WireExportBundle = Schemas["ExportBundleOut"];

export const exportBundleDecoder: Decoder<WireExportBundle> = obj({
  id: str,
  label: str,
  filesCount: num,
  status: oneOf(exportBundleStatuses),
  versionId: str,
  createdAt: str,
  isStale: withDefault(bool, false),
});

export const listOf = <T>(inner: Decoder<T>): Decoder<{ items: T[]; total: number }> =>
  obj({ items: arr(inner), total: withDefault(num, 0) });

/* ------------------------------------------------------------------ */
/* Люди                                                                */
/* ------------------------------------------------------------------ */

export type WireMusician = Schemas["MusicianOut"];

export const musicianDecoder: Decoder<WireMusician> = obj({
  id: str,
  name: str,
  role: oneOf(musicianRoles),
  instrumentNote: withDefault(str, ""),
  constraint: withDefault(str, ""),
  level: oneOf(musicianLevels),
});

export type WireBandLineup = Schemas["BandLineupOut"];

export const bandLineupDecoder: Decoder<WireBandLineup> = obj({
  leadVocal: bool,
  vocalRange: withDefault(str, ""),
  guitars: num,
  guitarTuning: withDefault(str, ""),
  capo: withDefault(str, ""),
  bass: oneOf(bassStrings),
  keys: bool,
  keysCanCoverLayers: bool,
  drums: bool,
  backingVocals: bool,
  musicianLevel: oneOf(musicianLevels),
  targetStyle: withDefault(str, ""),
});

export type WireStudentProfile = Schemas["StudentProfileOut"];

export const studentProfileDecoder: Decoder<WireStudentProfile> = obj({
  name: str,
  instrument: str,
  level: oneOf(studentLevels),
  ageGroup: withDefault(str, ""),
  notationReading: oneOf(notationReadings),
  chordKnowledge: withDefault(str, ""),
  homeInstrument: withDefault(str, ""),
});

export type WireTeacherProfile = Schemas["TeacherProfileOut"];

export const teacherProfileDecoder: Decoder<WireTeacherProfile> = obj({
  name: str,
  format: oneOf(teacherFormats),
  focus: withDefault(str, ""),
});

export type WireClassGroup = Schemas["ClassGroupOut"];

export const classGroupDecoder: Decoder<WireClassGroup> = obj({
  name: str,
  studentsCount: num,
  instruments: withDefault(arr(str), []),
});

export type WireLesson = Schemas["LessonOut"];

export const lessonDecoder: Decoder<WireLesson> = obj({
  goal: withDefault(str, ""),
  homeworkFormat: withDefault(str, ""),
  desiredDifficulty: oneOf(lessonDifficulties),
});

export type WireAssignment = Schemas["AssignmentOut"];

export const assignmentDecoder: Decoder<WireAssignment> = obj({
  id: str,
  title: str,
  recipient: str,
  status: oneOf(assignmentStatuses),
});

/* ------------------------------------------------------------------ */
/* Проект                                                              */
/* ------------------------------------------------------------------ */

export type WireCostEstimate = Schemas["CostEstimateOut"];

export const costEstimateDecoder: Decoder<WireCostEstimate> = obj({
  tier: oneOf(costTiers),
  complexity: oneOf(costComplexities),
  credits: num,
  notes: withDefault(arr(str), []),
});

export type WireSetupSnapshot = Schemas["SetupSnapshot"];

export const setupSnapshotDecoder: Decoder<WireSetupSnapshot> = obj({
  scenario: oneOf(scenarios),
  title: str,
  fields: withDefault(arr(obj({ label: str, value: str })), []),
});

export type WireLegalConsent = Schemas["LegalConsentOut"];

export const legalConsentDecoder: Decoder<WireLegalConsent> = obj({
  accepted: bool,
  versionId: str,
  text: str,
  acceptedAt: nullable(str),
});

export type WireDataRetentionState = Schemas["DataRetentionStateOut"];

export const dataRetentionStateDecoder: Decoder<WireDataRetentionState> = obj({
  sourceDeleted: bool,
  resultsDeleted: bool,
  sourceState: oneOf(deletionStates),
  resultsState: oneOf(deletionStates),
  retentionNote: withDefault(str, ""),
});

export type WireChangeLogEntry = Schemas["ChangeLogEntryOut"];

export const changeLogEntryDecoder: Decoder<WireChangeLogEntry> = obj({
  id: str,
  title: str,
  description: withDefault(str, ""),
  createdAt: str,
  actor: str,
});

export type WireProject = Schemas["ProjectOut"];

export const projectDecoder: Decoder<WireProject> = obj({
  id: str,
  name: str,
  scenario: oneOf(scenarios),
  processingGoal: processingGoalDecoder,
  upload: uploadDecoder,
  bandLineup: nullable(bandLineupDecoder),
  musicians: withDefault(arr(musicianDecoder), []),
  studentProfile: nullable(studentProfileDecoder),
  teacherProfile: nullable(teacherProfileDecoder),
  classGroup: nullable(classGroupDecoder),
  lesson: nullable(lessonDecoder),
  assignments: withDefault(arr(assignmentDecoder), []),
  versions: withDefault(arr(arrangementVersionDecoder), []),
  currentVersionId: nullable(str),
  processing: processingJobDecoder,
  analysis: songAnalysisDecoder,
  stagePack: stagePackDecoder,
  reviewIssues: withDefault(arr(reviewIssueDecoder), []),
  reviewComments: withDefault(arr(reviewCommentDecoder), []),
  directorSuggestions: withDefault(arr(directorSuggestionDecoder), []),
  chat: withDefault(arr(chatMessageDecoder), []),
  changeLog: withDefault(arr(changeLogEntryDecoder), []),
  shareRecipients: withDefault(arr(shareRecipientDecoder), []),
  shareLinks: withDefault(arr(shareLinkDecoder), []),
  exportBundles: withDefault(arr(exportBundleDecoder), []),
  costEstimate: costEstimateDecoder,
  setupSnapshot: setupSnapshotDecoder,
  legalConsent: legalConsentDecoder,
  dataRetention: dataRetentionStateDecoder,
  createdAt: str,
  updatedAt: str,
  lastOpenedAt: str,
});

export type WireProjectSummary = Schemas["ProjectSummary"];

export const projectSummaryDecoder: Decoder<WireProjectSummary> = obj({
  id: str,
  name: str,
  scenario: oneOf(scenarios),
  goalId: oneOf(goalIds),
  fileName: str,
  jobStatus: nullable(processingJobDecoder),
  sourceDeleted: bool,
  resultsDeleted: bool,
  createdAt: str,
  lastOpenedAt: str,
});

export type WireProjectList = Schemas["ProjectListResponse"];

export const projectListDecoder: Decoder<WireProjectList> = obj({
  items: arr(projectSummaryDecoder),
  total: num,
  limit: num,
  offset: num,
});

/* ------------------------------------------------------------------ */
/* Удаление                                                            */
/* ------------------------------------------------------------------ */

export type WireDeletionTargetStatus = Schemas["DeletionTargetStatus"];

export const deletionTargetStatusDecoder: Decoder<WireDeletionTargetStatus> = obj({
  state: oneOf(deletionStates),
  requestedAt: nullable(str),
  completedAt: nullable(str),
  error: nullable(str),
});

export type WireDeletionStatus = Schemas["DeletionStatusOut"];

export const deletionStatusDecoder: Decoder<WireDeletionStatus> = obj({
  projectId: str,
  source: deletionTargetStatusDecoder,
  results: deletionTargetStatusDecoder,
  retentionNote: withDefault(str, ""),
});

export type WireDeletionAccepted = Schemas["DeletionAcceptedOut"];

export const deletionAcceptedDecoder: Decoder<WireDeletionAccepted> = obj({
  projectId: str,
  state: oneOf(deletionStates),
  requestedAt: str,
  statusUrl: str,
  revokedLinksCount: nullable(num),
});

/* ------------------------------------------------------------------ */
/* Тела запросов                                                       */
/* ------------------------------------------------------------------ */

export type WireBandSetup = Schemas["BandSetup"];

export type WireLessonSetup = Schemas["LessonSetup"];

export type WireProjectSetup = WireBandSetup | WireLessonSetup;

export interface ProjectCreateRequest {
  uploadId: string;
  name?: string | null;
  scenario: Scenario;
  goalId: ProcessingGoalId;
  setup: WireProjectSetup;
  setupSnapshot?: WireSetupSnapshot | null;
  consent: { accepted: boolean; versionId: string };
}

export interface DeletionRequest {
  confirm: boolean;
  reason?: string | null;
}

export const unknownDecoder: Decoder<unknown> = anything;
