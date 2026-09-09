import { type Dispatch, type ReactNode, type SetStateAction, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileAudio,
  FolderOpen,
  Gauge,
  Layers3,
  MinusCircle,
  ListChecks,
  Play,
  Repeat2,
  X,
  XCircle,
  SlidersHorizontal,
  Sparkles,
  Share2,
} from "lucide-react";
import { lessonLevels, processingGoals, processingMilestones } from "./domain/mockData";
import {
  listStoredProjects,
  loadProject,
  removeStoredProject,
  saveProject,
  type StoredProject,
} from "./services/projectStorage";
import type {
  ArrangementVersion,
  CostEstimate,
  DirectorActionId,
  ProcessingGoalId,
  ProcessingStep,
  Project,
  ReviewStatus,
  Scenario,
} from "./domain/types";
import { type AudioFacts, browserDecoder, formatDuration, readAudioFacts } from "./services/audioFile";
import {
  addReviewComment,
  addSessionNote,
  addUnderstoodNothingReply,
  applyDirectorAction,
  applyDirectorActions,
  createProjectFromDemo,
  createProjectFromUpload,
  createShareLinks,
  deleteProjectResults,
  deleteProjectSource,
  getGoalsForScenario,
  listDemoProjects,
  rebuildExportBundle,
  rollbackToVersion,
  updateReviewIssue,
  validateUploadFile,
} from "./services/mockServices";

type Screen = "start" | "setup" | "processing" | "stage-pack" | "songs";
type WorkspaceTab = "overview" | "materials" | "lineup" | "review" | "director" | "export";

const homeJobOptions: Array<{
  goalId: ProcessingGoalId;
  scenario: Scenario;
  title: string;
  detail: string;
  outcome: string;
}> = [
  {
    goalId: "band-rehearsal",
    scenario: "band",
    title: "Подготовить к репетиции",
    detail: "партии, клик, минус, выдача",
    outcome: "Группа получает рабочий план до следующей репетиции.",
  },
  {
    goalId: "band-parts",
    scenario: "band",
    title: "Разложить на партии",
    detail: "ноты, TAB, MIDI, PDF",
    outcome: "Каждый музыкант видит свою партию и спорные места.",
  },
  {
    goalId: "band-minus",
    scenario: "band",
    title: "Минус, клик, аудиослои",
    detail: "репетиционные треки",
    outcome: "Можно заниматься без вокала, баса или другого слоя.",
  },
  {
    goalId: "band-boost",
    scenario: "band",
    title: "Усилить припев",
    detail: "энергия, акценты, концовка",
    outcome: "AI предложит, что добавить, чтобы песня звучала сильнее.",
  },
  {
    goalId: "lesson-advanced",
    scenario: "education",
    title: "Ученик может лучше",
    detail: "усложнить партию и домашку",
    outcome: "Сильный ученик получает версию выше базового уровня.",
  },
  {
    goalId: "lesson-ensemble",
    scenario: "education",
    title: "Школьный ансамбль",
    detail: "раздать роли по уровню",
    outcome: "Песня раскладывается на несколько учеников и партий.",
  },
];

const scenarioCopy: Record<Scenario, { label: string; description: string }> = {
  band: {
    label: "Для группы",
    description: "Подготовка кавера к репетиции или сцене: партии, аудиослои, минус, клик и адаптация под состав.",
  },
  education: {
    label: "Для обучения",
    description: "Разбор песни для урока, домашки, сильного ученика или школьного ансамбля.",
  },
};

const workspaceTabs: Array<{ id: WorkspaceTab; label: string; hint: string }> = [
  { id: "overview", label: "Обзор", hint: "что получилось" },
  { id: "materials", label: "Материалы", hint: "что собрано" },
  { id: "lineup", label: "Состав", hint: "кто играет" },
  { id: "review", label: "Проверка", hint: "что проверить" },
  { id: "director", label: "AI-директор", hint: "что поменять" },
  { id: "export", label: "Выдача", hint: "кому и что" },
];

const setupLabelByKey: Record<string, string> = {
  rehearsalDate: "Срок репетиции",
  vocalRange: "Диапазон вокала",
  guitars: "Гитаристов",
  bass: "Бас",
  keys: "Клавиши",
  drums: "Барабаны",
  targetStyle: "Стиль версии",
  instrument: "Инструмент ученика",
  level: "Уровень",
  lessonGoal: "Цель урока",
  difficulty: "Сложность результата",
  partsCount: "Количество партий",
  classInstruments: "Инструменты в классе",
  recipientFormat: "Кому выдать",
};

const formatConfidence = (value: number) => `${Math.round(value * 100)}%`;

/**
 * Пороги уверенности задаёт дизайн-система (docs/design/tokens.json,
 * confidence.high = 85, confidence.medium = 75): 85 и выше — акцент,
 * 75-84 — внимание, ниже 75 — опасность.
 */
const confidenceLevel = (value: number): "high" | "mid" | "low" =>
  value >= 0.85 ? "high" : value >= 0.75 ? "mid" : "low";

const lowConfidenceThreshold = 0.8;

/** Русское склонение по числу: 1 находка, 2 находки, 5 находок. */
const plural = (count: number, one: string, few: string, many: string): string => {
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return many;
  const mod10 = count % 10;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
};

/** Ниже этого порога аккорд показывается под вопросом (порог «внимание» из токенов). */
const mediumConfidenceThreshold = 0.75;

const initialScenario: Scenario = "band";
const initialGoalId: ProcessingGoalId = "band-rehearsal";

/**
 * Какие шаги на этом пути действительно выполняются.
 *
 * Демо-разбор существует заранее, поэтому его шаги настоящие. На пути
 * загрузки звук не обрабатывается вовсе: разделения на слои, аккордов, MIDI
 * и нот не происходит, Stage Pack остаётся пустым. Раньше все восемь шагов
 * доходили до «готово» и рисовали четыре зелёные вехи за несделанную работу.
 *
 * Ровно поэтому здесь не появляются новые «настоящие» шаги вроде «Чтение
 * файла»: у демо файла нет (`format: "DEMO"`), и такой шаг стал бы той же
 * неправдой, только на другом пути.
 */
export const runnableStepIds = (project: Project): string[] =>
  project.analysis.source === "demo" ? project.processing.steps.map((step) => step.id) : [];

const stepStatusForIndex = (
  stepIndex: number,
  activeIndex: number,
  stepId: string,
  errorStepId: string | null,
  runnable: string[],
): ProcessingStep["status"] => {
  if (!runnable.includes(stepId)) {
    return "skipped";
  }

  if (stepIndex === activeIndex && stepId === errorStepId) {
    return "error";
  }

  if (stepIndex < activeIndex) {
    return stepId === "structure" ? "warning" : "done";
  }

  if (stepIndex === activeIndex) {
    return "running";
  }

  return "queued";
};

function makeProcessingSteps(project: Project, activeIndex: number, errorStepId: string | null = null): ProcessingStep[] {
  const runnable = runnableStepIds(project);

  return project.processing.steps.map((step, index) => ({
    ...step,
    status: stepStatusForIndex(index, activeIndex, step.id, errorStepId, runnable),
  }));
}

export default function App() {
  // Открытая песня переживает перезагрузку вкладки. Хранилище локальное:
  // localStorage браузера, не облако. Подробности и границы — в
  // src/services/projectStorage.ts.
  const [screen, setScreen] = useState<Screen>("start");
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [goalId, setGoalId] = useState<ProcessingGoalId>(initialGoalId);
  const [fileName, setFileName] = useState("");
  const [fileFacts, setFileFacts] = useState<AudioFacts | null>(null);
  const [isDecoding, setIsDecoding] = useState(false);
  const [acceptedConsent, setAcceptedConsent] = useState(false);
  const [project, setProject] = useState<Project | null>(() => loadProject());
  const [processingIndex, setProcessingIndex] = useState(0);
  const [processingSteps, setProcessingSteps] = useState<ProcessingStep[]>([]);
  const [retriedSteps, setRetriedSteps] = useState<string[]>([]);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("overview");
  const [bandSettings, setBandSettings] = useState<Record<string, string>>({
    rehearsalDate: "через 5 дней",
    vocalRange: "A2-E4",
    guitars: "1",
    bass: "4 струны",
    keys: "да, закрывает слои",
    drums: "средний уровень",
    targetStyle: "плотнее и сценически",
  });
  const [lessonSettings, setLessonSettings] = useState<Record<string, string>>({
    instrument: "гитара",
    level: "начальный",
    lessonGoal: "сыграть куплет и припев с кликом",
    difficulty: "проще оригинала",
    partsCount: "3",
    classInstruments: "гитара, клавиши, перкуссия, вокал",
    recipientFormat: "ученику и преподавателю",
  });

  const goals = useMemo(() => getGoalsForScenario(scenario), [scenario]);
  const selectedGoal = useMemo(
    () => processingGoals.find((goal) => goal.id === goalId) ?? goals[0],
    [goalId, goals],
  );
  const demos = useMemo(() => listDemoProjects(), []);

  useEffect(() => {
    window.scrollTo({ left: 0, top: 0 });
  }, [screen]);

  useEffect(() => {
    const currentGoals = getGoalsForScenario(scenario);
    if (!currentGoals.some((goal) => goal.id === goalId)) {
      setGoalId(currentGoals[0].id);
    }
  }, [scenario, goalId]);

  const failingStepId =
    project && project.upload.quality === "low" && !retriedSteps.includes("stems") ? "stems" : null;
  const activeStepId = project?.processing.steps[processingIndex]?.id ?? null;
  const errorStepId = failingStepId && activeStepId === failingStepId ? failingStepId : null;

  useEffect(() => {
    if (screen !== "processing" || !project) {
      return;
    }

    setProcessingSteps(makeProcessingSteps(project, processingIndex, errorStepId));

    if (errorStepId) {
      return;
    }

    if (processingIndex >= runnableStepIds(project).length) {
      const timer = window.setTimeout(() => {
        setProject((current) =>
          current
            ? {
                ...current,
                processing: {
                  ...current.processing,
                  status: "ready",
                  progressPercent: 100,
                  // Пропущенные остаются пропущенными. Раньше здесь всем
                  // шагам подряд ставился «done», и регресс был невидим в
                  // вёрстке: экран уже сменился.
                  steps: makeProcessingSteps(current, runnableStepIds(current).length),
                },
              }
            : current,
        );
        setSelectedArtifactId(project.stagePack.artifacts[0]?.id ?? null);
        setScreen("stage-pack");
      }, 650);

      return () => window.clearTimeout(timer);
    }

    const timer = window.setTimeout(() => {
      setProcessingIndex((value) => value + 1);
    }, 520);

    return () => window.clearTimeout(timer);
  }, [screen, project, processingIndex, errorStepId]);

  const startProcessing = (nextProject: Project) => {
    setProject(nextProject);
    setProcessingIndex(0);
    setRetriedSteps([]);
    setProcessingSteps(makeProcessingSteps(nextProject, 0));
    setWorkspaceTab("overview");
    setScreen("processing");
  };

  const openDemo = (demoId: string) => {
    // Сценарий и цель здесь намеренно не трогаются. Это выбор пользователя
    // на стартовом экране, а не свойство демо: раньше просмотр демо подменял
    // задание своим, и после возврата подсветка карточки показывала чужое.
    // Открытый проект несет собственные сценарий и цель внутри себя.
    startProcessing(createProjectFromDemo(demoId));
  };

  const selectFile = async (file: File | null) => {
    setFileFacts(null);

    if (!file) {
      setFileName("");
      setUploadError(null);
      return;
    }

    const error = validateUploadFile(file);
    if (error) {
      setFileName("");
      setUploadError(error);
      return;
    }

    setFileName(file.name);
    setUploadError(null);
    setIsDecoding(true);

    // Декодирование в браузере: файл никуда не отправляется.
    const result = await readAudioFacts(file, browserDecoder);
    setIsDecoding(false);

    if (!result.ok) {
      setFileName("");
      setUploadError(result.error);
      return;
    }

    setFileFacts(result.facts);
  };

  const startUploadProject = () => {
    const nextProject = createProjectFromUpload({
      scenario,
      goalId,
      fileName,
      acceptedConsent,
      facts: fileFacts ?? undefined,
      // Снимок — для показа, `setup` — для расчёта. Раньше сервис искал
      // значения в снимке по русским подписям, и переименование подписи
      // молча заменяло настройку пользователя умолчанием.
      setupSnapshot: {
        scenario,
        title: scenario === "band" ? "Состав группы" : "Учебная задача",
        fields: Object.entries(scenario === "band" ? bandSettings : lessonSettings).map(([key, value]) => ({
          label: setupLabelByKey[key] ?? key,
          value,
        })),
      },
      setup:
        scenario === "band"
          ? {
              kind: "band",
              vocalRange: bandSettings.vocalRange,
              guitars: Number.parseInt(bandSettings.guitars, 10) || 1,
              bass: bandSettings.bass,
              keys: bandSettings.keys,
              drums: bandSettings.drums,
              targetStyle: bandSettings.targetStyle,
            }
          : {
              kind: "lesson",
              instrument: lessonSettings.instrument,
              level: lessonSettings.level,
              lessonGoal: lessonSettings.lessonGoal,
              difficulty: lessonSettings.difficulty,
            },
    });
    startProcessing(nextProject);
  };

  // Сохраняем при каждом изменении, а не по кнопке: кнопки «сохранить» в
  // продукте нет, и пользователь вправе рассчитывать, что работа не пропадет.
  const [songs, setSongs] = useState<StoredProject[]>(() => listStoredProjects());
  const [pendingSongDeletion, setPendingSongDeletion] = useState<StoredProject | null>(null);

  useEffect(() => {
    if (project) {
      saveProject(project, new Date().toISOString());
      setSongs(listStoredProjects());
    }
  }, [project]);

  const deleteSong = (projectId: string) => {
    removeStoredProject(projectId);
    setSongs(listStoredProjects());
    if (project?.id === projectId) {
      setProject(null);
      setScreen("start");
    }
  };

  const canStartJob = fileName.trim().length > 0 && acceptedConsent && !isDecoding && fileFacts !== null;

  return (
    <main className="app-shell">
      <AppHeader
        hasProject={screen === "stage-pack" && project !== null}
        workspaceTab={workspaceTab}
        onHome={() => setScreen("start")}
        onSongs={() => setScreen("songs")}
        onOpenTab={setWorkspaceTab}
      />

      {screen === "start" && (
        <StartScreen
          scenario={scenario}
          setScenario={setScenario}
          goalId={goalId}
          setGoalId={setGoalId}
          fileName={fileName}
          onSelectFile={selectFile}
          uploadError={uploadError}
          isDecoding={isDecoding}
          acceptedConsent={acceptedConsent}
          setAcceptedConsent={setAcceptedConsent}
          canStartJob={canStartJob}
          onStart={startUploadProject}
          onOpenSettings={() => setScreen("setup")}
          demos={demos}
          onOpenDemo={openDemo}
          openProject={project}
          onResume={() => setScreen("stage-pack")}
        />
      )}

      {screen === "songs" && (
        <SongsScreen
          songs={songs}
          onOpen={(stored) => {
            setProject(stored.project);
            setSelectedArtifactId(stored.project.stagePack.artifacts[0]?.id ?? null);
            setWorkspaceTab("overview");
            setScreen("stage-pack");
          }}
          onAskDelete={setPendingSongDeletion}
          onNew={() => setScreen("start")}
        />
      )}

      {pendingSongDeletion && (
        <ConfirmDialog
          title={`Удалить «${pendingSongDeletion.project.name}»?`}
          body="Удалим песню и все, что к ней собрано: версии, материалы и отметки проверки. Хранится она только в этом браузере, копии нигде нет. Отменить нельзя."
          acknowledgement="Понимаю, что копии нет и восстановить будет неоткуда"
          confirmLabel="Удалить навсегда"
          onCancel={() => setPendingSongDeletion(null)}
          onConfirm={() => {
            deleteSong(pendingSongDeletion.project.id);
            setPendingSongDeletion(null);
          }}
        />
      )}

      {screen === "setup" && (
        <SetupScreen
          scenario={scenario}
          selectedGoalLabel={selectedGoal.label}
          bandSettings={bandSettings}
          setBandSettings={setBandSettings}
          lessonSettings={lessonSettings}
          setLessonSettings={setLessonSettings}
          onBack={() => setScreen("start")}
          onStart={startUploadProject}
        />
      )}

      {screen === "processing" && project && (
        <ProcessingScreen
          project={project}
          steps={processingSteps}
          activeIndex={processingIndex}
          errorStepId={errorStepId}
          onRetry={(stepId) => setRetriedSteps((current) => [...current, stepId])}
        />
      )}

      {screen === "stage-pack" && project && (
        <StagePackShell
          project={project}
          setProject={setProject}
          selectedArtifactId={selectedArtifactId}
          setSelectedArtifactId={setSelectedArtifactId}
          workspaceTab={workspaceTab}
          setWorkspaceTab={setWorkspaceTab}
          onBack={() => setScreen("start")}
          onOpenDemo={() => openDemo(scenario === "education" ? "education-lesson-demo" : "band-demo")}
        />
      )}
    </main>
  );
}

/**
 * Шапка продукта по бренд-буку: знак «такт из четырёх долей», навигация,
 * состояние справа. Пункты «Состав» и «Выдача» показываются только когда за
 * ними есть куда идти — мёртвых пунктов в навигации не держим.
 */
function AppHeader({
  hasProject,
  workspaceTab,
  onHome,
  onSongs,
  onOpenTab,
}: {
  hasProject: boolean;
  workspaceTab: WorkspaceTab;
  onHome: () => void;
  onSongs: () => void;
  onOpenTab: (tab: WorkspaceTab) => void;
}) {
  return (
    <header className="app-header">
      <button className="brand-button" type="button" onClick={onHome} aria-label="На главный экран">
        <span className="brand-mark" aria-hidden="true">
          <i />
          <i />
          <i />
          <i />
        </span>
        <strong>Vokal</strong>
      </button>

      <nav className="app-nav" aria-label="Разделы">
        <button type="button" className="app-nav-item" onClick={onSongs}>
          Песни
        </button>
        <button
          type="button"
          className={hasProject ? "app-nav-item" : "app-nav-item active"}
          aria-current={hasProject ? undefined : "page"}
          onClick={onHome}
        >
          Новая песня
        </button>
        {hasProject && (
          <>
            <button
              type="button"
              className={workspaceTab === "lineup" ? "app-nav-item active" : "app-nav-item"}
              aria-current={workspaceTab === "lineup" ? "page" : undefined}
              onClick={() => onOpenTab("lineup")}
            >
              Состав
            </button>
            <button
              type="button"
              className={workspaceTab === "export" ? "app-nav-item active" : "app-nav-item"}
              aria-current={workspaceTab === "export" ? "page" : undefined}
              onClick={() => onOpenTab("export")}
            >
              Выдача
            </button>
          </>
        )}
      </nav>

      <div className="app-header-state">
        <span className="mono-chip">прототип</span>
      </div>
    </header>
  );
}

interface StartScreenProps {
  scenario: Scenario;
  setScenario: (scenario: Scenario) => void;
  goalId: ProcessingGoalId;
  setGoalId: (goalId: ProcessingGoalId) => void;
  fileName: string;
  onSelectFile: (file: File | null) => void;
  uploadError: string | null;
  isDecoding: boolean;
  acceptedConsent: boolean;
  setAcceptedConsent: (accepted: boolean) => void;
  canStartJob: boolean;
  onStart: () => void;
  onOpenSettings: () => void;
  demos: Project[];
  onOpenDemo: (demoId: string) => void;
  /** Открытая песня, если она есть: к ней надо чем-то вернуться. */
  openProject: Project | null;
  onResume: () => void;
}

function StartScreen({
  scenario,
  setScenario,
  goalId,
  setGoalId,
  fileName,
  onSelectFile,
  uploadError,
  isDecoding,
  acceptedConsent,
  setAcceptedConsent,
  canStartJob,
  onStart,
  onOpenSettings,
  demos,
  onOpenDemo,
  openProject,
  onResume,
}: StartScreenProps) {
  const recommendedDemo = demos.find((demo) => demo.scenario === scenario) ?? demos[0];
  const activeGoal = processingGoals.find((goal) => goal.id === goalId) ?? getGoalsForScenario(scenario)[0];
  const expectedOutputs = activeGoal.expectedOutputs.slice(0, 4);
  const activeHomeJob =
    homeJobOptions.find((job) => job.goalId === goalId) ??
    homeJobOptions.find((job) => job.scenario === scenario) ??
    homeJobOptions[0];
  const jobText =
    scenario === "band"
      ? `Пример команды: сделай ${activeGoal.label.toLowerCase()}, отметь слабые места и собери материалы музыкантам.`
      : `Пример команды: сделай ${activeGoal.label.toLowerCase()}, учти уровень ученика и собери домашнее задание.`;
  const chooseHomeJob = (job: (typeof homeJobOptions)[number]) => {
    setScenario(job.scenario);
    setGoalId(job.goalId);
  };

  return (
    <section className="home-screen">
      <div className="home-hero">
        <section className="home-lead">
          <div>
            <p className="eyebrow">Stage Pack · прототип</p>
            <h1>От выбора песни до выдачи материалов</h1>
            <p className="intro-copy">
              Прототип проходит весь путь: цель, разбор, Stage Pack, выдача. Звук не обрабатывается — форма, аккорды
              и партии взяты из демо-данных.
            </p>
          </div>
          <div className="hero-proof-row" aria-label="Что собрано в прототипе">
            <span>форма и аккорды</span>
            <span>партии и материалы</span>
            <span>сомнительные места</span>
            <span>версии и выдача</span>
          </div>
        </section>

        <section className="job-card hero-job-card" aria-label="Задание AI-директору">
          <div className="job-card-head">
            <span>1</span>
            <div>
              <h2>Соберите задание</h2>
              <p>Выберите, что нужно получить. Уточнения можно добавить отдельным шагом.</p>
            </div>
          </div>

          <div className="home-job-grid" role="radiogroup" aria-label="Что сделать с песней">
            {homeJobOptions.map((job) => (
              <button
                key={job.goalId}
                type="button"
                role="radio"
                aria-checked={job.goalId === activeHomeJob.goalId}
                className={job.goalId === activeHomeJob.goalId ? "home-job-option selected" : "home-job-option"}
                onClick={() => chooseHomeJob(job)}
              >
                <strong>{job.title}</strong>
                <span>{job.detail}</span>
              </button>
            ))}
          </div>

          <div className="job-director-command" aria-label="Команда AI-директору">
            <Sparkles size={18} />
            <span>
              <b>{activeHomeJob.outcome}</b> {jobText}
            </span>
          </div>

          <label className={uploadError ? "drop-zone job-drop-zone invalid" : "drop-zone job-drop-zone"}>
            <FileAudio size={30} />
            <span>
              {isDecoding
                ? "Читаем файл в браузере..."
                : fileName || "Выберите MP3, WAV, FLAC или M4A. Файл останется на устройстве"}
            </span>
            <input
              type="file"
              accept=".mp3,.wav,.flac,.m4a,audio/*"
              onChange={(event) => onSelectFile(event.target.files?.[0] ?? null)}
            />
          </label>

          {uploadError && (
            <p className="field-error" role="alert">
              <AlertTriangle size={15} />
              {uploadError}
            </p>
          )}

          <label className="consent-row compact">
            <input
              type="checkbox"
              checked={acceptedConsent}
              onChange={(event) => setAcceptedConsent(event.target.checked)}
            />
            <span>Я вправе обработать этот материал для приватной репетиции, урока или внутренней подготовки.</span>
          </label>

          <div className="job-result-row" aria-label="Что покажем в разборе">
            {expectedOutputs.map((output) => (
              <span key={output}>{output}</span>
            ))}
          </div>

          <button className="btn btn-primary job-action" type="button" disabled={!canStartJob} onClick={onStart}>
            <Sparkles size={18} />
            Разобрать мой файл
          </button>

          {!canStartJob && (
            <p className="action-hint">
              {isDecoding
                ? "Читаем файл, это займет мгновение."
                : !fileName
                  ? "Чтобы продолжить, выберите файл песни."
                  : "Чтобы продолжить, подтвердите право обработать этот материал."}
            </p>
          )}

          <button className="settings-link" type="button" disabled={!canStartJob} onClick={onOpenSettings}>
            <SlidersHorizontal size={16} />
            Уточнить состав и уровень
          </button>

          <div className="free-preview-note">
            <CheckCircle2 size={16} />
            <span>Дальше — Stage Pack на демо-данных: PDF, MIDI и треки показаны схематично, файлы не создаются.</span>
          </div>
        </section>

        <HomeResultPreview activeGoalLabel={activeGoal.label} expectedOutputs={expectedOutputs} scenario={scenario} />
      </div>

      {/*
        Уход на главный экран не удаляет песню — она остаётся в памяти. Но
        раньше к ней не вело ничего: работа становилась недостижимой без
        предупреждения. Возврат стоит первым, до демо и загрузки.
      */}
      {openProject && (
        <section className="resume-row">
          <div>
            <p className="eyebrow">Песня открыта</p>
            <strong>{openProject.name}</strong>
            {/*
              Пользователь вправе знать, где лежит его работа. Хранилище
              локальное: другой браузер и другое устройство её не увидят, а
              очистка данных сайта удалит.
            */}
            <span className="privacy-note">Сохранена в этом браузере, на сервер не уходит</span>
          </div>
          <button className="btn btn-outline" type="button" onClick={onResume}>
            <ArrowRight size={18} />
            Вернуться к песне
          </button>
        </section>
      )}

      <div className="home-support-row">
        <section className="demo-spotlight">
          <div>
            <div className="section-title">
              <FolderOpen size={17} />
              <span>Демо без загрузки</span>
            </div>
            <h2>{recommendedDemo.name}</h2>
            <p>{scenarioCopy[recommendedDemo.scenario].description}</p>
          </div>
          <button className="btn btn-outline" type="button" onClick={() => onOpenDemo(recommendedDemo.id)}>
            <ArrowRight size={18} />
            Открыть демо-разбор
          </button>
        </section>

        <div className="launch-stack">
          {demos
            .filter((demo) => demo.id !== recommendedDemo.id)
            .map((demo) => (
              <button key={demo.id} type="button" className="demo-row" onClick={() => onOpenDemo(demo.id)}>
                <span>{demo.name}</span>
                <small>{scenarioCopy[demo.scenario].label}</small>
              </button>
            ))}
        </div>

        <AccessModel />
      </div>

    </section>
  );
}

function HomeResultPreview({
  activeGoalLabel,
  expectedOutputs,
  scenario,
}: {
  activeGoalLabel: string;
  expectedOutputs: string[];
  scenario: Scenario;
}) {
  const tracks =
    scenario === "education"
      ? ["ученик", "преподаватель", "ансамбль", "домашка"]
      : ["вокал", "барабаны", "бас", "гитара", "клавиши"];

  return (
    <aside className="home-result-preview" aria-label="Превью результата">
      <div className="result-preview-top">
        <span>После запуска</span>
        <b>демо-данные</b>
      </div>
      <div className="result-preview-title">
        <strong>{activeGoalLabel}</strong>
        <span>{scenario === "education" ? "урок, уровень, домашка" : "репетиция, партии, выдача"}</span>
      </div>
      <div className="preview-wave" aria-label="Форма песни">
        {[42, 68, 54, 86, 60, 74, 48, 92, 56, 70, 44, 78].map((height, index) => (
          <i key={index} style={{ height: `${height}%` }} />
        ))}
      </div>
      <div className="preview-output-row">
        {expectedOutputs.map((output) => (
          <span key={output}>{output}</span>
        ))}
      </div>
      <div className="preview-track-list">
        {tracks.map((track, index) => (
          <div key={track} className="preview-track">
            <span>{track}</span>
            <i>
              <b style={{ width: `${72 - index * 5}%` }} />
            </i>
          </div>
        ))}
      </div>
      <div className="preview-ai-note">
        <Sparkles size={16} />
        <span>
          В демо-разборе отмечены сомнительные места и предложение AI-директора:{" "}
          {scenario === "education" ? "партия сложнее для ученика" : "усилить припев"}.
        </span>
      </div>
    </aside>
  );
}

function AccessModel() {
  return (
    <section className="access-model" aria-label="Что внутри прототипа">
      <article className="access-card free">
        <span>собрано</span>
        <strong>Демо-песни и разборы</strong>
        <p>Оба сценария, цели, форма, аккорды, партии и материалы Stage Pack — на заранее собранных данных.</p>
      </article>
      <article className="access-card trial">
        <span>имитация</span>
        <strong>Шаги и действия</strong>
        <p>Обработка идет по таймеру. Действия AI-директора меняют версию, статусы и историю правок внутри прототипа.</p>
      </article>
      <article className="access-card pro">
        <span>нужна обработка</span>
        <strong>Файлы и ссылки</strong>
        <p>PDF, MIDI, аудиослои, ZIP и ссылки для музыкантов в прототипе не создаются — для них нужна настоящая обработка звука.</p>
      </article>
    </section>
  );
}

interface SetupScreenProps {
  scenario: Scenario;
  selectedGoalLabel: string;
  bandSettings: Record<string, string>;
  setBandSettings: (settings: Record<string, string>) => void;
  lessonSettings: Record<string, string>;
  setLessonSettings: (settings: Record<string, string>) => void;
  onBack: () => void;
  onStart: () => void;
}

function SetupScreen({
  scenario,
  selectedGoalLabel,
  bandSettings,
  setBandSettings,
  lessonSettings,
  setLessonSettings,
  onBack,
  onStart,
}: SetupScreenProps) {
  const fields =
    scenario === "band"
      ? [
          ["vocalRange", "Диапазон вокала"],
          ["guitars", "Гитаристов"],
          ["keys", "Клавиши и слои"],
          ["targetStyle", "Что усилить"],
        ]
      : [
          ["instrument", "Инструмент ученика"],
          ["level", "Уровень"],
          ["lessonGoal", "Что должно получиться"],
          ["classInstruments", "Инструменты и ученики"],
        ];

  const values = scenario === "band" ? bandSettings : lessonSettings;
  const setValues = scenario === "band" ? setBandSettings : setLessonSettings;
  const summaryFields = fields.slice(0, 5).map(([key, label]) => ({
    label,
    value: values[key] ?? "",
  }));
  const promiseList =
    scenario === "band"
      ? [
          "состав сохранится в карточке песни",
          "сомнительные места покажем отдельно",
          "файлы и ссылки пока не создаются",
        ]
      : [
          "уровень ученика сохранится в проекте",
          "роли и домашнее задание покажем отдельно",
          "файлы и ссылки пока не создаются",
        ];

  return (
    <section className="setup-view">
      <button className="text-button" type="button" onClick={onBack}>
        <ArrowLeft size={17} />
        Назад к заданию
      </button>

      <div className="setup-header">
        <p className="eyebrow">{scenarioCopy[scenario].label}</p>
        <h1>Уточнить перед запуском</h1>
        <p>
          Шаг необязательный. Уточнения сохранятся в карточке песни, на демо-разбор они не влияют.
        </p>
      </div>

      <div className="setup-layout">
        <div className="settings-stack">
          <section className="settings-card setup-focus-card">
            <div className="section-title">
              <Sparkles size={17} />
              <span>Выбранная задача</span>
            </div>
            <h2>{selectedGoalLabel}</h2>
            <p>Задачу можно поменять на главной. Здесь — короткие уточнения о составе или об ученике.</p>
          </section>

          <section className="settings-card">
            <div className="section-title">
              <SlidersHorizontal size={17} />
              <span>{scenario === "band" ? "4 уточнения о составе" : "4 уточнения об уроке"}</span>
            </div>
            <div className="form-grid">
              {fields.map(([key, label]) => (
                <label key={key} className="field">
                  <span>{label}</span>
                  <input
                    value={values[key] ?? ""}
                    onChange={(event) => setValues({ ...values, [key]: event.target.value })}
                  />
                </label>
              ))}
            </div>
          </section>
        </div>

        <aside className="setup-summary-card">
          <div className="section-title">
            <ListChecks size={17} />
            <span>Что попадет в проект</span>
          </div>
          <h2>Можно запускать</h2>
          <div className="setup-promise-list">
            {promiseList.map((item) => (
              <span key={item}>
                <CheckCircle2 size={15} />
                {item}
              </span>
            ))}
          </div>
          <div className="brief-list">
            {summaryFields.map((field) => (
              <span key={field.label}>
                <b>{field.label}</b>
                {field.value}
              </span>
            ))}
          </div>
          <button className="btn btn-primary" type="button" onClick={onStart}>
            <Activity size={18} />
            Разобрать мой файл
          </button>
        </aside>
      </div>

      <div className="setup-notes">
        <div>
          <Sparkles size={18} />
          <span>Сначала откроется обзор, а не список файлов.</span>
        </div>
        <div>
          <AlertTriangle size={18} />
          <span>Сомнительные места — отдельно: принять, исправить или оставить на репетицию.</span>
        </div>
      </div>
    </section>
  );
}

function ProcessingScreen({
  project,
  steps,
  activeIndex,
  errorStepId,
  onRetry,
}: {
  project: Project;
  steps: ProcessingStep[];
  activeIndex: number;
  errorStepId: string | null;
  onRetry: (stepId: string) => void;
}) {
  // Знаменатель — выполняемые шаги, а не все. Когда выполнять нечего,
  // прогресс равен 100 сразу: работа окончена, а не застряла.
  const runnableCount = runnableStepIds(project).length;
  const progress = runnableCount === 0 ? 100 : Math.min(100, Math.round((activeIndex / runnableCount) * 100));
  const nothingRuns = runnableCount === 0;
  const failedStep = errorStepId ? steps.find((step) => step.id === errorStepId) : undefined;
  const currentStep =
    steps.find((step) => step.status === "error") ??
    steps.find((step) => step.status === "running") ??
    [...steps].reverse().find((step) => step.status === "done" || step.status === "warning") ??
    steps[0];
  const getMilestoneStatus = (ids: string[]): ProcessingStep["status"] => {
    const relatedSteps = steps.filter((step) => ids.includes(step.id));

    if (relatedSteps.some((step) => step.status === "error")) {
      return "error";
    }

    if (relatedSteps.some((step) => step.status === "running")) {
      return "running";
    }

    if (relatedSteps.some((step) => step.status === "warning")) {
      return "warning";
    }

    if (relatedSteps.length > 0 && relatedSteps.every((step) => step.status === "skipped")) {
      return "skipped";
    }

    if (relatedSteps.length > 0 && relatedSteps.every((step) => step.status === "done")) {
      return "done";
    }

    return "queued";
  };

  return (
    <section className="processing-view">
      <div className="processing-card">
        <div className="panel-heading">
          <Activity size={24} />
          <div>
            <h1>{project.analysis.source === "demo" ? "Собираем демо-разбор" : "Читаем ваш файл"}</h1>
            <p>{project.name}</p>
          </div>
        </div>

        <div className="progress-track" aria-label={`Прогресс ${progress}%`}>
          <span style={{ width: `${progress}%` }} />
        </div>

        <p className="processing-disclaimer">
          {nothingRuns
            ? "Прототип читает свойства файла. Звук не обрабатывается, разбор не создается."
            : "Шаги идут по таймеру, звук не обрабатывается."}
        </p>

        <div className={failedStep ? "processing-focus failed" : "processing-focus"}>
          <span>{progress}%</span>
          <div>
            <strong>{nothingRuns ? "Разбор не создается" : (currentStep?.label ?? "Запуск")}</strong>
            <p>
              {nothingRuns
                ? "Прочитаны формат, длительность, каналы и частота. Больше с файлом ничего не делается."
                : (currentStep?.detail ?? "Первый шаг демо-разбора.")}
            </p>
          </div>
        </div>

        {failedStep && (
          <div className="processing-error" role="alert">
            <AlertTriangle size={18} />
            <div>
              <strong>Шаг «{failedStep.label}» не прошел</strong>
              <p>Так в продукте будет выглядеть сбой на исходнике низкого качества. Шаг можно повторить.</p>
            </div>
            <button className="secondary-action" type="button" onClick={() => onRetry(failedStep.id)}>
              <Repeat2 size={16} />
              Повторить шаг
            </button>
          </div>
        )}

        <div className="processing-milestones" aria-label="Этапы обработки">
          {processingMilestones.map((milestone) => {
            const status = getMilestoneStatus(milestone.stepIds);

            return (
              <div key={milestone.label} className={`processing-milestone ${status}`}>
                <span className="step-icon">
                  {status === "done" ? (
                    <CheckCircle2 size={18} />
                  ) : status === "warning" || status === "error" ? (
                    <AlertTriangle size={18} />
                  ) : status === "skipped" ? (
                    <MinusCircle size={18} />
                  ) : (
                    <Clock3 size={18} />
                  )}
                </span>
                <strong>{milestone.label}</strong>
                <small>{status === "skipped" ? "не выполняется" : milestone.detail}</small>
              </div>
            );
          })}
        </div>

        {project.processing.warnings.length > 0 && (
          <div className="processing-warnings" aria-label="Предупреждения обработки">
            <strong>
              <AlertTriangle size={16} />
              Что уже видно
            </strong>
            {project.processing.warnings.map((warning) => (
              <span key={warning}>{warning}</span>
            ))}
          </div>
        )}

        {/*
          Оценка сложности показывается только там, где обработка идёт. На
          пути загрузки экран строкой выше говорит «Разбор не создается» —
          оценка работы, которой не будет, противоречит ей же.
        */}
        {!nothingRuns && <CostEstimateBox estimate={project.costEstimate} />}
      </div>
    </section>
  );
}

function CostEstimateBox({ estimate, compact = false }: { estimate: CostEstimate; compact?: boolean }) {
  return (
    <div className={compact ? "cost-estimate compact" : "cost-estimate"} aria-label="Оценка сложности обработки">
      <div className="cost-estimate-head">
        <Gauge size={16} />
        <strong>Оценка сложности</strong>
        <span className={`cost-chip ${estimate.complexity}`}>{complexityCopy[estimate.complexity]}</span>
      </div>
      <div className="cost-estimate-metrics">
        <span>
          <b>{estimate.credits}</b>
          условных единиц сложности
        </span>
        <span>
          <b>{tierCopy[estimate.tier]}</b>
          режим
        </span>
      </div>
      {!compact && (
        <div className="cost-estimate-notes">
          {estimate.notes.map((note) => (
            <span key={note}>{note}</span>
          ))}
        </div>
      )}
    </div>
  );
}

const artifactStatusCopy = {
  ready: "готово",
  draft: "черновик",
  needs_review: "проверить",
  rebuild_required: "пересобрать",
  pending: "нет в демо",
} as const;

const audienceCopy: Record<Project["stagePack"]["artifacts"][number]["audience"], string> = {
  all: "всем",
  band: "группе",
  teacher: "преподавателю",
  student: "ученику",
  instrument: "по инструменту",
};

const reviewStatusCopy: Record<ReviewStatus, string> = {
  needs_review: "нужно проверить",
  checked: "проверено",
  fixed: "исправлено",
  uncertain: "сомнительно",
  accepted_for_rehearsal: "принято для репетиции",
};

const versionStatusCopy: Record<ArrangementVersion["status"], string> = {
  draft: "черновик",
  needs_review: "нужна проверка",
  approved: "принята",
  distributed: "выдана",
};

const actionLabel: Record<DirectorActionId, string> = {
  "transpose-down-2": "Опустить на тон",
  "merge-guitars": "Объединить гитары",
  "move-strings-to-keys": "Перенести струнные на клавиши",
  "simplify-drums": "Упростить барабаны",
  "beginner-bass": "Упростить бас",
  "boost-chorus": "Усилить припев",
  "practice-without-bass": "Собрать трек без баса",
  "education-version": "Сделать учебную версию",
  "advanced-student-part": "Усложнить партию",
  "student-ensemble": "Разложить на ансамбль",
  "lesson-analysis": "Разобрать к уроку",
};

const uploadQualityCopy = {
  good: "хорошее",
  medium: "среднее",
  low: "низкое",
} as const;

const complexityCopy = {
  low: "низкая сложность",
  medium: "средняя сложность",
  high: "высокая сложность",
} as const;

const tierCopy = {
  fast_draft: "быстрый черновик",
  accurate: "точный разбор",
  multi_version: "несколько версий",
} as const;

const assembledArtifactTypes = new Set(["score", "chords", "lyrics", "teacher", "student"]);

const hasAssembledContent = (artifact: Project["stagePack"]["artifacts"][number]) =>
  assembledArtifactTypes.has(artifact.type);

function StagePackShell({
  project,
  setProject,
  selectedArtifactId,
  setSelectedArtifactId,
  workspaceTab,
  setWorkspaceTab,
  onBack,
  onOpenDemo,
}: {
  project: Project;
  setProject: Dispatch<SetStateAction<Project | null>>;
  selectedArtifactId: string | null;
  setSelectedArtifactId: (artifactId: string) => void;
  workspaceTab: WorkspaceTab;
  setWorkspaceTab: (tab: WorkspaceTab) => void;
  onBack: () => void;
  onOpenDemo: () => void;
}) {
  const [selectedRecipients, setSelectedRecipients] = useState<string[]>(
    project.shareRecipients.filter((recipient) => recipient.status !== "opened").slice(0, 2).map((recipient) => recipient.id),
  );
  const [chatCommand, setChatCommand] = useState("");
  // Какое необратимое действие ждёт подтверждения. null — диалога нет.
  const [pendingDeletion, setPendingDeletion] = useState<"source" | "results" | null>(null);
  const [pickedSuggestions, setPickedSuggestions] = useState<DirectorActionId[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [materialsPage, setMaterialsPage] = useState(0);
  const [onlyPdf, setOnlyPdf] = useState(false);

  const dismissToast = (id: string) => setToasts((current) => current.filter((toast) => toast.id !== id));

  const pushToast = (toast: Omit<Toast, "id">) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    // Третий вытесняет самый старый: больше двух на экране бренд-бук
    // запрещает, иначе они перекрывают то, о чём сообщают.
    setToasts((current) => [...current, { ...toast, id }].slice(-toastLimit));
    window.setTimeout(() => dismissToast(id), toastLifetimeMs(toast));
  };
  const [sessionNote, setSessionNote] = useState(
    project.scenario === "education"
      ? "Ученик уверенно сыграл припев. Следующую версию можно сделать выразительнее."
      : "На репетиции припев просел по энергии. Нужна более плотная концертная версия.",
  );
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const selectedArtifact =
    project.stagePack.artifacts.find((artifact) => artifact.id === selectedArtifactId) ??
    project.stagePack.artifacts[0];
  const hasArtifacts = project.stagePack.artifacts.length > 0;
  // Список материалов листается: одиннадцать строк подряд читаются как
  // свалка, а в бренд-буке таблица показывает страницу и говорит, сколько
  // строк из скольких видно.
  const materialsPageSize = 6;
  const filteredArtifacts = onlyPdf
    ? project.stagePack.artifacts.filter((artifact) => artifact.format === "PDF")
    : project.stagePack.artifacts;
  const pageCount = Math.max(1, Math.ceil(filteredArtifacts.length / materialsPageSize));
  const safePage = Math.min(materialsPage, pageCount - 1);
  const visibleArtifacts = filteredArtifacts.slice(
    safePage * materialsPageSize,
    safePage * materialsPageSize + materialsPageSize,
  );
  const readyArtifacts = project.stagePack.artifacts.filter((artifact) => artifact.status === "ready").length;
  const reviewCount = project.reviewIssues.filter(
    (issue) => issue.status === "needs_review" || issue.status === "uncertain",
  ).length;
  const issuedCount = project.shareRecipients.filter(
    (recipient) => recipient.status === "issued" || recipient.status === "opened",
  ).length;
  const hasStaleBundle = project.exportBundles.some((bundle) => bundle.status !== "ready");
  const confidences = Object.values(project.analysis.confidenceByPart);
  const hasAnalysis = project.analysis.source === "demo";
  // Без разбора среднее считать не из чего: деление на ноль дало бы NaN на экране.
  const averageConfidence = confidences.length
    ? confidences.reduce((sum, value) => sum + value, 0) / confidences.length
    : 0;
  const selectedVersionChanges = currentVersion?.changes ?? [];

  const toggleSuggestion = (actionId: DirectorActionId) => {
    setPickedSuggestions((current) =>
      current.includes(actionId) ? current.filter((id) => id !== actionId) : [...current, actionId],
    );
  };

  const assemblePicked = () => {
    const picked = pickedSuggestions;
    const titles = project.directorSuggestions
      .filter((suggestion) => picked.includes(suggestion.actionId))
      .map((suggestion) => suggestion.title);
    const previousVersionId = project.currentVersionId;
    setProject((current) => (current ? applyDirectorActions(current, picked, titles.join(". ")) : current));
    setPickedSuggestions([]);
    pushToast({
      kind: "success",
      title: `Собрана версия из ${picked.length} ${plural(picked.length, "предложения", "предложений", "предложений")}`,
      detail: "Правки сведены в один шаг и откатываются вместе.",
      action: {
        label: "Отменить",
        run: () => setProject((current) => (current ? rollbackToVersion(current, previousVersionId) : current)),
      },
    });
  };

  const runAction = (actionId: DirectorActionId, userCommand?: string) => {
    const previousVersionId = project.currentVersionId;
    setProject((current) => (current ? applyDirectorAction(current, actionId, userCommand) : current));
    pushToast({
      kind: "success",
      title: "Создана новая версия",
      detail: "Материалы, которых правка касается, помечены на пересборку.",
      action: {
        label: "Отменить",
        run: () => setProject((current) => (current ? rollbackToVersion(current, previousVersionId) : current)),
      },
    });
  };

  const submitReviewComment = (issueId: string, text: string) => {
    setProject((current) => (current ? addReviewComment(current, issueId, text) : current));
  };

  const changeReviewStatus = (issueId: string, status: ReviewStatus) => {
    setProject((current) => (current ? updateReviewIssue(current, issueId, status) : current));
  };

  const toggleRecipient = (recipientId: string) => {
    setSelectedRecipients((current) =>
      current.includes(recipientId) ? current.filter((id) => id !== recipientId) : [...current, recipientId],
    );
  };

  const issueLinks = () => {
    setProject((current) => (current ? createShareLinks(current, selectedRecipients) : current));
  };

  // Предыдущая версия — та, из которой выросла текущая. По ней строится
  // чип «вернуть vN» под ответом директора.
  const previousVersion = project.versions.find(
    (version) => version.id === project.versions.find((v) => v.id === project.currentVersionId)?.parentVersionId,
  );

  const rollbackTo = (versionId: string) => {
    setProject((current) => (current ? rollbackToVersion(current, versionId) : current));
  };

  const rebuildBundle = () => {
    setProject((current) => (current ? rebuildExportBundle(current) : current));
  };

  const deleteSource = () => {
    setProject((current) => (current ? deleteProjectSource(current) : current));
  };

  const deleteResults = () => {
    setProject((current) => (current ? deleteProjectResults(current) : current));
  };

  const addNote = () => {
    setProject((current) => (current && sessionNote.trim() ? addSessionNote(current, sessionNote.trim()) : current));
  };

  /**
   * Разбирает команду пользователя. Возвращает `null`, если ничего не узнал.
   *
   * Раньше здесь стоял `: "boost-chorus"` в конце цепочки, и любая
   * нераспознанная команда молча выполнялась как «усилить припев»: на
   * «убери барабаны» продукт создавал версию с чужими правками и рапортовал
   * об успехе. Настоящего разбора языка нет, поэтому непонятое честнее
   * назвать непонятым.
   */
  const matchCommand = (text: string): DirectorActionId | null => {
    const command = text.toLowerCase();

    if (project.scenario === "education") {
      if (command.includes("слож")) return "advanced-student-part";
      if (command.includes("ансамб")) return "student-ensemble";
      if (command.includes("урок")) return "lesson-analysis";
    }
    if (command.includes("трансп") || command.includes("тональн")) return "transpose-down-2";
    if (command.includes("припев")) return "boost-chorus";
    if (command.includes("гитар")) return "merge-guitars";
    if (command.includes("бас")) return "practice-without-bass";
    if (command.includes("бараб")) return "simplify-drums";
    if (command.includes("струнн") || command.includes("клавиш")) return "move-strings-to-keys";
    return null;
  };

  const submitChat = () => {
    const text = chatCommand.trim();
    if (!text) return;

    const action = matchCommand(text);
    if (action) {
      runAction(action, text);
    } else {
      setProject((current) => (current ? addUnderstoodNothingReply(current, text) : current));
    }
    setChatCommand("");
  };

  const deletionCopy = {
    source: {
      title: "Удалить исходник?",
      body:
        "Удалим загруженный файл. Материалы, собранные из него, останутся, но пересобрать их будет не из чего. Отменить нельзя.",
      acknowledgement: "Понимаю, что пересобрать материалы будет не из чего",
      confirmLabel: "Удалить навсегда",
    },
    results: {
      title: "Удалить результаты?",
      body:
        "Удалим партии, ноты, MIDI, аудиослои и репетиционные треки. Выданные музыкантам ссылки перестанут работать. Отменить нельзя.",
      acknowledgement: "Понимаю, что мои правки партий тоже удалятся",
      confirmLabel: "Удалить навсегда",
    },
  } as const;

  return (
    <section className="stage-shell">
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {pendingDeletion && (
        <ConfirmDialog
          title={deletionCopy[pendingDeletion].title}
          body={deletionCopy[pendingDeletion].body}
          acknowledgement={deletionCopy[pendingDeletion].acknowledgement}
          confirmLabel={deletionCopy[pendingDeletion].confirmLabel}
          onCancel={() => setPendingDeletion(null)}
          onConfirm={() => {
            if (pendingDeletion === "source") {
              deleteSource();
            } else {
              deleteResults();
            }
            setPendingDeletion(null);
          }}
        />
      )}

      <div className="stage-toolbar">
        <button className="text-button" type="button" onClick={onBack}>
          <ArrowLeft size={17} />
          Новая песня
        </button>
        <div>
          <h1>{project.name}</h1>
          <p>
            {hasAnalysis
              ? `${project.analysis.key}, ${project.analysis.bpm} BPM, ${project.analysis.meter}, точность разбора ${formatConfidence(averageConfidence)}`
              : `${project.upload.fileName} · ${project.analysis.duration}`}
          </p>
        </div>
        <span className="version-pill" title={currentVersion?.label}>
          v{Math.max(project.versions.findIndex((version) => version.id === project.currentVersionId), 0) + 1} ·
          активная
        </span>
      </div>

      <div className="metric-strip" aria-label="Состояние песни">
        {/*
          Без разбора считать нечего. Четыре карточки с нулями читаются как
          «проверено, ничего нет» — обратное правде, поэтому на этом пути
          полоса схлопывается в одну честную карточку.
        */}
        {!hasAnalysis ? (
          <div className="metric-card wide">
            <strong>{project.upload.format}</strong>
            <span>файл прочитан, разбора песни нет</span>
          </div>
        ) : (
          <>
        <div className="metric-card">
          <strong>
            {Number.isInteger(project.analysis.bpm)
              ? project.analysis.bpm
              : project.analysis.bpm.toFixed(1).replace(".", ",")}
          </strong>
          <span>
            BPM · {project.analysis.meter} · {project.analysis.key}
          </span>
        </div>
        <div className="metric-card">
          <strong>
            {readyArtifacts}/{project.stagePack.artifacts.length}
          </strong>
          <span>материалов готово</span>
        </div>
        <div className={reviewCount > 0 ? "metric-card attention" : "metric-card"}>
          <strong>{reviewCount}</strong>
          <span>{plural(reviewCount, "место", "места", "мест")} на проверку</span>
        </div>
        <button
          type="button"
          className={hasStaleBundle ? "metric-card console-card stale" : "metric-card console-card"}
          onClick={() => setWorkspaceTab("export")}
        >
          <span>
            Открыть выдачу
            {hasStaleBundle && <i className="mono-chip on-console">пересобрать</i>}
          </span>
          <strong>
            {issuedCount}/{project.shareRecipients.length} ссылок · ZIP
          </strong>
        </button>
          </>
        )}
      </div>

      <div className="workspace-tabs" role="tablist" aria-label="Разделы Stage Pack">
        {workspaceTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={workspaceTab === tab.id}
            aria-controls={`workspace-${tab.id}`}
            className={workspaceTab === tab.id ? "workspace-tab active" : "workspace-tab"}
            title={tab.hint}
            onClick={() => setWorkspaceTab(tab.id)}
          >
            <strong>{tab.label}</strong>
            <span>{tab.hint}</span>
          </button>
        ))}
      </div>

      {workspaceTab === "overview" && (
        <section id="workspace-overview" className="stage-panel stage-view overview-view" role="tabpanel">
          <div className="overview-main">
            <div className="preview-header">
              <div>
                <p className="eyebrow">{hasAnalysis ? "Демо-разбор" : "Ваш файл"}</p>
                <h2>{project.analysis.title}</h2>
                {hasAnalysis && <p>{project.analysis.summary}</p>}
              </div>
              <span className={hasAnalysis ? "status-badge ready" : "status-badge pending"}>
                {hasAnalysis ? "демо-данные" : "без разбора"}
              </span>
            </div>

            {hasAnalysis ? (
              <div className="song-facts">
                <span>{project.analysis.artist}</span>
                <span>{project.analysis.key}</span>
                <span>{project.analysis.bpm} BPM</span>
                <span>{project.analysis.meter}</span>
                <span>{project.analysis.duration}</span>
                <span>{project.analysis.genre}</span>
              </div>
            ) : (
              <div className="song-facts">
                <span>{project.upload.format}</span>
                <span>{project.analysis.duration}</span>
                {project.upload.sampleRate && <span>{project.upload.sampleRate} Гц</span>}
                {project.upload.channels === 1 && <span>моно</span>}
                {project.upload.channels === 2 && <span>стерео</span>}
              </div>
            )}

            {hasAnalysis && averageConfidence < lowConfidenceThreshold && (
              <div className="inline-warning" role="status">
                <AlertTriangle size={17} />
                <span>
                  Средняя точность разбора {formatConfidence(averageConfidence)}. Это черновик: перед репетицией
                  пройдите проверку.
                </span>
              </div>
            )}

            {project.upload.quality === "low" && (
              <div className="inline-warning" role="status">
                <AlertTriangle size={17} />
                <span>{project.upload.sourceNote} Качество исходника низкое — партии в разборе грубее.</span>
              </div>
            )}

            {hasAnalysis ? (
              <>
                <ConsolePanel project={project} onAction={runAction} />
              </>
            ) : (
              <div className="no-analysis" role="status">
                <Layers3 size={20} />
                <div>
                  <strong>Звук не анализируется</strong>
                  <p>
                    Прототип прочитал файл и показывает его настоящие параметры. Форма песни, аккорды, партии и
                    точность разбора появятся с настоящей обработкой звука — подставлять сюда данные другой песни
                    было бы неправдой.
                  </p>
                  <button className="secondary-action" type="button" onClick={onOpenDemo}>
                    Открыть демо-разбор
                  </button>
                </div>
              </div>
            )}
          </div>

          <aside className="overview-next">
            <div className="access-summary">
              <span>
                <b>Собрано</b>
                {hasAnalysis
                  ? "форма, аккорды, партии, материалы и предложения AI-директора"
                  : "параметры вашего файла: длительность, каналы, частота, качество"}
              </span>
              <span>
                <b>Нужна обработка</b>
                {hasAnalysis
                  ? "PDF, MIDI, аудио и ссылки пока не создаются"
                  : "разбор песни, партии, материалы и выдача"}
              </span>
            </div>

            <section className="subpanel compact">
              <h3>Что делать дальше</h3>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("materials")}>
                Посмотреть материалы
              </button>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("review")}>
                Проверить сомнительные места
              </button>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("director")}>
                Открыть AI-директора
              </button>
            </section>

            {project.directorSuggestions.length > 0 && (
            <section className="subpanel compact">
              {/*
                Бренд-бук называет карточку числом найденного, а не темой:
                «Директор нашёл 3 проблемы». Общей кнопки «Применить и
                пересобрать» здесь нет намеренно — сборка версии сразу из
                нескольких предложений это B98, а кнопка, применяющая одно
                из трёх, обманывает подписью.
              */}
              <h3>
                Директор нашел {project.directorSuggestions.length}{" "}
                {plural(project.directorSuggestions.length, "находку", "находки", "находок")}
              </h3>
              {project.directorSuggestions.slice(0, 3).map((suggestion) => (
                <button
                  key={suggestion.id}
                  className="suggestion-row"
                  type="button"
                  onClick={() => runAction(suggestion.actionId, suggestion.title)}
                >
                  <span>{suggestion.title}</span>
                  <small>{actionLabel[suggestion.actionId]}</small>
                </button>
              ))}
            </section>
            )}
          </aside>
        </section>
      )}

      {workspaceTab === "lineup" && (
        <section id="workspace-lineup" className="stage-panel" role="tabpanel">
          <h2>Состав</h2>
          <LineupPanel project={project} onOpenDemo={onOpenDemo} onFillLineup={onBack} />
        </section>
      )}

      {workspaceTab === "materials" && (
        <section
          id="workspace-materials"
          className={hasArtifacts ? "stage-panel stage-view materials-view" : "stage-panel"}
          role="tabpanel"
        >
          {!hasArtifacts && (
            <div className="no-analysis" role="status">
              <Layers3 size={20} />
              <div>
                <strong>Материалов пока нет</strong>
                <p>
                  Партии, ноты, MIDI и аудиослои собираются из разбора песни. Пока звук не обрабатывается,
                  собирать их не из чего. Как это выглядит на готовом разборе, видно в демо-проекте.
                </p>
                <button className="secondary-action" type="button" onClick={onOpenDemo}>
                  Открыть демо-разбор
                </button>
              </div>
            </div>
          )}
          {hasArtifacts && (
          <>
          <aside className="material-list-pane">
            <div className="pane-title-row">
              <h2>Материалы</h2>
              <div className="pane-tools">
                <button
                  type="button"
                  className={onlyPdf ? "btn btn-outline btn-xs active" : "btn btn-outline btn-xs"}
                  aria-pressed={onlyPdf}
                  onClick={() => {
                    setOnlyPdf((value) => !value);
                    setMaterialsPage(0);
                  }}
                >
                  Только PDF
                </button>
                {/*
                  Выключена: файлов не существует, обработки нет. Кнопка,
                  которая нажимается и ничего не скачивает, — обещание, как
                  кнопка воспроизведения на пульте.
                */}
                <button
                  type="button"
                  className="btn btn-primary btn-xs"
                  disabled
                  title="Файлов пока нет: звук не обрабатывается"
                >
                  Скачать ZIP
                </button>
              </div>
            </div>

            {visibleArtifacts.map((artifact) => (
              <button
                key={artifact.id}
                type="button"
                className={artifact.id === selectedArtifact.id ? "artifact-row active" : "artifact-row"}
                onClick={() => setSelectedArtifactId(artifact.id)}
              >
                <span>{artifact.name}</span>
                <small>
                  <i className="artifact-format">{artifact.format}</i> · {formatConfidence(artifact.confidence)} ·{" "}
                  {artifactStatusCopy[artifact.status]} · {audienceCopy[artifact.audience]}
                </small>
                <span className={hasAssembledContent(artifact) ? "access-label assembled" : "access-label processing"}>
                  {hasAssembledContent(artifact) ? "собрано" : "нужна обработка"}
                </span>
                {artifact.isStale && <em>нужно пересобрать</em>}
              </button>
            ))}

            <div className="pane-footer">
              <span>
                Показаны {visibleArtifacts.length} из {project.stagePack.artifacts.length}
              </span>
              <div className="pager">
                <button
                  type="button"
                  className="btn btn-outline btn-xs"
                  aria-label="Предыдущая страница"
                  disabled={safePage === 0}
                  onClick={() => setMaterialsPage((page) => Math.max(0, page - 1))}
                >
                  <ArrowLeft size={15} />
                </button>
                <span className="pager-position">
                  {safePage + 1} / {pageCount}
                </span>
                <button
                  type="button"
                  className="btn btn-outline btn-xs"
                  aria-label="Следующая страница"
                  disabled={safePage + 1 >= pageCount}
                  onClick={() => setMaterialsPage((page) => Math.min(pageCount - 1, page + 1))}
                >
                  <ArrowRight size={15} />
                </button>
              </div>
            </div>
          </aside>

          <div className="material-preview-pane">
            <div className="preview-header">
              <div>
                <p className="eyebrow">Выбранный материал</p>
                <h2>{selectedArtifact.name}</h2>
                <p>{selectedArtifact.description}</p>
              </div>
              <span className={`status-badge ${selectedArtifact.status}`}>{artifactStatusCopy[selectedArtifact.status]}</span>
            </div>

            {!hasAssembledContent(selectedArtifact) && (
              <div className="pro-note">
                <Layers3 size={18} />
                <span>Здесь пока только карточка материала. Содержимое появится с настоящей обработкой звука.</span>
              </div>
            )}

            <ArtifactPreview project={project} artifact={selectedArtifact} />

            <div className="bundle-box">
              <strong>Пакеты экспорта</strong>
              {project.exportBundles.map((bundle) => (
                <span key={bundle.id}>
                  {bundle.label}: {bundle.filesCount} {plural(bundle.filesCount, "материал", "материала", "материалов")}, {bundle.status === "ready" ? "актуален" : "устарел"}
                </span>
              ))}
            </div>
          </div>
          </>
          )}
        </section>
      )}

      {workspaceTab === "review" && (
        <section id="workspace-review" className="stage-panel stage-view review-view" role="tabpanel">
          <div className="review-main">
            {project.reviewIssues.length === 0 ? (
              <EmptyState
                title="Сомнительных мест нет, потому что нет разбора"
                reason={{ text: "разбора нет", kind: "neutral" }}
                onOpenDemo={onOpenDemo}
              >
                Сомнительные места находит разбор песни. Пока звук не обрабатывается, находить их не в чем — это
                не значит, что в вашей песне все чисто.
              </EmptyState>
            ) : (
            <>
            <div className="preview-header">
              <div>
                <p className="eyebrow">Ручная проверка</p>
                <h2>Сомнительные места</h2>
                <p>AI не притворяется идеальным: сомнительные места вынесены отдельно — их можно принять, исправить или оставить на репетицию.</p>
              </div>
              <span className="status-badge needs_review">{reviewCount} в работе</span>
            </div>

            <div className="review-list">
              {project.reviewIssues.map((issue) => (
                <div key={issue.id} className="review-item">
                  <strong>
                    Такт {issue.bar}: {issue.title}
                  </strong>
                  <p>{issue.reason}</p>
                  {/*
                    Все пять статусов, а не три. «Проверено», «исправлено» и
                    «принято» одинаково заявляют, что вопрос закрыт: музыкант,
                    который посмотрел такт и остался в сомнении, сказать это
                    не мог, а ошибочную отметку не мог отменить.
                  */}
                  <div className="review-actions">
                    {(["checked", "fixed", "accepted_for_rehearsal", "uncertain", "needs_review"] as const)
                      .filter((status) => status !== issue.status)
                      .map((status) => (
                        <button
                          key={status}
                          type="button"
                          className="btn btn-outline btn-xs"
                          onClick={() => changeReviewStatus(issue.id, status)}
                        >
                          {reviewStatusCopy[status]}
                        </button>
                      ))}
                  </div>

                  <ReviewNote issueId={issue.id} onSubmit={submitReviewComment} />
                  <small>
                    {issue.part} · {formatConfidence(issue.confidence)} · {reviewStatusCopy[issue.status]}
                  </small>
                  {project.reviewComments
                    .filter((comment) => comment.issueId === issue.id)
                    .map((comment) => (
                      <p key={comment.id} className="review-comment">
                        <b>{comment.author}:</b> {comment.text}
                      </p>
                    ))}
                </div>
              ))}
            </div>
            </>
            )}
          </div>

          <aside className="review-side">
            <section className="subpanel compact">
              <h3>{project.scenario === "education" ? "Учебные настройки" : "Состав и ограничения"}</h3>
              <div className="constraint-grid">
                {project.scenario === "education" ? (
                  <>
                    <span>Инструмент: {project.studentProfile?.instrument}</span>
                    <span>Уровень: {project.studentProfile?.level}</span>
                    <span>Ноты: {project.studentProfile?.notationReading}</span>
                    <span>Дома: {project.studentProfile?.homeInstrument}</span>
                    <span>Цель: {project.lesson?.goal}</span>
                    <span>Выдача: {project.lesson?.homeworkFormat}</span>
                  </>
                ) : (
                  <>
                    <span>Вокал: {project.bandLineup?.vocalRange}</span>
                    <span>Гитары: {project.bandLineup?.guitars}</span>
                    <span>Бас: {project.bandLineup?.bass === "5 strings" ? "5 струн" : "4 струны"}</span>
                    <span>Клавиши: {project.bandLineup?.keys ? "есть" : "нет"}</span>
                    <span>Барабаны: {project.bandLineup?.drums ? "есть" : "нет"}</span>
                    <span>Стиль: {project.bandLineup?.targetStyle}</span>
                  </>
                )}
              </div>
            </section>

            {project.assignments.length > 0 && (
              <section className="subpanel compact">
                <h3>Назначения</h3>
                <div className="assignment-list">
                  {project.assignments.map((assignment) => (
                    <span key={assignment.id}>
                      {assignment.recipient}: {assignment.title}
                    </span>
                  ))}
                </div>
              </section>
            )}
          </aside>
        </section>
      )}

      {workspaceTab === "director" && (
        <section id="workspace-director" className="stage-panel stage-view director-view" role="tabpanel">
          <div className="director-main">
            <div className="panel-heading">
              <Sparkles size={20} />
              <div>
                <h2>AI-директор</h2>
                <p>{project.analysis.summary}</p>
              </div>
            </div>

            {project.directorSuggestions.length === 0 && (
              <EmptyState
                title="Предложений пока нет"
                reason={{ text: "разбора нет", kind: "neutral" }}
                onOpenDemo={onOpenDemo}
              >
                AI-директор строит предложения на разборе песни: состав, партии, спорные места. Пока разбора нет,
                предлагать нечего.
              </EmptyState>
            )}

            {/*
              Предложения можно отметить и собрать одной версией. По одному
              получалось по версии на каждое: три правки — три шага истории и
              три отката, хотя решение было одно.
            */}
            <div className="suggestions-grid">
              {project.directorSuggestions.slice(0, 4).map((suggestion) => (
                <div key={suggestion.id} className="suggestion-card">
                  <label className="suggestion-pick">
                    <input
                      type="checkbox"
                      checked={pickedSuggestions.includes(suggestion.actionId)}
                      onChange={() => toggleSuggestion(suggestion.actionId)}
                    />
                    <strong>{suggestion.title}</strong>
                  </label>
                  <p>{suggestion.description}</p>
                  <button
                    className="btn btn-accent"
                    type="button"
                    onClick={() => runAction(suggestion.actionId, suggestion.title)}
                  >
                    {actionLabel[suggestion.actionId]}
                  </button>
                </div>
              ))}
            </div>

            {pickedSuggestions.length > 0 && (
              <button className="btn btn-accent btn-block" type="button" onClick={assemblePicked}>
                Собрать версию из {pickedSuggestions.length}{" "}
                {plural(pickedSuggestions.length, "предложения", "предложений", "предложений")}
              </button>
            )}

            <div className="director-thread" aria-label="Разговор с AI-директором">
              {project.chat.length === 0 ? (
                <p className="chat-empty">
                  {project.directorSuggestions.length > 0
                    ? "Разговора пока нет. Выберите предложение директора выше или напишите, что поменять в аранжировке."
                    : "Разговор появится вместе с разбором песни."}
                </p>
              ) : (
                project.chat.map((message) => (
                  <div key={message.id} className={`chat-bubble from-${message.author}`}>
                    <p>{message.text}</p>
                    {message.author === "director" && message.id === project.chat[project.chat.length - 1]?.id && (
                      <div className="chat-actions">
                        <button type="button" className="mono-chip" onClick={() => setWorkspaceTab("review")}>
                          открыть проверку
                        </button>
                        {previousVersion && (
                          <button
                            type="button"
                            className="mono-chip"
                            title={previousVersion.label}
                            onClick={() => rollbackTo(previousVersion.id)}
                          >
                            вернуть v
                            {project.versions.findIndex((version) => version.id === previousVersion.id) + 1}
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            <div className="chat-box">
              <label>
                <span>Команда AI-директору</span>
                <textarea
                  value={chatCommand}
                  onChange={(event) => setChatCommand(event.target.value)}
                  placeholder={
                    project.scenario === "education"
                      ? "Например: усложни партию для сильного ученика"
                      : "Например: усили припев и сделай концовку сценичнее"
                  }
                />
              </label>
              <button className="btn btn-primary" type="button" onClick={submitChat} disabled={!chatCommand.trim()}>
                <Sparkles size={18} />
                Применить в демо
              </button>
            </div>
          </div>

          <aside className="director-side">
            <section className="subpanel compact">
              <h3>Версии</h3>
              <div className="version-list">
                {project.versions.map((version) => (
                  <button
                    key={version.id}
                    type="button"
                    className={version.id === project.currentVersionId ? "version-row active" : "version-row"}
                    onClick={() => rollbackTo(version.id)}
                  >
                    <span>{version.label}</span>
                    <small>{versionStatusCopy[version.status]}</small>
                  </button>
                ))}
              </div>
              <ul className="change-list">
                {selectedVersionChanges.map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
            </section>

            <section className="subpanel compact">
              <h3>{project.scenario === "education" ? "После урока" : "После репетиции"}</h3>
              <textarea
                className="session-note"
                value={sessionNote}
                onChange={(event) => setSessionNote(event.target.value)}
              />
              <button className="secondary-action" type="button" onClick={addNote} disabled={!sessionNote.trim()}>
                Создать следующую версию
              </button>
            </section>
          </aside>
        </section>
      )}

      {workspaceTab === "export" && (
        <section id="workspace-export" className="stage-panel stage-view export-view" role="tabpanel">
          <div className="export-main">
            <div className="plan-banner" aria-label="Что собрано и что появится после обработки">
              <div>
                <Sparkles size={18} />
                <span>
                  <strong>Собрано:</strong> демо-проекты, разбор, материалы, версии и статусы выдачи.
                </span>
              </div>
              <div>
                <Clock3 size={18} />
                <span>
                  <strong>Нужна обработка:</strong> настоящие PDF, MIDI, аудио, ZIP и ссылки для музыкантов.
                </span>
              </div>
            </div>

            <section className="subpanel compact">
              <h3>Кому выдать материалы</h3>
              {project.shareRecipients.length === 0 && (
                <EmptyState
                  title="Получателей пока нет"
                  reason={{ text: "нечего выдавать", kind: "neutral" }}
                  onOpenDemo={onOpenDemo}
                >
                  Список получателей собирается из состава группы или класса, а материалы для выдачи — из разбора.
                  Пока нет ни того, ни другого.
                </EmptyState>
              )}

              <div className="recipient-list">
                {project.shareRecipients.map((recipient) => (
                  <label key={recipient.id} className="recipient-row">
                    <input
                      type="checkbox"
                      checked={selectedRecipients.includes(recipient.id)}
                      onChange={() => toggleRecipient(recipient.id)}
                    />
                    <span>
                      <strong>{recipient.name}</strong>
                      <small>
                        {recipient.material} ·{" "}
                        {recipient.status === "issued"
                          ? "выдано"
                          : recipient.status === "opened"
                            ? "открыто"
                            : recipient.status === "needs_fix"
                              ? "нужна правка"
                              : "не выдано"}
                      </small>
                    </span>
                  </label>
                ))}
              </div>
              <button
                className="secondary-action pro-action"
                type="button"
                onClick={issueLinks}
                disabled={selectedRecipients.length === 0 || project.dataRetention.resultsDeleted}
              >
                <Share2 size={14} />
                Создать демо-ссылки
              </button>
              <button
                className="secondary-action pro-action"
                type="button"
                onClick={rebuildBundle}
                disabled={project.dataRetention.resultsDeleted || project.exportBundles.length === 0}
              >
                <Repeat2 size={14} />
                Пересобрать пакет
              </button>
              {project.dataRetention.resultsDeleted && (
                <p className="action-hint">Результаты удалены, выдача и пересборка недоступны.</p>
              )}
              {project.shareLinks.length > 0 && (
                <div className="mock-links">
                  <em className="mock-links-caption">Демо-ссылки: не открываются</em>
                  {project.shareLinks.map((link) => (
                    <span key={link.id} className={link.status === "stale" ? "stale" : undefined}>
                      {link.label}
                      {link.status === "stale" && <b> · ссылка устарела</b>}
                    </span>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="export-side">
            {project.exportBundles.length > 0 && (
            <div className="bundle-box">
              <strong>Пакеты</strong>
              {project.exportBundles.map((bundle) => (
                <span key={bundle.id}>
                  {bundle.label}: {bundle.filesCount} {plural(bundle.filesCount, "материал", "материала", "материалов")}, {bundle.status === "ready" ? "актуален" : "устарел"}
                </span>
              ))}
            </div>
            )}

            <section className="subpanel compact">
              <h3>Настройки задачи</h3>
              <CostEstimateBox estimate={project.costEstimate} compact />
              <div className="setup-summary-strip compact" aria-label="Настройки задачи">
                <strong>{project.setupSnapshot.title}</strong>
                <div>
                  {project.setupSnapshot.fields.slice(0, 6).map((field) => (
                    <span key={`${field.label}-${field.value}`}>
                      {field.label}: {field.value}
                    </span>
                  ))}
                </div>
              </div>
            </section>

            <section className="subpanel compact">
              <h3>Исходник</h3>
              <div className="constraint-grid">
                <span>Файл: {project.upload.fileName}</span>
                <span>Формат: {project.upload.format}</span>
                <span>Длительность: {formatDuration(project.upload.durationSeconds)}</span>
                <span>Качество: {uploadQualityCopy[project.upload.quality]}</span>
                {project.upload.sampleRate && <span>Частота: {project.upload.sampleRate} Гц</span>}
                {project.upload.channels && (
                  <span>Каналов: {project.upload.channels === 1 ? "1 (моно)" : project.upload.channels}</span>
                )}
                {project.upload.sizeBytes && (
                  <span>Размер: {Math.round(project.upload.sizeBytes / 1024 / 1024)} МБ</span>
                )}
              </div>
              <p className="privacy-note">{project.upload.sourceNote}</p>
            </section>

            <section className="subpanel compact">
              <h3>Приватность</h3>
              <p className="privacy-note">{project.legalConsent.text}</p>
              <div className="retention-grid">
                <span>Исходник: {project.dataRetention.sourceDeleted ? "удален" : "сохранен"}</span>
                <span>Результаты: {project.dataRetention.resultsDeleted ? "удалены" : "сохранены"}</span>
              </div>
              {/*
                Кнопки открывают подтверждение, а не удаляют. Отменить
                удаление нельзя, поэтому спрашивать обязательно.
              */}
              <button
                className="btn btn-outline"
                type="button"
                onClick={() => setPendingDeletion("source")}
                disabled={project.dataRetention.sourceDeleted}
              >
                Удалить исходник
              </button>
              <button
                className="btn btn-danger"
                type="button"
                onClick={() => setPendingDeletion("results")}
                disabled={project.dataRetention.resultsDeleted}
              >
                Удалить результаты
              </button>
            </section>

            <section className="subpanel compact">
              <h3>История</h3>
              {project.changeLog.slice(0, 4).map((entry) => (
                <div key={entry.id} className="history-row">
                  <strong>{entry.title}</strong>
                  <span>{entry.description}</span>
                </div>
              ))}
            </section>
          </aside>
        </section>
      )}
    </section>
  );
}

/**
 * Одно пустое состояние на все вкладки. Пустой заголовок со счетчиком «0»
 * читается как «проверено, проблем нет» — то есть ровно наоборот, поэтому
 * пустоту всегда объясняем и даем один выход.
 */
/**
 * Пустое состояние. По бренд-буку у пустоты есть плашка причины: класс
 * проблемы читается до абзаца, а не вычитывается из него. Где у пустоты
 * есть выход, кроме демо, он стоит первым действием.
 */
function EmptyState({
  title,
  reason,
  children,
  action,
  onOpenDemo,
}: {
  title: string;
  /** Класс причины: «состав не заполнен», «разбора нет». Моноширинная плашка. */
  reason?: { text: string; kind: "attention" | "neutral" | "error" };
  children: ReactNode;
  action?: { label: string; run: () => void };
  onOpenDemo: () => void;
}) {
  return (
    <div className="no-analysis">
      <Layers3 size={20} />
      <div>
        {reason && <span className={`empty-reason ${reason.kind}`}>{reason.text}</span>}
        <strong>{title}</strong>
        <p>{children}</p>
        <div className="empty-actions">
          {action && (
            <button className="btn btn-outline btn-xs" type="button" onClick={action.run}>
              {action.label}
            </button>
          )}
          <button className="btn btn-outline btn-xs" type="button" onClick={onOpenDemo}>
            Открыть демо-разбор
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Пультовая панель. Правило бренд-бука: всё, что связано со звуком, живёт на
 * одной графитовой поверхности — так дорожки, полосы и цифры читаются, а
 * светлая часть интерфейса остаётся для решений и текста.
 *
 * Уверенность подписана процентом рядом с полосой: цвет не единственный
 * сигнал, иначе разбор нечитаем при дальтонизме и в ч/б печати партий.
 */
/**
 * Подтверждение необратимого действия. По бренд-буку: затемнение, белая
 * карточка, обязательный чекбокс согласия, «Оставить» контуром и
 * «Удалить навсегда» красной заливкой — красный в системе закреплён именно
 * за необратимым.
 *
 * Чекбокс здесь не формальность: он держит подтверждающую кнопку
 * выключенной, пока пользователь не прочитал, что именно исчезнет.
 */
export interface Toast {
  id: string;
  kind: "success" | "attention" | "error";
  title: string;
  detail: string;
  /** Действие в тосте. Успех по бренд-буку несёт «Отменить». */
  action?: { label: string; run: () => void };
}

/**
 * Сколько тост живёт. Бренд-бук: шесть секунд, с действием — десять, потому
 * что действие надо успеть прочитать и нажать.
 */
export const toastLifetimeMs = (toast: Pick<Toast, "action">): number => (toast.action ? 10000 : 6000);

/** Одновременно на экране не больше двух: третий вытесняет самый старый. */
export const toastLimit = 2;

function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast ${toast.kind}`} role="status">
          <span className="toast-icon" aria-hidden="true">
            {toast.kind === "success" ? (
              <CheckCircle2 size={17} />
            ) : toast.kind === "error" ? (
              <XCircle size={17} />
            ) : (
              <AlertTriangle size={17} />
            )}
          </span>
          <div className="toast-body">
            <strong>{toast.title}</strong>
            <span>{toast.detail}</span>
          </div>
          {toast.action && (
            <button
              className="btn btn-outline btn-xs"
              type="button"
              onClick={() => {
                toast.action!.run();
                onDismiss(toast.id);
              }}
            >
              {toast.action.label}
            </button>
          )}
          <button
            className="toast-close"
            type="button"
            aria-label="Закрыть уведомление"
            onClick={() => onDismiss(toast.id)}
          >
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}

/**
 * Свой комментарий к сомнительному месту. Раньше в переписке по месту были
 * только автоматические записи о смене статуса: почему решили именно так,
 * записать было негде, и на репетиции это выяснялось заново.
 */
function ReviewNote({
  issueId,
  onSubmit,
}: {
  issueId: string;
  onSubmit: (issueId: string, text: string) => void;
}) {
  const [text, setText] = useState("");

  return (
    <div className="review-note">
      <label>
        <span className="visually-hidden">Комментарий к месту</span>
        <input
          type="text"
          value={text}
          aria-label="Комментарий к месту"
          placeholder="Почему решили так"
          onChange={(event) => setText(event.target.value)}
        />
      </label>
      <button
        className="btn btn-outline btn-xs"
        type="button"
        disabled={!text.trim()}
        onClick={() => {
          onSubmit(issueId, text);
          setText("");
        }}
      >
        Записать
      </button>
    </div>
  );
}

/**
 * Список песен. Появился вместе с хранением (B6): до него пункт навигации
 * вел бы на экран, который всегда пуст, — ровно то, чего мы не строим.
 *
 * Песни лежат в этом браузере и больше нигде. Удаление здесь необратимо не
 * потому, что так задумано, а потому, что копии нет: поэтому оно проходит
 * через подтверждение, как удаление результатов.
 */
function SongsScreen({
  songs,
  onOpen,
  onAskDelete,
  onNew,
}: {
  songs: StoredProject[];
  onOpen: (stored: StoredProject) => void;
  onAskDelete: (stored: StoredProject) => void;
  onNew: () => void;
}) {
  const formatSavedAt = (iso: string) => {
    const date = new Date(iso);
    return Number.isNaN(date.getTime())
      ? "время неизвестно"
      : date.toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
  };

  return (
    <section className="songs-screen stage-panel">
      {/*
        Когда список пуст, действие несет пустое состояние: две кнопки с
        одной подписью и одним действием на экране — избыточность, а не
        забота.
      */}
      <div className="pane-title-row">
        <h1>Песни</h1>
        {songs.length > 0 && (
          <button className="btn btn-primary btn-xs" type="button" onClick={onNew}>
            Загрузить песню
          </button>
        )}
      </div>

      {songs.length === 0 ? (
        <div className="no-analysis">
          <Layers3 size={20} />
          <div>
            <span className="empty-reason neutral">ничего не открыто</span>
            <strong>Пока ни одной песни</strong>
            <p>
              Загрузите mp3, wav, flac или m4a — или откройте демо-разбор, чтобы посмотреть, как выглядит готовый
              Stage Pack. Открытые песни останутся здесь.
            </p>
            <div className="empty-actions">
              <button className="btn btn-outline btn-xs" type="button" onClick={onNew}>
                Загрузить песню
              </button>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="songs-list">
            {songs.map((stored) => (
              <div key={stored.project.id} className="song-row">
                <div className="song-body">
                  <strong>{stored.project.name}</strong>
                  <span>
                    {scenarioCopy[stored.project.scenario].label} · {stored.project.versions.length}{" "}
                    {plural(stored.project.versions.length, "версия", "версии", "версий")} · открыта{" "}
                    {formatSavedAt(stored.savedAt)}
                  </span>
                </div>
                <button className="btn btn-outline btn-xs" type="button" onClick={() => onOpen(stored)}>
                  Открыть
                </button>
                <button className="btn btn-danger btn-xs" type="button" onClick={() => onAskDelete(stored)}>
                  Удалить
                </button>
              </div>
            ))}
          </div>
          <p className="privacy-note">
            Песни хранятся в этом браузере и никуда не отправляются. Другое устройство их не увидит, а очистка данных
            сайта удалит.
          </p>
        </>
      )}
    </section>
  );
}

function ConfirmDialog({
  title,
  body,
  acknowledgement,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  acknowledgement: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onCancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="dialog-scrim" role="presentation" onClick={onCancel}>
      <div
        className="dialog-card"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <h2>{title}</h2>
        <p>{body}</p>
        <label className="dialog-ack">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          <span>{acknowledgement}</span>
        </label>
        <div className="dialog-actions">
          <button className="btn btn-outline" type="button" onClick={onCancel}>
            Оставить
          </button>
          <button
            className="btn btn-danger solid"
            type="button"
            disabled={!acknowledged}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Состав: люди, а не количество инструментов. Ограничение стоит рядом с
 * именем, потому что оно принадлежит человеку — диапазон вокалистке, число
 * струн басисту, уровень каждому свой. В плоском `BandLineup` этого не
 * выразить, и директор предлагал транспонирование, не зная, чей диапазон.
 */
function LineupPanel({
  project,
  onOpenDemo,
  onFillLineup,
}: {
  project: Project;
  onOpenDemo: () => void;
  onFillLineup: () => void;
}) {
  const initials = (name: string) =>
    name
      .split(/\s+/)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase() ?? "")
      .join("");

  const isLesson = project.scenario === "education";

  if (project.musicians.length === 0) {
    return (
      <EmptyState
        title="Нечего адаптировать"
        reason={{ text: "состав не заполнен", kind: "attention" }}
        action={{ label: "Заполнить состав", run: onFillLineup }}
        onOpenDemo={onOpenDemo}
      >
        Директор подгоняет тональность, партии и сложность под конкретных людей: диапазон вокалиста, число струн
        баса, уровень каждого. Пока состава нет, он считает по среднему случаю.
      </EmptyState>
    );
  }

  return (
    <div className="lineup-list">
      {project.musicians.map((musician) => (
        <div key={musician.id} className="musician-row">
          <span className="musician-avatar" aria-hidden="true">
            {initials(musician.name)}
          </span>
          <div className="musician-body">
            <strong className="musician-name">
              {musician.name} · {musician.role}
            </strong>
            <span className="musician-instrument">{musician.instrumentNote}</span>
          </div>
          <span className="musician-constraint">{musician.constraint}</span>
          <span className="mono-chip">{musician.level}</span>
        </div>
      ))}
      {isLesson && <LessonLevels />}

      <p className="privacy-note">
        Состав заводится один раз и переиспользуется для каждой новой песни. Заведение руками появится вместе с
        хранением песен.
      </p>
    </div>
  );
}

/**
 * Уровень сложности как выдача, а не настройка. Одна песня превращается в
 * три учебных материала, и переключатель показывает, чем они отличаются,
 * а не абстрактную «сложность 3 из 5».
 */
function LessonLevels() {
  const [levelId, setLevelId] = useState(lessonLevels[1].id);
  const level = lessonLevels.find((item) => item.id === levelId) ?? lessonLevels[0];

  return (
    <section className="level-picker">
      <h3>Уровень сложности</h3>
      <div className="level-switch" role="radiogroup" aria-label="Уровень сложности">
        {lessonLevels.map((item) => (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={item.id === levelId}
            className={item.id === levelId ? "level-option active" : "level-option"}
            onClick={() => setLevelId(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="level-detail">
        <strong>{level.title}</strong>
        <p>{level.detail}</p>
        <div className="level-facts">
          {level.facts.map((fact) => (
            <span key={fact} className="mono-chip">
              {fact}
            </span>
          ))}
        </div>
      </div>
      <p className="privacy-note">
        Одна песня превращается в три учебных материала. Переключатель — часть выдачи ученику, а не настройка в
        глубине.
      </p>
    </section>
  );
}

function ConsolePanel({
  project,
  onAction,
}: {
  project: Project;
  onAction: (actionId: DirectorActionId) => void;
}) {
  const [activeSectionId, setActiveSectionId] = useState(project.analysis.sections[0]?.id ?? "");

  const sections = project.analysis.sections;
  const activeIndex = Math.max(sections.findIndex((section) => section.id === activeSectionId), 0);
  const playedShare = sections.length ? (activeIndex + 1) / sections.length : 0;

  // Столбики строим детерминированно от разбора, а не случайно: картинка
  // должна быть одинаковой между рендерами, иначе это шум, а не форма песни.
  const bars = Array.from({ length: 64 }, (_, index) => {
    const position = index / 64;
    const section = sections[Math.min(Math.floor(position * sections.length), sections.length - 1)];
    const weight = section && /припев|chorus|кульмин/i.test(section.label) ? 1 : 0.62;
    return 0.3 + weight * (0.4 + 0.3 * Math.abs(Math.sin(index * 1.7)));
  });

  const barToTime = (bar: number) => {
    const seconds = Math.round(((bar - 1) * 4 * 60) / Math.max(project.analysis.bpm, 1));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  };

  const commandForPart = (part: string): { label: string; actionId: DirectorActionId } => {
    const normalized = part.toLowerCase();

    // Ветка урока раньше искала только «вокал». В демо урока партии
    // называются «Мелодия», «Аккорды», «Гитара», «Бас» — вокала нет вовсе,
    // поэтому все четыре дорожки получали «усложнить», в том числе
    // «Аккорды», где команда не имеет смысла, а «разбор к уроку» не
    // доставался никому.
    if (project.scenario === "education") {
      if (normalized.includes("вокал") || normalized.includes("мелод")) {
        return { label: "разбор к уроку", actionId: "lesson-analysis" };
      }
      if (normalized.includes("аккорд")) {
        return { label: "учебная версия", actionId: "education-version" };
      }
      if (normalized.includes("бас")) {
        return { label: "упростить бас", actionId: "beginner-bass" };
      }
      if (normalized.includes("перкус") || normalized.includes("бараб")) {
        return { label: "на ансамбль", actionId: "student-ensemble" };
      }
      return { label: "усложнить", actionId: "advanced-student-part" };
    }
    if (normalized.includes("гитар")) return { label: "объединить", actionId: "merge-guitars" };
    if (normalized.includes("клав")) return { label: "взять струнные", actionId: "move-strings-to-keys" };
    if (normalized.includes("бараб")) return { label: "упростить", actionId: "simplify-drums" };
    if (normalized.includes("бас")) return { label: "трек без баса", actionId: "practice-without-bass" };
    return { label: "усилить припев", actionId: "boost-chorus" };
  };

  // Подпись определяется ролью партии, а не номером строки: при другом
  // порядке дорожек барабаны получали бы «поддержку», а бас — «ритм».
  const partNote = (part: string) => {
    const normalized = part.toLowerCase();
    if (normalized.includes("вокал")) return "аудиослой + MIDI";
    if (normalized.includes("гитар")) return project.scenario === "band" ? "ведущая партия" : "партия ученика";
    if (normalized.includes("клав")) return "без струнных оригинала";
    if (normalized.includes("бараб")) return "ритм";
    if (normalized.includes("бас")) return "сопровождение";
    return "сопровождение";
  };

  return (
    <section className="console-panel" aria-label="Пульт песни">
      <div className="console-transport">
        {/*
          Кнопка выключена, а не «работает вхолостую». Звука в продукте нет:
          нажатие, которое меняет только иконку, читается как обещание
          воспроизведения. Включается вместе с настоящим плеером.
        */}
        <button
          type="button"
          className="console-play"
          disabled
          aria-label="Проиграть — звука в прототипе нет"
          title="Звука нет: обработка не подключена"
        >
          <Play size={18} />
        </button>
        <div className="console-title">
          <strong>{project.analysis.title}</strong>
          <span className="console-facts">
            {project.analysis.bpm} BPM · {project.analysis.key} · {project.analysis.meter} ·{" "}
            {project.analysis.duration}
          </span>
        </div>
        {/*
          Чипы режимов из бренд-бука — клик, скорость, петля — сюда вернутся
          вместе с плеером. Пока их нет, три плашки описывали бы режимы
          воспроизведения, которого не существует.
        */}
        <div className="console-modes">
          <span className="mono-chip on-console">звук не подключен</span>
        </div>
      </div>

      <div className="console-wave" aria-hidden="true">
        {bars.map((height, index) => (
          <i
            key={index}
            className={index / bars.length <= playedShare ? "played" : undefined}
            style={{ height: `${Math.round(height * 100)}%` }}
          />
        ))}
      </div>

      <div className="console-sections" aria-label="Форма песни">
        {sections.map((section) => {
          const barsCount = section.endBar - section.startBar + 1;

          return (
            <button
              key={section.id}
              type="button"
              className={section.id === activeSectionId ? "console-section active" : "console-section"}
              style={{ flexGrow: barsCount }}
              aria-pressed={section.id === activeSectionId}
              onClick={() => setActiveSectionId(section.id)}
            >
              <strong>{section.label}</strong>
              <span>{barToTime(section.startBar)}</span>
            </button>
          );
        })}
      </div>

      <div className="console-tracks">
        {Object.entries(project.analysis.confidenceByPart).map(([part, value]) => {
          const command = commandForPart(part);
          const percent = Math.round(value * 100);

          return (
            <div key={part} className="console-track-row">
              <div className="track-name">
                <strong>{part}</strong>
                <span>{partNote(part)}</span>
              </div>
              <i className="track-confidence" aria-hidden="true">
                <b className={confidenceLevel(value)} style={{ width: `${percent}%` }} />
              </i>
              <span className={`track-percent ${confidenceLevel(value)}`} aria-label={`${part}: точность разбора ${percent}%`}>
                {percent}%
              </span>
              <div className="track-controls">
                {/*
                  Выключены по той же причине, что и воспроизведение: звука
                  нет, заглушать и солировать нечего. Нажатие, которое ничего
                  не меняет, — обещание микшера, а не микшер.
                */}
                <button type="button" disabled title="Звука нет: заглушать нечего" aria-label={`Заглушить ${part} — звука в прототипе нет`}>
                  M
                </button>
                <button type="button" disabled title="Звука нет: солировать нечего" aria-label={`Солировать ${part} — звука в прототипе нет`}>
                  S
                </button>
                <button type="button" className="track-command" onClick={() => onAction(command.actionId)}>
                  {command.label}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="console-chords" aria-label="Аккорды">
        {project.analysis.chords.slice(0, 8).map((chord, index) => (
          <span
            key={`${chord.bar}-${chord.beat}-${index}`}
            className={chord.confidence < mediumConfidenceThreshold ? "chord-chip uncertain" : "chord-chip"}
            title={`Такт ${chord.bar}, точность ${formatConfidence(chord.confidence)}`}
          >
            {chord.chord}
            {chord.confidence < mediumConfidenceThreshold && " ?"}
          </span>
        ))}
        <span className="console-hint">
          ? — аккорд под вопросом: точность ниже {Math.round(mediumConfidenceThreshold * 100)}%
        </span>
      </div>
    </section>
  );
}

function ArtifactPreview({ project, artifact }: { project: Project; artifact: Project["stagePack"]["artifacts"][number] }) {
  if (artifact.status === "pending") {
    return (
      <div className="empty-preview">
        <Clock3 size={22} />
        <span>Этого материала нет в демо-данных. В продукте он появится после обработки.</span>
      </div>
    );
  }

  if (artifact.preview.kind === "waveform") {
    return (
      <div className="waveform-preview">
        {artifact.preview.lines.map((line, index) => (
          <div key={line} className="wave-row">
            <span>{line}</span>
            <i style={{ width: `${64 + ((index * 13) % 30)}%` }} />
          </div>
        ))}
      </div>
    );
  }

  if (artifact.preview.kind === "midi") {
    return (
      <div className="piano-roll">
        {artifact.preview.lines.map((line, index) => (
          <div key={line} className="midi-row">
            <span>{line}</span>
            <i style={{ left: `${8 + index * 9}%`, width: `${24 + index * 4}%` }} />
          </div>
        ))}
      </div>
    );
  }

  if (artifact.preview.kind === "bundle") {
    return (
      <div className="bundle-preview">
        {artifact.preview.lines.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </div>
    );
  }

  return (
    <div className="mock-score">
      {project.analysis.sections.map((section) => (
        <div key={section.id} className="score-line">
          <strong>
            {section.label} · такты {section.startBar}-{section.endBar}
          </strong>
          <span>{section.note}</span>
        </div>
      ))}
      <div className="chord-strip" aria-label="Аккорды">
        {project.analysis.chords.map((chord) => (
          <span key={`${chord.bar}-${chord.chord}`}>
            {chord.bar}: {chord.chord}
          </span>
        ))}
      </div>
    </div>
  );
}
