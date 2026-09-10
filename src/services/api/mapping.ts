/**
 * Перевод формы провода в доменную модель фронтенда.
 *
 * Расхождение осознанное и описано на стороне сервера
 * (`server/app/api/schemas/enums.py`): в контракте — устойчивые латинские
 * ключи, в `src/domain/types.ts` на этих местах стоят русские подписи. Пока
 * домен фронтенда не переехал на ключи, перевод живет здесь: **таблицей**,
 * которую видно, а не разбором строк по вхождению подстроки.
 *
 * Это развилка владельца, а не вкусовщина: либо таблица остается тут навсегда,
 * либо `types.ts` переходит на ключи и подписи уезжают в слой представления.
 * Пока выбрано первое — как меньшее вмешательство в чужие файлы.
 *
 * Правило перевода одно: **ничего не выдумывать**. Там, где домен не умеет
 * выразить ответ сервера (состояние загрузки, состояние удаления, статус
 * ссылки), поле не подменяется похожим — оно уезжает в `ProjectExtras`
 * рядом с проектом.
 */
import type {
  ArrangementVersion,
  Artifact,
  Assignment,
  BandLineup,
  ChangeLogEntry,
  ChatMessage,
  ClassGroup,
  CostEstimate,
  DirectorSuggestion,
  ExportBundle,
  LegalConsent,
  Lesson,
  Musician,
  ProcessingJob,
  Project,
  ReviewComment,
  ReviewIssue,
  ShareRecipient,
  SongAnalysis,
  StagePack,
  StudentProfile,
  TeacherProfile,
  Upload,
} from "../../domain/types";
import type {
  WireArrangementVersion,
  WireArtifact,
  WireAssignment,
  WireBandLineup,
  WireBassStrings,
  WireChangeLogEntry,
  WireChatMessage,
  WireClassGroup,
  WireCostEstimate,
  WireDirectorSuggestion,
  WireExportBundle,
  WireLegalConsent,
  WireLesson,
  WireLessonDifficulty,
  WireMusician,
  WireMusicianLevel,
  WireMusicianRole,
  WireNotationReading,
  WireProcessingJob,
  WireProject,
  WireReviewComment,
  WireReviewIssue,
  WireShareRecipient,
  WireSongAnalysis,
  WireStagePack,
  WireStudentLevel,
  WireStudentProfile,
  WireTeacherFormat,
  WireTeacherProfile,
  WireUpload,
} from "./contract";

/* ------------------------------------------------------------------ */
/* Таблицы перевода                                                    */
/* ------------------------------------------------------------------ */

export const musicianRoleLabels: Record<WireMusicianRole, Musician["role"]> = {
  vocal: "вокал",
  guitar: "гитара",
  bass: "бас",
  keys: "клавиши",
  drums: "барабаны",
  backing_vocal: "бэк-вокал",
};

export const musicianLevelLabels: Record<WireMusicianLevel, Musician["level"]> = {
  beginner: "начинающий",
  middle: "средний",
  advanced: "продвинутый",
};

export const bassStringsLabels: Record<WireBassStrings, BandLineup["bass"]> = {
  "4_strings": "4 strings",
  "5_strings": "5 strings",
};

export const studentLevelLabels: Record<WireStudentLevel, StudentProfile["level"]> = {
  starter: "начальный",
  middle: "средний",
  strong: "сильный",
};

export const notationReadingLabels: Record<WireNotationReading, StudentProfile["notationReading"]> = {
  none: "не читает",
  simple: "простые ноты",
  confident: "уверенно",
};

export const teacherFormatLabels: Record<WireTeacherFormat, TeacherProfile["format"]> = {
  individual: "индивидуальный урок",
  group: "группа",
  school_ensemble: "школьный ансамбль",
};

export const lessonDifficultyLabels: Record<WireLessonDifficulty, Lesson["desiredDifficulty"]> = {
  easier: "проще оригинала",
  original_like: "близко к оригиналу",
  harder: "сложнее оригинала",
};

/* ------------------------------------------------------------------ */
/* Перевод сущностей                                                   */
/* ------------------------------------------------------------------ */

export const toDomainMusician = (wire: WireMusician): Musician => ({
  id: wire.id,
  name: wire.name,
  role: musicianRoleLabels[wire.role],
  instrumentNote: wire.instrumentNote,
  constraint: wire.constraint,
  level: musicianLevelLabels[wire.level],
});

export const toDomainBandLineup = (wire: WireBandLineup): BandLineup => ({
  leadVocal: wire.leadVocal,
  vocalRange: wire.vocalRange,
  guitars: wire.guitars,
  guitarTuning: wire.guitarTuning,
  capo: wire.capo,
  bass: bassStringsLabels[wire.bass],
  keys: wire.keys,
  keysCanCoverLayers: wire.keysCanCoverLayers,
  drums: wire.drums,
  backingVocals: wire.backingVocals,
  musicianLevel: wire.musicianLevel,
  targetStyle: wire.targetStyle,
});

export const toDomainStudentProfile = (wire: WireStudentProfile): StudentProfile => ({
  name: wire.name,
  instrument: wire.instrument,
  level: studentLevelLabels[wire.level],
  ageGroup: wire.ageGroup,
  notationReading: notationReadingLabels[wire.notationReading],
  chordKnowledge: wire.chordKnowledge,
  homeInstrument: wire.homeInstrument,
});

export const toDomainTeacherProfile = (wire: WireTeacherProfile): TeacherProfile => ({
  name: wire.name,
  format: teacherFormatLabels[wire.format],
  focus: wire.focus,
});

export const toDomainClassGroup = (wire: WireClassGroup): ClassGroup => ({
  name: wire.name,
  studentsCount: wire.studentsCount,
  instruments: wire.instruments,
});

export const toDomainLesson = (wire: WireLesson): Lesson => ({
  goal: wire.goal,
  homeworkFormat: wire.homeworkFormat,
  desiredDifficulty: lessonDifficultyLabels[wire.desiredDifficulty],
});

export const toDomainAssignment = (wire: WireAssignment): Assignment => ({
  id: wire.id,
  title: wire.title,
  recipient: wire.recipient,
  status: wire.status,
});

/**
 * Предпросмотра может не быть. Пустой список строк — это честное «показывать
 * нечего»; выдумать сюда текст значило бы нарисовать содержимое, которого нет.
 */
export const toDomainArtifact = (wire: WireArtifact): Artifact => ({
  id: wire.id,
  type: wire.type,
  name: wire.name,
  format: wire.format,
  description: wire.description,
  status: wire.status,
  confidence: wire.confidence,
  audience: wire.audience,
  isStale: wire.isStale,
  preview: wire.preview ?? { kind: "text", title: wire.name, lines: [] },
});

export const toDomainVersion = (wire: WireArrangementVersion): ArrangementVersion => ({
  id: wire.id,
  label: wire.label,
  kind: wire.kind,
  parentVersionId: wire.parentVersionId ?? undefined,
  createdAt: wire.createdAt,
  createdBy: wire.createdBy,
  status: wire.status,
  changes: wire.changes,
  artifactsSnapshot: wire.artifactsSnapshot
    ? wire.artifactsSnapshot.map(toDomainArtifact)
    : undefined,
});

export const toDomainStagePack = (wire: WireStagePack): StagePack => ({
  id: wire.id,
  versionId: wire.versionId,
  artifacts: wire.artifacts.map(toDomainArtifact),
});

export const toDomainReviewIssue = (wire: WireReviewIssue): ReviewIssue => ({
  id: wire.id,
  title: wire.title,
  sectionId: wire.sectionId,
  bar: wire.bar,
  part: wire.part,
  reason: wire.reason,
  status: wire.status,
  confidence: wire.confidence,
});

export const toDomainReviewComment = (wire: WireReviewComment): ReviewComment => ({
  id: wire.id,
  issueId: wire.issueId,
  author: wire.author,
  text: wire.text,
  createdAt: wire.createdAt,
});

export const toDomainChatMessage = (wire: WireChatMessage): ChatMessage => ({
  id: wire.id,
  author: wire.author,
  text: wire.text,
  createdAt: wire.createdAt,
});

export const toDomainChangeLogEntry = (wire: WireChangeLogEntry): ChangeLogEntry => ({
  id: wire.id,
  title: wire.title,
  description: wire.description,
  createdAt: wire.createdAt,
  actor: wire.actor,
});

export const toDomainSuggestion = (wire: WireDirectorSuggestion): DirectorSuggestion => ({
  id: wire.id,
  title: wire.title,
  description: wire.description,
  actionId: wire.actionId,
  scenario: wire.scenario,
  impact: wire.impact,
});

export const toDomainRecipient = (wire: WireShareRecipient): ShareRecipient => ({
  id: wire.id,
  name: wire.name,
  role: wire.role,
  material: wire.material,
  status: wire.status,
});

/**
 * Устаревший архив показывается устаревшим, даже если сервер оставил статус
 * `ready`: в домене на это есть отдельное значение, и терять признак нельзя —
 * иначе музыкант унесет на репетицию несобранный заново пакет.
 */
export const toDomainExportBundle = (wire: WireExportBundle): ExportBundle => ({
  id: wire.id,
  label: wire.label,
  filesCount: wire.filesCount,
  status: wire.isStale && wire.status === "ready" ? "stale" : wire.status,
});

export const toDomainAnalysis = (wire: WireSongAnalysis): SongAnalysis => ({
  source: wire.source,
  title: wire.title,
  artist: wire.artist,
  bpm: wire.bpm,
  key: wire.key,
  meter: wire.meter,
  duration: wire.duration,
  genre: wire.genre,
  sections: wire.sections,
  chords: wire.chords,
  confidenceByPart: wire.confidenceByPart,
  summary: wire.summary,
});

export const toDomainJob = (wire: WireProcessingJob): ProcessingJob => ({
  id: wire.id,
  status: wire.status,
  steps: wire.steps,
  warnings: wire.warnings,
  progressPercent: wire.progressPercent,
});

export const toDomainUpload = (wire: WireUpload): Upload => ({
  id: wire.id,
  fileName: wire.fileName,
  format: wire.format,
  durationSeconds: wire.durationSeconds,
  quality: wire.quality,
  sourceNote: wire.sourceNote,
  sizeBytes: wire.sizeBytes ?? undefined,
  sampleRate: wire.sampleRate ?? undefined,
  channels: wire.channels ?? undefined,
});

export const toDomainCostEstimate = (wire: WireCostEstimate): CostEstimate => ({
  tier: wire.tier,
  complexity: wire.complexity,
  credits: wire.credits,
  notes: wire.notes,
});

export const toDomainConsent = (wire: WireLegalConsent): LegalConsent => ({
  accepted: wire.accepted,
  versionId: wire.versionId,
  text: wire.text,
  acceptedAt: wire.acceptedAt ?? undefined,
});

/**
 * То, что доменная модель фронтенда пока не умеет выразить.
 *
 * `null` означает «источник этого не знает» — так отвечают моки. Ноль, пустая
 * строка или выдуманное состояние здесь были бы враньем: разница между
 * «удаление выполняется» и «удалено» — ровно то, ради чего документ о
 * гарантиях удаления написан.
 */
export interface ProjectExtras {
  uploadState: WireUpload["state"] | null;
  sourceState: WireProject["dataRetention"]["sourceState"] | null;
  resultsState: WireProject["dataRetention"]["resultsState"] | null;
  shareLinks: WireProject["shareLinks"] | null;
  createdAt: string | null;
  updatedAt: string | null;
  jobErrorCode: string | null;
}

export const emptyExtras: ProjectExtras = {
  uploadState: null,
  sourceState: null,
  resultsState: null,
  shareLinks: null,
  createdAt: null,
  updatedAt: null,
  jobErrorCode: null,
};

export interface ProjectView {
  project: Project;
  extras: ProjectExtras;
}

/**
 * Полный перевод карточки проекта.
 *
 * Ссылки выдачи в домен не переводятся: доменный `ShareLink.status` знает
 * только `mock_created` и `stale`, а сервер различает действующую, устаревшую,
 * **отозванную** и истекшую. Подставить сюда `mock_created` значило бы
 * показать отозванную ссылку рабочей — ровно то, что запрещает
 * `docs/DELETION_AND_RETENTION_DESIGN.md`. Поэтому ссылки уходят в `extras`
 * как есть, а домен ждет правки.
 */
export const toProjectView = (wire: WireProject): ProjectView => ({
  project: {
    id: wire.id,
    name: wire.name,
    scenario: wire.scenario,
    processingGoal: wire.processingGoal,
    upload: toDomainUpload(wire.upload),
    bandLineup: wire.bandLineup ? toDomainBandLineup(wire.bandLineup) : undefined,
    musicians: wire.musicians.map(toDomainMusician),
    studentProfile: wire.studentProfile ? toDomainStudentProfile(wire.studentProfile) : undefined,
    teacherProfile: wire.teacherProfile ? toDomainTeacherProfile(wire.teacherProfile) : undefined,
    classGroup: wire.classGroup ? toDomainClassGroup(wire.classGroup) : undefined,
    lesson: wire.lesson ? toDomainLesson(wire.lesson) : undefined,
    assignments: wire.assignments.map(toDomainAssignment),
    versions: wire.versions.map(toDomainVersion),
    currentVersionId: wire.currentVersionId ?? "",
    processing: toDomainJob(wire.processing),
    analysis: toDomainAnalysis(wire.analysis),
    stagePack: toDomainStagePack(wire.stagePack),
    reviewIssues: wire.reviewIssues.map(toDomainReviewIssue),
    reviewComments: [
      ...wire.reviewComments.map(toDomainReviewComment),
      // Комментарии приходят и вложенными в место проверки: сервер отдает их
      // рядом с местом, домен держит плоским списком.
      // Поле необязательно в контракте: сервер может не прислать вложенные
      // комментарии вовсе. Руками написанный тип объявлял его обязательным.
      ...wire.reviewIssues.flatMap((issue) => (issue.comments ?? []).map(toDomainReviewComment)),
    ],
    directorSuggestions: wire.directorSuggestions.map(toDomainSuggestion),
    chat: wire.chat.map(toDomainChatMessage),
    changeLog: wire.changeLog.map(toDomainChangeLogEntry),
    shareRecipients: wire.shareRecipients.map(toDomainRecipient),
    shareLinks: [],
    exportBundles: wire.exportBundles.map(toDomainExportBundle),
    costEstimate: toDomainCostEstimate(wire.costEstimate),
    setupSnapshot: wire.setupSnapshot,
    legalConsent: toDomainConsent(wire.legalConsent),
    dataRetention: {
      sourceDeleted: wire.dataRetention.sourceDeleted,
      resultsDeleted: wire.dataRetention.resultsDeleted,
      retentionNote: wire.dataRetention.retentionNote,
    },
  },
  extras: {
    uploadState: wire.upload.state,
    sourceState: wire.dataRetention.sourceState,
    resultsState: wire.dataRetention.resultsState,
    shareLinks: wire.shareLinks,
    createdAt: wire.createdAt,
    updatedAt: wire.updatedAt,
    jobErrorCode: wire.processing.errorCode ?? null,
  },
});
