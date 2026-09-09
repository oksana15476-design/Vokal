import { type Dispatch, type SetStateAction, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Download,
  FileAudio,
  FolderOpen,
  Layers3,
  ListChecks,
  LockKeyhole,
  Music2,
  Pause,
  Play,
  Repeat2,
  SlidersHorizontal,
  Sparkles,
  Share2,
  Volume2,
} from "lucide-react";
import { processingGoals } from "./domain/mockData";
import type { DirectorActionId, ProcessingGoalId, ProcessingStep, Project, ReviewStatus, Scenario } from "./domain/types";
import {
  applyDirectorAction,
  addSessionNote,
  createProjectFromDemo,
  createProjectFromUpload,
  createShareLinks,
  deleteProjectResults,
  deleteProjectSource,
  getGoalsForScenario,
  listDemoProjects,
  rebuildExportBundle,
  updateReviewIssue,
} from "./services/mockServices";

type Screen = "start" | "setup" | "processing" | "stage-pack";
type WorkspaceTab = "overview" | "materials" | "review" | "director" | "export";

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

const statusCopy: Record<ProcessingStep["status"], string> = {
  queued: "в очереди",
  running: "выполняется",
  done: "готово",
  warning: "предупреждение",
  error: "ошибка",
};

const workspaceTabs: Array<{ id: WorkspaceTab; label: string; hint: string }> = [
  { id: "overview", label: "Обзор", hint: "результат" },
  { id: "materials", label: "Материалы", hint: "что готово" },
  { id: "review", label: "Проверка", hint: "что проверить" },
  { id: "director", label: "AI-директор", hint: "изменить" },
  { id: "export", label: "Экспорт", hint: "выдать" },
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

const initialScenario: Scenario = "band";
const initialGoalId: ProcessingGoalId = "band-rehearsal";

const stepStatusForIndex = (stepIndex: number, activeIndex: number, stepId: string): ProcessingStep["status"] => {
  if (stepIndex < activeIndex) {
    return stepId === "structure" ? "warning" : "done";
  }

  if (stepIndex === activeIndex) {
    return "running";
  }

  return "queued";
};

function makeProcessingSteps(project: Project, activeIndex: number): ProcessingStep[] {
  return project.processing.steps.map((step, index) => ({
    ...step,
    status: stepStatusForIndex(index, activeIndex, step.id),
  }));
}

export default function App() {
  const [screen, setScreen] = useState<Screen>("start");
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [goalId, setGoalId] = useState<ProcessingGoalId>(initialGoalId);
  const [fileName, setFileName] = useState("");
  const [acceptedConsent, setAcceptedConsent] = useState(false);
  const [project, setProject] = useState<Project | null>(null);
  const [processingIndex, setProcessingIndex] = useState(0);
  const [processingSteps, setProcessingSteps] = useState<ProcessingStep[]>([]);
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

  useEffect(() => {
    if (screen !== "processing" || !project) {
      return;
    }

    setProcessingSteps(makeProcessingSteps(project, processingIndex));

    if (processingIndex >= project.processing.steps.length) {
      const timer = window.setTimeout(() => {
        setProject((current) =>
          current
            ? {
                ...current,
                processing: {
                  ...current.processing,
                  status: "ready",
                  progressPercent: 100,
                  steps: current.processing.steps.map((step) => ({
                    ...step,
                    status: step.id === "structure" ? "warning" : "done",
                  })),
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
  }, [screen, project, processingIndex]);

  const startProcessing = (nextProject: Project) => {
    setProject(nextProject);
    setProcessingIndex(0);
    setProcessingSteps(makeProcessingSteps(nextProject, 0));
    setWorkspaceTab("overview");
    setScreen("processing");
  };

  const openDemo = (demoId: string) => {
    const nextProject = createProjectFromDemo(demoId);
    setScenario(nextProject.scenario);
    setGoalId(nextProject.processingGoal.id);
    startProcessing(nextProject);
  };

  const startUploadProject = () => {
    const nextProject = createProjectFromUpload({
      scenario,
      goalId,
      fileName,
      acceptedConsent,
      setupSnapshot: {
        scenario,
        title: scenario === "band" ? "Состав группы" : "Учебная задача",
        fields: Object.entries(scenario === "band" ? bandSettings : lessonSettings).map(([key, value]) => ({
          label: setupLabelByKey[key] ?? key,
          value,
        })),
      },
    });
    startProcessing(nextProject);
  };

  const canContinueToSetup = fileName.trim().length > 0 && acceptedConsent;

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="brand-button" type="button" onClick={() => setScreen("start")} aria-label="На главный экран">
          <span className="brand-mark">
            <Music2 size={20} strokeWidth={2.2} />
          </span>
          <span>
            <strong>Vokal Director</strong>
            <small>моковый AI-директор</small>
          </span>
        </button>
        <div className="topbar-plan" aria-label="Доступ">
          <span>Free тест</span>
          <span>Pro экспорт</span>
        </div>
      </header>

      {screen === "start" && (
        <StartScreen
          scenario={scenario}
          setScenario={setScenario}
          goalId={goalId}
          setGoalId={setGoalId}
          goals={goals}
          fileName={fileName}
          setFileName={setFileName}
          acceptedConsent={acceptedConsent}
          setAcceptedConsent={setAcceptedConsent}
          canContinueToSetup={canContinueToSetup}
          onContinue={() => setScreen("setup")}
          demos={demos}
          onOpenDemo={openDemo}
        />
      )}

      {screen === "setup" && (
        <SetupScreen
          scenario={scenario}
          selectedGoalLabel={selectedGoal.label}
          goals={goals}
          goalId={goalId}
          setGoalId={setGoalId}
          bandSettings={bandSettings}
          setBandSettings={setBandSettings}
          lessonSettings={lessonSettings}
          setLessonSettings={setLessonSettings}
          onBack={() => setScreen("start")}
          onStart={startUploadProject}
        />
      )}

      {screen === "processing" && project && (
        <ProcessingScreen project={project} steps={processingSteps} activeIndex={processingIndex} />
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
        />
      )}
    </main>
  );
}

interface StartScreenProps {
  scenario: Scenario;
  setScenario: (scenario: Scenario) => void;
  goalId: ProcessingGoalId;
  setGoalId: (goalId: ProcessingGoalId) => void;
  goals: ReturnType<typeof getGoalsForScenario>;
  fileName: string;
  setFileName: (fileName: string) => void;
  acceptedConsent: boolean;
  setAcceptedConsent: (accepted: boolean) => void;
  canContinueToSetup: boolean;
  onContinue: () => void;
  demos: Project[];
  onOpenDemo: (demoId: string) => void;
}

function StartScreen({
  scenario,
  setScenario,
  goalId,
  setGoalId,
  goals,
  fileName,
  setFileName,
  acceptedConsent,
  setAcceptedConsent,
  canContinueToSetup,
  onContinue,
  demos,
  onOpenDemo,
}: StartScreenProps) {
  const recommendedDemo = demos.find((demo) => demo.scenario === scenario) ?? demos[0];
  const activeGoal = goals.find((goal) => goal.id === goalId) ?? goals[0];
  const expectedOutputs = activeGoal.expectedOutputs.slice(0, 4);
  const activeHomeJob =
    homeJobOptions.find((job) => job.goalId === goalId) ??
    homeJobOptions.find((job) => job.scenario === scenario) ??
    homeJobOptions[0];
  const jobText =
    scenario === "band"
      ? `Завтра репетиция: сделай ${activeGoal.label.toLowerCase()}, отметь слабые места и подготовь материалы музыкантам.`
      : `Подготовь урок: сделай ${activeGoal.label.toLowerCase()}, учти уровень ученика и собери домашку.`;
  const chooseHomeJob = (job: (typeof homeJobOptions)[number]) => {
    setScenario(job.scenario);
    setGoalId(job.goalId);
  };

  return (
    <section className="home-screen">
      <div className="home-hero">
        <section className="home-lead">
          <div>
            <p className="eyebrow">AI Stage Pack</p>
            <h1>Разберите песню на партии за несколько минут</h1>
            <p className="intro-copy">
              Загрузите трек: Vokal сделает форму, аккорды, партии, аудиослои, клик и список мест для проверки.
            </p>
          </div>
          <div className="hero-proof-row" aria-label="Что бесплатно видно сразу">
            <span>60 секунд бесплатно</span>
            <span>BPM и тональность</span>
            <span>форма и аккорды</span>
            <span>2 AI-подсказки</span>
          </div>
        </section>

        <section className="job-card hero-job-card" aria-label="Создать AI-задание">
          <div className="job-card-head">
            <span>1</span>
            <div>
              <h2>Загрузите песню</h2>
              <p>Выберите, что нужно получить. Детали состава, уровня ученика и экспорта уточним на следующем шаге.</p>
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

          <label className="drop-zone job-drop-zone">
            <FileAudio size={30} />
            <span>{fileName || "Добавьте MP3/WAV для бесплатного черновика"}</span>
            <input
              type="file"
              accept=".mp3,.wav,.flac,.m4a,audio/*"
              onChange={(event) => setFileName(event.target.files?.[0]?.name ?? "")}
            />
          </label>

          <label className="consent-row compact">
            <input
              type="checkbox"
              checked={acceptedConsent}
              onChange={(event) => setAcceptedConsent(event.target.checked)}
            />
            <span>Я вправе обработать этот материал для приватной репетиции, урока или внутренней подготовки.</span>
          </label>

          <div className="job-result-row" aria-label="Что получится">
            {expectedOutputs.map((output) => (
              <span key={output}>{output}</span>
            ))}
          </div>

          <button className="primary-action job-action" type="button" disabled={!canContinueToSetup} onClick={onContinue}>
            <SlidersHorizontal size={18} />
            Разобрать песню бесплатно
          </button>

          <div className="free-preview-note">
            <CheckCircle2 size={16} />
            <span>Без оплаты покажем черновой разбор. Полная песня, PDF/MIDI/WAV/ZIP и ссылки откроются в Pro.</span>
          </div>
        </section>

        <HomeResultPreview activeGoalLabel={activeGoal.label} expectedOutputs={expectedOutputs} scenario={scenario} />
      </div>

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
          <button className="primary-action" type="button" onClick={() => onOpenDemo(recommendedDemo.id)}>
            <ArrowRight size={18} />
            Открыть готовый разбор
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
        <span>После загрузки</span>
        <b>Free preview</b>
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
          AI нашел 2 места для проверки и предложил{" "}
          {scenario === "education" ? "версию сильнее для ученика" : "усилить припев"}.
        </span>
      </div>
    </aside>
  );
}

function AccessModel() {
  return (
    <section className="access-model" aria-label="Модель доступа">
      <article className="access-card free">
        <span>Бесплатно</span>
        <strong>Попробовать без оплаты</strong>
        <p>Демо-проекты, базовый разбор, форма песни, аккорды-превью и первые подсказки AI-директора.</p>
      </article>
      <article className="access-card trial">
        <span>Пробно</span>
        <strong>Один полный Stage Pack</strong>
        <p>Проверка ценности на своей песне: партии, сомнительные такты, моковый экспорт и сценарий выдачи.</p>
      </article>
      <article className="access-card pro">
        <span>Pro</span>
        <strong>Подписка для работы</strong>
        <p>ZIP, PDF, MIDI, WAV, версии после урока или репетиции, ссылки для учеников, группы и школы.</p>
      </article>
    </section>
  );
}

interface SetupScreenProps {
  scenario: Scenario;
  selectedGoalLabel: string;
  goals: ReturnType<typeof getGoalsForScenario>;
  goalId: ProcessingGoalId;
  setGoalId: (goalId: ProcessingGoalId) => void;
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
  goals,
  goalId,
  setGoalId,
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
          ["rehearsalDate", "Срок репетиции"],
          ["vocalRange", "Диапазон вокала"],
          ["guitars", "Гитаристов"],
          ["bass", "Бас"],
          ["keys", "Клавиши"],
          ["drums", "Барабаны"],
          ["targetStyle", "Стиль версии"],
        ]
      : [
          ["instrument", "Инструмент ученика"],
          ["level", "Уровень"],
          ["lessonGoal", "Цель урока"],
          ["difficulty", "Сложность результата"],
          ["partsCount", "Количество партий"],
          ["classInstruments", "Инструменты в классе"],
          ["recipientFormat", "Кому выдать"],
        ];

  const values = scenario === "band" ? bandSettings : lessonSettings;
  const setValues = scenario === "band" ? setBandSettings : setLessonSettings;
  const summaryFields = fields.slice(0, 5).map(([key, label]) => ({
    label,
    value: values[key] ?? "",
  }));

  return (
    <section className="setup-view">
      <button className="text-button" type="button" onClick={onBack}>
        <ArrowLeft size={17} />
        Назад к загрузке
      </button>

      <div className="setup-header">
        <p className="eyebrow">{scenarioCopy[scenario].label}</p>
        <h1>Настройка задачи</h1>
        <p>
          Цель: <strong>{selectedGoalLabel}</strong>. Уточните, кто будет играть или учиться, чтобы AI собрал
          полезный черновик, а не случайный набор файлов.
        </p>
      </div>

      <div className="setup-layout">
        <div className="settings-stack">
          <section className="settings-card">
            <div className="section-title">
              <Sparkles size={17} />
              <span>Job</span>
            </div>
            <div className="settings-goal-grid" aria-label="Что должен сделать AI">
              {goals.map((goal) => (
                <button
                  key={goal.id}
                  type="button"
                  className={goal.id === goalId ? "settings-goal selected" : "settings-goal"}
                  onClick={() => setGoalId(goal.id)}
                >
                  <strong>{goal.label}</strong>
                  <span>{goal.description}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="settings-card">
            <div className="section-title">
              <SlidersHorizontal size={17} />
              <span>{scenario === "band" ? "Состав" : "Урок"}</span>
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
            <span>Бриф обработки</span>
          </div>
          <h2>{selectedGoalLabel}</h2>
          <div className="brief-list">
            {summaryFields.map((field) => (
              <span key={field.label}>
                <b>{field.label}</b>
                {field.value}
              </span>
            ))}
          </div>
          <button className="primary-action" type="button" onClick={onStart}>
            <Activity size={18} />
            Запустить подготовку
          </button>
        </aside>
      </div>

      <div className="setup-notes">
        <div>
          <Sparkles size={18} />
          <span>
            {scenario === "band"
              ? "AI-директор проверит, где оригинальная аранжировка не совпадает с вашим составом."
              : "AI-директор учтет уровень ученика и сможет сделать версию проще, близко к оригиналу или сложнее."}
          </span>
        </div>
        <div>
          <AlertTriangle size={18} />
          <span>Автоматический разбор будет показан как черновик с местами для ручной проверки.</span>
        </div>
      </div>
    </section>
  );
}

function ProcessingScreen({ project, steps, activeIndex }: { project: Project; steps: ProcessingStep[]; activeIndex: number }) {
  const progress = Math.min(100, Math.round((activeIndex / project.processing.steps.length) * 100));

  return (
    <section className="processing-view">
      <div className="processing-card">
        <div className="panel-heading">
          <Activity size={24} />
          <div>
            <h1>Готовим Stage Pack</h1>
            <p>{project.name}</p>
          </div>
        </div>

        <div className="progress-track" aria-label={`Прогресс ${progress}%`}>
          <span style={{ width: `${progress}%` }} />
        </div>

        <div className="processing-steps">
          {steps.map((step) => (
            <div key={step.id} className={`step-row ${step.status}`}>
              <span className="step-icon">
                {step.status === "done" ? <CheckCircle2 size={18} /> : step.status === "warning" ? <AlertTriangle size={18} /> : <Clock3 size={18} />}
              </span>
              <div>
                <strong>{step.label}</strong>
                <p>{step.detail}</p>
              </div>
              <small>{statusCopy[step.status]}</small>
            </div>
          ))}
        </div>

        <div className="processing-summary">
          <div>
            <strong>Разбор песни</strong>
            <span>форма, тональность, BPM и аккорды</span>
          </div>
          <div>
            <strong>Материалы</strong>
            <span>партии, MIDI, минус и клик</span>
          </div>
          <div>
            <strong>Проверка</strong>
            <span>сомнительные такты отдельно</span>
          </div>
          <div>
            <strong>AI-директор</strong>
            <span>предложит, как усилить или упростить</span>
          </div>
        </div>
      </div>
    </section>
  );
}

const artifactStatusCopy = {
  ready: "готово",
  draft: "черновик",
  needs_review: "проверить",
  rebuild_required: "пересобрать",
  pending: "готовится",
} as const;

const reviewStatusCopy: Record<ReviewStatus, string> = {
  needs_review: "нужно проверить",
  checked: "проверено",
  fixed: "исправлено",
  uncertain: "сомнительно",
  accepted_for_rehearsal: "принято для репетиции",
};

const actionLabel: Record<DirectorActionId, string> = {
  "transpose-down-2": "Транспонировать",
  "merge-guitars": "Объединить гитары",
  "move-strings-to-keys": "На клавиши",
  "simplify-drums": "Упростить",
  "beginner-bass": "Бас easy",
  "boost-chorus": "Усилить",
  "practice-without-bass": "Трек без баса",
  "education-version": "Учебная версия",
  "advanced-student-part": "Advanced",
  "student-ensemble": "Ансамбль",
  "lesson-analysis": "Разбор урока",
};

const complexityCopy = {
  low: "низкая сложность",
  medium: "средняя сложность",
  high: "высокая сложность",
} as const;

const freeArtifactTypes = new Set(["score", "chords", "lyrics", "teacher", "student"]);

const hasFreePreview = (artifact: Project["stagePack"]["artifacts"][number]) => freeArtifactTypes.has(artifact.type);

function StagePackShell({
  project,
  setProject,
  selectedArtifactId,
  setSelectedArtifactId,
  workspaceTab,
  setWorkspaceTab,
  onBack,
}: {
  project: Project;
  setProject: Dispatch<SetStateAction<Project | null>>;
  selectedArtifactId: string | null;
  setSelectedArtifactId: (artifactId: string) => void;
  workspaceTab: WorkspaceTab;
  setWorkspaceTab: (tab: WorkspaceTab) => void;
  onBack: () => void;
}) {
  const [selectedRecipients, setSelectedRecipients] = useState<string[]>(
    project.shareRecipients.filter((recipient) => recipient.status !== "opened").slice(0, 2).map((recipient) => recipient.id),
  );
  const [chatCommand, setChatCommand] = useState("");
  const [sessionNote, setSessionNote] = useState(
    project.scenario === "education"
      ? "Ученик уверенно сыграл припев. Следующую версию можно сделать выразительнее."
      : "На репетиции припев просел по энергии. Нужна более плотная концертная версия.",
  );
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const selectedArtifact =
    project.stagePack.artifacts.find((artifact) => artifact.id === selectedArtifactId) ?? project.stagePack.artifacts[0];
  const readyArtifacts = project.stagePack.artifacts.filter((artifact) => artifact.status === "ready").length;
  const reviewCount = project.reviewIssues.filter(
    (issue) => issue.status === "needs_review" || issue.status === "uncertain",
  ).length;
  const issuedCount = project.shareRecipients.filter(
    (recipient) => recipient.status === "issued" || recipient.status === "opened",
  ).length;
  const hasStaleBundle = project.exportBundles.some((bundle) => bundle.status !== "ready");
  const averageConfidence =
    Object.values(project.analysis.confidenceByPart).reduce((sum, value) => sum + value, 0) /
    Object.values(project.analysis.confidenceByPart).length;
  const selectedVersionChanges = currentVersion?.changes ?? [];

  const runAction = (actionId: DirectorActionId) => {
    setProject((current) => (current ? applyDirectorAction(current, actionId) : current));
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

  const submitChat = () => {
    const command = chatCommand.toLowerCase();
    const action: DirectorActionId =
      project.scenario === "education" && (command.includes("слож") || command.includes("advanced"))
        ? "advanced-student-part"
        : project.scenario === "education" && command.includes("ансамб")
          ? "student-ensemble"
          : command.includes("трансп")
            ? "transpose-down-2"
            : "boost-chorus";
    runAction(action);
    setChatCommand("");
  };

  return (
    <section className="stage-shell">
      <div className="stage-toolbar">
        <button className="text-button" type="button" onClick={onBack}>
          <ArrowLeft size={17} />
          Новый проект
        </button>
        <div>
          <h1>{project.name}</h1>
          <p>
            {project.analysis.key}, {project.analysis.bpm} BPM, {project.analysis.meter}, точность{" "}
            {formatConfidence(averageConfidence)}
          </p>
        </div>
        <span className="version-pill">{currentVersion?.label ?? "Версия"}</span>
      </div>

      <div className="stage-command-strip" aria-label="Состояние проекта">
        <div className="command-metric">
          <Layers3 size={18} />
          <span>
            <strong>{readyArtifacts}/{project.stagePack.artifacts.length}</strong>
            материалов готовы
          </span>
        </div>
        <div className="command-metric">
          <AlertTriangle size={18} />
          <span>
            <strong>{reviewCount}</strong>
            мест требуют проверки
          </span>
        </div>
        <div className="command-metric">
          <Share2 size={18} />
          <span>
            <strong>{issuedCount}/{project.shareRecipients.length}</strong>
            получателей с материалами
          </span>
        </div>
        <button className={hasStaleBundle ? "command-action urgent" : "command-action"} type="button" onClick={() => setWorkspaceTab("export")}>
          <Download size={18} />
          {hasStaleBundle ? "Экспорт: пересобрать" : "Открыть экспорт"}
        </button>
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
                <p className="eyebrow">Готовый черновик</p>
                <h2>{project.analysis.title}</h2>
                <p>{project.analysis.summary}</p>
              </div>
              <span className="status-badge ready">бесплатный обзор</span>
            </div>

            <div className="song-facts">
              <span>{project.analysis.artist}</span>
              <span>{project.analysis.key}</span>
              <span>{project.analysis.bpm} BPM</span>
              <span>{project.analysis.meter}</span>
              <span>{project.analysis.duration}</span>
            </div>

            <SectionTimeline project={project} />
            <TransportBar project={project} />
            <StudioTrackStack project={project} onAction={runAction} />
            <ConfidenceMixer project={project} />
          </div>

          <aside className="overview-next">
            <div className="access-summary">
              <span>
                <b>Бесплатно</b>
                обзор песни, форма, аккорды-превью и AI-подсказки
              </span>
              <span>
                <b>Pro</b>
                полный Stage Pack, экспорт, версии и ссылки
              </span>
            </div>

            <section className="subpanel compact">
              <h3>Что делать дальше</h3>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("materials")}>
                Посмотреть материалы
              </button>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("review")}>
                Проверить сомнительные такты
              </button>
              <button className="secondary-action" type="button" onClick={() => setWorkspaceTab("director")}>
                Попросить AI улучшить версию
              </button>
            </section>

            <section className="subpanel compact">
              <h3>AI предлагает</h3>
              {project.directorSuggestions.slice(0, 2).map((suggestion) => (
                <button key={suggestion.id} className="suggestion-row" type="button" onClick={() => runAction(suggestion.actionId)}>
                  <span>{suggestion.title}</span>
                  <small>{actionLabel[suggestion.actionId]}</small>
                </button>
              ))}
            </section>
          </aside>
        </section>
      )}

      {workspaceTab === "materials" && (
        <section id="workspace-materials" className="stage-panel stage-view materials-view" role="tabpanel">
          <aside className="material-list-pane">
            <div className="pane-title-row">
              <h2>Материалы</h2>
              <span>{project.stagePack.artifacts.length}</span>
            </div>
            {project.stagePack.artifacts.map((artifact) => (
              <button
                key={artifact.id}
                type="button"
                className={artifact.id === selectedArtifact.id ? "artifact-row active" : "artifact-row"}
                onClick={() => setSelectedArtifactId(artifact.id)}
              >
                <span>{artifact.name}</span>
                <small>
                  {artifact.format} · {formatConfidence(artifact.confidence)} · {artifactStatusCopy[artifact.status]}
                </small>
                <span className={hasFreePreview(artifact) ? "access-label free" : "access-label pro"}>
                  {hasFreePreview(artifact) ? "бесплатно" : "подписка"}
                </span>
                {artifact.isStale && <em>нужно пересобрать</em>}
              </button>
            ))}
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

            {!hasFreePreview(selectedArtifact) && (
              <div className="pro-note">
                <LockKeyhole size={18} />
                <span>Просмотр доступен в моках, скачивание и выдача этого материала относятся к подписке.</span>
              </div>
            )}

            <ArtifactPreview project={project} artifact={selectedArtifact} />

            <div className="bundle-box">
              <strong>Пакеты экспорта</strong>
              {project.exportBundles.map((bundle) => (
                <span key={bundle.id}>
                  {bundle.label}: {bundle.filesCount} файлов, {bundle.status === "ready" ? "готово" : "устарело"}
                </span>
              ))}
            </div>
          </div>
        </section>
      )}

      {workspaceTab === "review" && (
        <section id="workspace-review" className="stage-panel stage-view review-view" role="tabpanel">
          <div className="review-main">
            <div className="preview-header">
              <div>
                <p className="eyebrow">Человеческая проверка</p>
                <h2>Сомнительные такты</h2>
                <p>AI не притворяется идеальным: спорные места вынесены отдельно, чтобы их быстро принять или исправить.</p>
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
                  <div className="review-actions">
                    {(["checked", "fixed", "accepted_for_rehearsal"] as const).map((status) => (
                      <button key={status} type="button" onClick={() => changeReviewStatus(issue.id, status)}>
                        {reviewStatusCopy[status]}
                      </button>
                    ))}
                  </div>
                  <small>
                    {issue.part} · {formatConfidence(issue.confidence)} · {reviewStatusCopy[issue.status]}
                  </small>
                </div>
              ))}
            </div>
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

            <div className="suggestions-grid">
              {project.directorSuggestions.slice(0, 4).map((suggestion) => (
                <div key={suggestion.id} className="suggestion-card">
                  <strong>{suggestion.title}</strong>
                  <p>{suggestion.description}</p>
                  <button type="button" onClick={() => runAction(suggestion.actionId)}>
                    {actionLabel[suggestion.actionId]}
                  </button>
                </div>
              ))}
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
              <button className="primary-action" type="button" onClick={submitChat} disabled={!chatCommand.trim()}>
                <Sparkles size={18} />
                Применить как мок
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
                    onClick={() =>
                      setProject((current) => (current ? { ...current, currentVersionId: version.id } : current))
                    }
                  >
                    <span>{version.label}</span>
                    <small>{version.status === "needs_review" ? "нужна проверка" : "черновик"}</small>
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
            <div className="plan-banner" aria-label="Бесплатные и платные функции">
              <div>
                <Sparkles size={18} />
                <span>
                  <strong>Бесплатно:</strong> демо, базовый разбор, форма, аккорды-превью и AI-подсказки.
                </span>
              </div>
              <div>
                <LockKeyhole size={18} />
                <span>
                  <strong>Подписка:</strong> экспорт ZIP/PDF/MIDI/WAV, ссылки, версии и командная выдача.
                </span>
              </div>
            </div>

            <section className="subpanel compact">
              <h3>Кому выдать материалы</h3>
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
              <button className="secondary-action pro-action" type="button" onClick={issueLinks} disabled={selectedRecipients.length === 0}>
                <LockKeyhole size={14} />
                Создать ссылки по подписке
              </button>
              <button className="secondary-action pro-action" type="button" onClick={rebuildBundle}>
                <LockKeyhole size={14} />
                Пересобрать ZIP и треки
              </button>
              {project.shareLinks.length > 0 && (
                <div className="mock-links">
                  {project.shareLinks.map((link) => (
                    <span key={link.id}>{link.label}</span>
                  ))}
                </div>
              )}
            </section>
          </div>

          <aside className="export-side">
            <div className="bundle-box">
              <strong>Пакеты</strong>
              {project.exportBundles.map((bundle) => (
                <span key={bundle.id}>
                  {bundle.label}: {bundle.filesCount} файлов, {bundle.status === "ready" ? "готово" : "устарело"}
                </span>
              ))}
            </div>

            <section className="subpanel compact">
              <h3>Настройки обработки</h3>
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
              <h3>Приватность</h3>
              <p className="privacy-note">{project.legalConsent.text}</p>
              <div className="retention-grid">
                <span>Исходник: {project.dataRetention.sourceDeleted ? "удален" : "сохранен"}</span>
                <span>Результаты: {project.dataRetention.resultsDeleted ? "удалены" : "сохранены"}</span>
              </div>
              <button className="secondary-action" type="button" onClick={deleteSource} disabled={project.dataRetention.sourceDeleted}>
                Удалить исходник
              </button>
              <button className="secondary-action danger" type="button" onClick={deleteResults} disabled={project.dataRetention.resultsDeleted}>
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

function SectionTimeline({ project }: { project: Project }) {
  const totalBars = Math.max(...project.analysis.sections.map((section) => section.endBar), 1);

  return (
    <div className="section-timeline" aria-label="Форма песни">
      {project.analysis.sections.map((section) => {
        const barsCount = section.endBar - section.startBar + 1;

        return (
          <div key={section.id} className="section-segment" style={{ flexGrow: barsCount }}>
            <strong>{section.label}</strong>
            <span>
              {section.startBar}-{section.endBar} / {totalBars}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function TransportBar({ project }: { project: Project }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const loopSection = project.scenario === "education" ? "куплет + припев" : "припев 2";

  return (
    <div className="transport-bar" aria-label="Прослушивание мока">
      <button className="transport-button" type="button" onClick={() => setIsPlaying((value) => !value)}>
        {isPlaying ? <Pause size={18} /> : <Play size={18} />}
        <span>{isPlaying ? "Пауза" : "Прослушать мок"}</span>
      </button>
      <div className="transport-metrics">
        <span>{project.analysis.bpm} BPM</span>
        <span>{project.analysis.key}</span>
        <span>{project.analysis.meter}</span>
        <span>
          <Repeat2 size={15} />
          {loopSection}
        </span>
      </div>
    </div>
  );
}

function StudioTrackStack({
  project,
  onAction,
}: {
  project: Project;
  onAction: (actionId: DirectorActionId) => void;
}) {
  const entries = Object.entries(project.analysis.confidenceByPart);
  const commandForPart = (part: string): { label: string; actionId: DirectorActionId } => {
    const normalized = part.toLowerCase();

    if (project.scenario === "education") {
      return normalized.includes("вокал")
        ? { label: "разбор урока", actionId: "lesson-analysis" }
        : { label: "под ученика", actionId: "advanced-student-part" };
    }

    if (normalized.includes("гитар")) {
      return { label: "объединить", actionId: "merge-guitars" };
    }

    if (normalized.includes("клав")) {
      return { label: "на клавиши", actionId: "move-strings-to-keys" };
    }

    if (normalized.includes("бараб")) {
      return { label: "упростить", actionId: "simplify-drums" };
    }

    if (normalized.includes("бас")) {
      return { label: "трек без баса", actionId: "practice-without-bass" };
    }

    return { label: "усилить", actionId: "boost-chorus" };
  };

  return (
    <section className="studio-track-stack" aria-label="Рабочие дорожки">
      <div className="studio-head">
        <div>
          <Layers3 size={18} />
          <strong>Рабочие дорожки</strong>
        </div>
        <span>{project.scenario === "education" ? "уровни и роли учеников" : "слои для репетиции и сцены"}</span>
      </div>
      <div className="studio-track-list">
        {entries.map(([part, value], index) => {
          const command = commandForPart(part);

          return (
            <div key={part} className="studio-track-row">
              <div className="track-name">
                <strong>{part}</strong>
                <span>{index === 0 ? "ведущий слой" : index === 1 ? "ритм" : "поддержка"}</span>
              </div>
              <i className="track-confidence">
                <b style={{ width: `${Math.round(value * 100)}%` }} />
              </i>
              <div className="track-controls">
                <button type="button" title={`Solo: ${part}`} aria-label={`Solo: ${part}`}>
                  S
                </button>
                <button type="button" title={`Mute: ${part}`} aria-label={`Mute: ${part}`}>
                  M
                </button>
                <button type="button" onClick={() => onAction(command.actionId)}>
                  {command.label}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ConfidenceMixer({ project }: { project: Project }) {
  const entries = Object.entries(project.analysis.confidenceByPart);

  return (
    <section className="confidence-mixer" aria-label="Уверенность по партиям">
      <div className="mixer-head">
        <div>
          <Volume2 size={18} />
          <strong>Партии и аудиослои</strong>
        </div>
        <span>видно, что можно выдавать, а что слушать руками</span>
      </div>
      <div className="mixer-grid">
        {entries.map(([part, value]) => (
          <div key={part} className="mixer-channel">
            <span>{part}</span>
            <i>
              <b style={{ width: `${Math.round(value * 100)}%` }} />
            </i>
            <small>{formatConfidence(value)}</small>
          </div>
        ))}
      </div>
    </section>
  );
}

function ArtifactPreview({ project, artifact }: { project: Project; artifact: Project["stagePack"]["artifacts"][number] }) {
  if (artifact.status === "pending") {
    return (
      <div className="empty-preview">
        <Clock3 size={22} />
        <span>Материал еще готовится. После обработки он появится в Stage Pack.</span>
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
