export type Scenario = "band" | "education";

export type ProcessingGoalId =
  | "band-analysis"
  | "band-rehearsal"
  | "band-performance"
  | "band-minus"
  | "band-parts"
  | "band-transpose"
  | "band-adapt-lineup"
  | "band-boost"
  | "lesson-analysis"
  | "lesson-easy"
  | "lesson-original"
  | "lesson-advanced"
  | "lesson-concert"
  | "lesson-ensemble"
  | "lesson-homework"
  | "lesson-practice-tracks";

export interface ProcessingGoal {
  id: ProcessingGoalId;
  scenario: Scenario;
  label: string;
  description: string;
  expectedOutputs: string[];
}

export interface Upload {
  id: string;
  fileName: string;
  format: "MP3" | "WAV" | "FLAC" | "M4A" | "DEMO";
  durationSeconds: number;
  quality: "good" | "medium" | "low";
  sourceNote: string;
  /** Факты из декодированного аудио. У демо отсутствуют: файла нет. */
  sizeBytes?: number;
  sampleRate?: number;
  channels?: number;
}

/**
 * Человек в составе. Заведён отдельной сущностью, потому что ограничения
 * принадлежат людям, а не группе: диапазон — вокалиста, число струн —
 * басиста, уровень — каждого свой. В плоском `BandLineup` этого не выразить,
 * и директор предлагал транспонирование, не зная, чей это диапазон.
 */
export interface Musician {
  id: string;
  name: string;
  role: "вокал" | "гитара" | "бас" | "клавиши" | "барабаны" | "бэк-вокал";
  /** Чем играет: «5 струн · E1», «2 слоя · Nord Stage». */
  instrumentNote: string;
  /** Что ограничивает: диапазон, строй, каподастр. Данные, а не примечание. */
  constraint: string;
  level: "начинающий" | "средний" | "продвинутый";
}

export interface BandLineup {
  leadVocal: boolean;
  vocalRange: string;
  guitars: number;
  guitarTuning: string;
  capo: string;
  bass: "4 strings" | "5 strings";
  keys: boolean;
  keysCanCoverLayers: boolean;
  drums: boolean;
  backingVocals: boolean;
  musicianLevel: "beginner" | "middle" | "advanced";
  targetStyle: string;
}

export interface StudentProfile {
  name: string;
  instrument: string;
  level: "начальный" | "средний" | "сильный";
  ageGroup: string;
  notationReading: "не читает" | "простые ноты" | "уверенно";
  chordKnowledge: string;
  homeInstrument: string;
}

export interface TeacherProfile {
  name: string;
  format: "индивидуальный урок" | "группа" | "школьный ансамбль";
  focus: string;
}

export interface ClassGroup {
  name: string;
  studentsCount: number;
  instruments: string[];
}

export interface Lesson {
  goal: string;
  homeworkFormat: string;
  desiredDifficulty: "проще оригинала" | "близко к оригиналу" | "сложнее оригинала";
}

export interface Assignment {
  id: string;
  title: string;
  recipient: string;
  status: "assigned" | "in_progress" | "analyzed" | "ready_for_concert";
}

export type VersionKind =
  | "original"
  | "band"
  | "easy"
  | "original-like"
  | "advanced"
  | "concert"
  | "ensemble"
  | "after-rehearsal"
  | "after-lesson";

export interface ArrangementVersion {
  id: string;
  label: string;
  kind: VersionKind;
  parentVersionId?: string;
  createdAt: string;
  createdBy: string;
  status: "draft" | "needs_review" | "approved" | "distributed";
  changes: string[];
  /** Состояние материалов на момент выхода из версии. Позволяет откатиться назад. */
  artifactsSnapshot?: Artifact[];
}

/**
 * `skipped` — шаг не выполняется на этом пути, и результата у него не будет.
 * Отдельный статус нужен, чтобы не выдавать несделанное за «готово»: на пути
 * загрузки звук не обрабатывается вовсе.
 */
export type ProcessingStepStatus = "queued" | "running" | "done" | "warning" | "error" | "skipped";

export interface ProcessingStep {
  id: string;
  label: string;
  status: ProcessingStepStatus;
  detail: string;
}

export interface ProcessingJob {
  id: string;
  status: "queued" | "running" | "ready" | "warning" | "error";
  steps: ProcessingStep[];
  warnings: string[];
  progressPercent: number;
}

export interface SongSection {
  id: string;
  label: string;
  startBar: number;
  endBar: number;
  note: string;
}

export interface ChordEvent {
  bar: number;
  beat: number;
  chord: string;
  confidence: number;
}

export interface SongAnalysis {
  /**
   * Откуда взят разбор. `demo` — данные подготовлены заранее; `none` — разбора
   * нет, потому что звук не анализируется. Промежуточного состояния нет:
   * подставлять чужой разбор к своему файлу нельзя.
   */
  source: "demo" | "none";
  title: string;
  artist: string;
  bpm: number;
  key: string;
  meter: string;
  duration: string;
  genre: string;
  sections: SongSection[];
  chords: ChordEvent[];
  confidenceByPart: Record<string, number>;
  summary: string;
}

export type ArtifactType =
  | "score"
  | "part"
  | "tab"
  | "chords"
  | "lyrics"
  | "midi"
  | "stem"
  | "minus"
  | "click"
  | "practice"
  | "teacher"
  | "student"
  | "zip";

export type ArtifactStatus = "ready" | "draft" | "needs_review" | "rebuild_required" | "pending";

export interface ArtifactPreview {
  kind: "notation" | "waveform" | "midi" | "bundle" | "text";
  title: string;
  lines: string[];
}

export interface Artifact {
  id: string;
  type: ArtifactType;
  name: string;
  format: "PDF" | "MIDI" | "WAV" | "ZIP" | "MusicXML" | "VIEW";
  description: string;
  status: ArtifactStatus;
  confidence: number;
  audience: "all" | "band" | "teacher" | "student" | "instrument";
  isStale: boolean;
  preview: ArtifactPreview;
}

export interface StagePack {
  id: string;
  versionId: string;
  artifacts: Artifact[];
}

export type ReviewStatus =
  | "needs_review"
  | "checked"
  | "fixed"
  | "uncertain"
  | "accepted_for_rehearsal";

export interface ReviewIssue {
  id: string;
  title: string;
  sectionId: string;
  bar: number;
  part: string;
  reason: string;
  status: ReviewStatus;
  confidence: number;
}

export interface ReviewComment {
  id: string;
  issueId: string;
  author: string;
  text: string;
  createdAt: string;
}

export interface DirectorSuggestion {
  id: string;
  title: string;
  description: string;
  actionId: DirectorActionId;
  scenario: Scenario | "both";
  impact: "arrangement" | "education" | "export" | "review";
}

export type DirectorActionId =
  | "transpose-down-2"
  | "merge-guitars"
  | "move-strings-to-keys"
  | "simplify-drums"
  | "beginner-bass"
  | "boost-chorus"
  | "practice-without-bass"
  | "education-version"
  | "advanced-student-part"
  | "student-ensemble"
  | "lesson-analysis";

export interface DirectorActionResult {
  versionLabel: string;
  versionKind: VersionKind;
  historyTitle: string;
  changes: string[];
  staleArtifactTypes: ArtifactType[];
}

export interface ChatMessage {
  id: string;
  author: "user" | "director";
  text: string;
  createdAt: string;
}

export interface ChangeLogEntry {
  id: string;
  title: string;
  description: string;
  createdAt: string;
  actor: string;
}

export interface ShareRecipient {
  id: string;
  name: string;
  role: "vocalist" | "guitarist" | "bassist" | "keys" | "drummer" | "teacher" | "student" | "parent";
  material: string;
  status: "not_issued" | "issued" | "opened" | "needs_fix";
}

export interface ShareLink {
  id: string;
  recipientId: string;
  label: string;
  url: string;
  status: "mock_created" | "stale";
}

export interface ExportBundle {
  id: string;
  label: string;
  filesCount: number;
  status: "ready" | "stale" | "pending";
}

export interface CostEstimate {
  tier: "fast_draft" | "accurate" | "multi_version";
  complexity: "low" | "medium" | "high";
  credits: number;
  notes: string[];
  /**
   * Ожидаемого времени здесь намеренно нет: обработки не существует, а любое
   * число рядом со словом «минут» читается как обещание срока и нарушает
   * поправку спеки от 2026-09-09. Вернуть вместе с настоящим ModelRouter.
   */
}

/**
 * Настройка, введённая пользователем на экране уточнений.
 *
 * Отдельный тип, а не `Record<string, string>` с подписями: раньше сервис
 * искал значения по русским подписям («Диапазон вокала»), и переименование
 * подписи копирайтером молча заменяло настройку пользователя умолчанием.
 * Ошибка тихая — ни исключения, ни пустого поля, просто чужое значение.
 *
 * `SetupSnapshot` остаётся, но только для показа: это то, что пользователь
 * видит в сводке, а не то, из чего считается аранжировка.
 */
export interface BandSetup {
  kind: "band";
  vocalRange: string;
  guitars: number;
  bass: string;
  keys: string;
  drums: string;
  targetStyle: string;
}

export interface LessonSetup {
  kind: "lesson";
  instrument: string;
  level: string;
  lessonGoal: string;
  difficulty: string;
}

export type ProjectSetup = BandSetup | LessonSetup;

export interface SetupSnapshot {
  scenario: Scenario;
  title: string;
  fields: Array<{
    label: string;
    value: string;
  }>;
}

export interface LegalConsent {
  accepted: boolean;
  /**
   * Версия формулировки, которую человек принял. Без неё запись «согласие
   * получено» остаётся без предмета: текст на экране меняется, а по чему
   * читать старое согласие — неизвестно. Задним числом не восстанавливается.
   */
  versionId: string;
  /** Точный текст на момент принятия. Дублирует версию намеренно: запись
   *  должна читаться, даже если модуль версий когда-нибудь потеряют. */
  text: string;
  acceptedAt?: string;
}

export interface DataRetentionState {
  sourceDeleted: boolean;
  resultsDeleted: boolean;
  retentionNote: string;
}

export interface Project {
  id: string;
  name: string;
  scenario: Scenario;
  processingGoal: ProcessingGoal;
  upload: Upload;
  bandLineup?: BandLineup;
  /** Кто играет. Пусто в сценарии урока и у проектов без состава. */
  musicians: Musician[];
  studentProfile?: StudentProfile;
  teacherProfile?: TeacherProfile;
  classGroup?: ClassGroup;
  lesson?: Lesson;
  assignments: Assignment[];
  versions: ArrangementVersion[];
  currentVersionId: string;
  processing: ProcessingJob;
  analysis: SongAnalysis;
  stagePack: StagePack;
  reviewIssues: ReviewIssue[];
  reviewComments: ReviewComment[];
  directorSuggestions: DirectorSuggestion[];
  chat: ChatMessage[];
  changeLog: ChangeLogEntry[];
  shareRecipients: ShareRecipient[];
  shareLinks: ShareLink[];
  exportBundles: ExportBundle[];
  costEstimate: CostEstimate;
  setupSnapshot: SetupSnapshot;
  legalConsent: LegalConsent;
  dataRetention: DataRetentionState;
}

export interface UploadProjectInput {
  scenario: Scenario;
  goalId: ProcessingGoalId;
  fileName: string;
  acceptedConsent: boolean;
  /** Показывается пользователю в сводке. Из него ничего не вычисляется. */
  setupSnapshot?: SetupSnapshot;
  /** Введённые значения. Именно из них строится аранжировка. */
  setup?: ProjectSetup;
  /** Факты из декодированного файла. Отсутствуют, если декодирование не удалось. */
  facts?: {
    durationSeconds: number;
    sampleRate: number;
    channels: number;
    sizeBytes: number;
    quality: Upload["quality"];
  };
}
