import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  FileAudio,
  FolderOpen,
  Gauge,
  GraduationCap,
  Music2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  Users,
} from "lucide-react";
import { processingGoals } from "./domain/mockData";
import type { ProcessingGoalId, ProcessingStep, Project, Scenario } from "./domain/types";
import { createProjectFromDemo, createProjectFromUpload, getGoalsForScenario, listDemoProjects } from "./services/mockServices";

type Screen = "start" | "setup" | "processing" | "stage-pack";
type MobileTab = "materials" | "preview" | "director";

const scenarioCopy: Record<Scenario, { label: string; description: string }> = {
  band: {
    label: "Для группы",
    description: "Подготовка кавера к репетиции или сцене: партии, stems, минус, клик и адаптация под состав.",
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
  const [mobileTab, setMobileTab] = useState<MobileTab>("preview");
  const [bandSettings, setBandSettings] = useState<Record<string, string>>({
    rehearsalDate: "через 5 дней",
    vocalRange: "A2-E4",
    guitars: "1",
    bass: "4 струны",
    keys: "да, закрывает layers",
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
  const selectedArtifact = project?.stagePack.artifacts.find((artifact) => artifact.id === selectedArtifactId);

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
        <nav className="topbar-nav" aria-label="Разделы продукта">
          <span>Stage Pack</span>
          <span>SongGraph</span>
          <span>Архитектура моков</span>
        </nav>
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
          selectedArtifactId={selectedArtifactId}
          selectedArtifactName={selectedArtifact?.name ?? "Материал"}
          mobileTab={mobileTab}
          setMobileTab={setMobileTab}
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
  return (
    <section className="start-grid">
      <div className="intro-panel">
        <p className="eyebrow">Рабочий прототип</p>
        <h1>Песня превращается в план репетиции, урока и выдачу материалов.</h1>
        <p className="intro-copy">
          Сейчас это моковый продукт без реальной обработки аудио. Но сущности уже такие, как в будущем backend:
          проект, версии, Stage Pack, сомнительные такты, AI-действия и раздача материалов.
        </p>

        <div className="scenario-switch" role="tablist" aria-label="Сценарий">
          {(["band", "education"] as const).map((item) => (
            <button
              key={item}
              type="button"
              className={item === scenario ? "segment active" : "segment"}
              onClick={() => setScenario(item)}
            >
              {item === "band" ? <Users size={18} /> : <GraduationCap size={18} />}
              <span>{scenarioCopy[item].label}</span>
            </button>
          ))}
        </div>

        <p className="scenario-note">{scenarioCopy[scenario].description}</p>

        <div className="goal-grid" aria-label="Цели обработки">
          {goals.map((goal) => (
            <button
              key={goal.id}
              type="button"
              className={goal.id === goalId ? "goal-card selected" : "goal-card"}
              onClick={() => setGoalId(goal.id)}
            >
              <strong>{goal.label}</strong>
              <span>{goal.description}</span>
            </button>
          ))}
        </div>
      </div>

      <aside className="upload-panel">
        <div className="panel-heading">
          <UploadCloud size={22} />
          <div>
            <h2>Загрузка</h2>
            <p>MP3, WAV, FLAC или M4A</p>
          </div>
        </div>

        <label className="drop-zone">
          <FileAudio size={30} />
          <span>{fileName || "Выберите файл для моковой обработки"}</span>
          <input
            type="file"
            accept=".mp3,.wav,.flac,.m4a,audio/*"
            onChange={(event) => setFileName(event.target.files?.[0]?.name ?? "")}
          />
        </label>

        <label className="consent-row">
          <input
            type="checkbox"
            checked={acceptedConsent}
            onChange={(event) => setAcceptedConsent(event.target.checked)}
          />
          <span>Я вправе обработать этот материал для приватной репетиции, урока или внутренней подготовки.</span>
        </label>

        <div className="estimate-list">
          <div>
            <Gauge size={18} />
            <span>Оценка обработки: 3-8 минут, 4-10 кредитов в будущем.</span>
          </div>
          <div>
            <ShieldCheck size={18} />
            <span>AI отметит сомнительные такты и не будет обещать идеальные ноты.</span>
          </div>
        </div>

        <button className="primary-action" type="button" disabled={!canContinueToSetup} onClick={onContinue}>
          <SlidersHorizontal size={18} />
          Настроить задачу
        </button>

        <div className="demo-list">
          <div className="section-title">
            <FolderOpen size={17} />
            <span>Открыть пример</span>
          </div>
          {demos.map((demo) => (
            <button key={demo.id} type="button" className="demo-row" onClick={() => onOpenDemo(demo.id)}>
              <span>{demo.name}</span>
              <small>{scenarioCopy[demo.scenario].label}</small>
            </button>
          ))}
        </div>
      </aside>
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
          Цель: <strong>{selectedGoalLabel}</strong>. Эти параметры позже станут входом для `ModelRouter`,
          `SongGraph` и правил аранжировки Vokal.
        </p>
      </div>

      <div className="form-grid">
        {fields.map(([key, label]) => (
          <label key={key} className="field">
            <span>{label}</span>
            <input value={values[key] ?? ""} onChange={(event) => setValues({ ...values, [key]: event.target.value })} />
          </label>
        ))}
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

      <button className="primary-action wide" type="button" onClick={onStart}>
        <Activity size={18} />
        Запустить подготовку
      </button>
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

        <div className="processing-warning">
          <AlertTriangle size={18} />
          <span>
            Качество зависит от исходника. В этом моковом режиме мы показываем будущую механику, а не выполняем
            настоящую аудиообработку.
          </span>
        </div>
      </div>
    </section>
  );
}

function StagePackShell({
  project,
  selectedArtifactName,
  mobileTab,
  setMobileTab,
  onBack,
}: {
  project: Project;
  selectedArtifactId: string | null;
  selectedArtifactName: string;
  mobileTab: MobileTab;
  setMobileTab: (tab: MobileTab) => void;
  onBack: () => void;
}) {
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const averageConfidence =
    Object.values(project.analysis.confidenceByPart).reduce((sum, value) => sum + value, 0) /
    Object.values(project.analysis.confidenceByPart).length;

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

      <div className="mobile-tabs" role="tablist" aria-label="Stage Pack">
        <button type="button" className={mobileTab === "materials" ? "active" : ""} onClick={() => setMobileTab("materials")}>
          Материалы
        </button>
        <button type="button" className={mobileTab === "preview" ? "active" : ""} onClick={() => setMobileTab("preview")}>
          Просмотр
        </button>
        <button type="button" className={mobileTab === "director" ? "active" : ""} onClick={() => setMobileTab("director")}>
          AI-директор
        </button>
      </div>

      <div className="stage-grid">
        <aside className={`stage-panel materials-pane ${mobileTab === "materials" ? "mobile-visible" : ""}`}>
          <h2>Материалы</h2>
          {project.stagePack.artifacts.map((artifact) => (
            <button key={artifact.id} type="button" className="artifact-row">
              <span>{artifact.name}</span>
              <small>
                {artifact.format} · {formatConfidence(artifact.confidence)}
              </small>
            </button>
          ))}
        </aside>

        <section className={`stage-panel preview-pane ${mobileTab === "preview" ? "mobile-visible" : ""}`}>
          <p className="eyebrow">Просмотр</p>
          <h2>{selectedArtifactName}</h2>
          <div className="mock-score">
            {project.analysis.sections.map((section) => (
              <div key={section.id} className="score-line">
                <strong>
                  {section.label} · такты {section.startBar}-{section.endBar}
                </strong>
                <span>{section.note}</span>
              </div>
            ))}
          </div>
        </section>

        <aside className={`stage-panel director-pane ${mobileTab === "director" ? "mobile-visible" : ""}`}>
          <div className="panel-heading">
            <Sparkles size={20} />
            <div>
              <h2>AI-директор</h2>
              <p>{project.analysis.summary}</p>
            </div>
          </div>
          {project.directorSuggestions.slice(0, 4).map((suggestion) => (
            <div key={suggestion.id} className="suggestion-card">
              <strong>{suggestion.title}</strong>
              <p>{suggestion.description}</p>
            </div>
          ))}
        </aside>
      </div>
    </section>
  );
}
