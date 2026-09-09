import { type Dispatch, type SetStateAction, useEffect, useMemo, useState } from "react";
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
import type { DirectorActionId, ProcessingGoalId, ProcessingStep, Project, ReviewStatus, Scenario } from "./domain/types";
import {
  applyDirectorAction,
  createProjectFromDemo,
  createProjectFromUpload,
  createShareLinks,
  getGoalsForScenario,
  listDemoProjects,
  updateReviewIssue,
} from "./services/mockServices";

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
          setProject={setProject}
          selectedArtifactId={selectedArtifactId}
          setSelectedArtifactId={setSelectedArtifactId}
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

function StagePackShell({
  project,
  setProject,
  selectedArtifactId,
  setSelectedArtifactId,
  mobileTab,
  setMobileTab,
  onBack,
}: {
  project: Project;
  setProject: Dispatch<SetStateAction<Project | null>>;
  selectedArtifactId: string | null;
  setSelectedArtifactId: (artifactId: string) => void;
  selectedArtifactName: string;
  mobileTab: MobileTab;
  setMobileTab: (tab: MobileTab) => void;
  onBack: () => void;
}) {
  const [selectedRecipients, setSelectedRecipients] = useState<string[]>(
    project.shareRecipients.filter((recipient) => recipient.status !== "opened").slice(0, 2).map((recipient) => recipient.id),
  );
  const [chatCommand, setChatCommand] = useState("");
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const selectedArtifact =
    project.stagePack.artifacts.find((artifact) => artifact.id === selectedArtifactId) ?? project.stagePack.artifacts[0];
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
          <div className="pane-title-row">
            <h2>Материалы</h2>
            <span>{project.stagePack.artifacts.length}</span>
          </div>
          {project.stagePack.artifacts.map((artifact) => (
            <button
              key={artifact.id}
              type="button"
              className={artifact.id === selectedArtifact.id ? "artifact-row active" : "artifact-row"}
              onClick={() => {
                setSelectedArtifactId(artifact.id);
                setMobileTab("preview");
              }}
            >
              <span>{artifact.name}</span>
              <small>
                {artifact.format} · {formatConfidence(artifact.confidence)} · {artifactStatusCopy[artifact.status]}
              </small>
              {artifact.isStale && <em>нужно пересобрать</em>}
            </button>
          ))}

          <div className="bundle-box">
            <strong>Пакеты</strong>
            {project.exportBundles.map((bundle) => (
              <span key={bundle.id}>
                {bundle.label}: {bundle.filesCount} файлов, {bundle.status === "ready" ? "готово" : "устарело"}
              </span>
            ))}
          </div>
        </aside>

        <section className={`stage-panel preview-pane ${mobileTab === "preview" ? "mobile-visible" : ""}`}>
          <div className="preview-header">
            <div>
              <p className="eyebrow">Просмотр</p>
              <h2>{selectedArtifact.name}</h2>
              <p>{selectedArtifact.description}</p>
            </div>
            <span className={`status-badge ${selectedArtifact.status}`}>{artifactStatusCopy[selectedArtifact.status]}</span>
          </div>

          <div className="song-facts">
            <span>{project.analysis.title}</span>
            <span>{project.analysis.key}</span>
            <span>{project.analysis.bpm} BPM</span>
            <span>{project.analysis.meter}</span>
            <span>{project.analysis.duration}</span>
          </div>

          <ArtifactPreview project={project} artifact={selectedArtifact} />

          <div className="workspace-columns">
            <section className="subpanel">
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

            <section className="subpanel">
              <h3>Сомнительные такты</h3>
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
            </section>
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
              <button type="button" onClick={() => runAction(suggestion.actionId)}>
                {actionLabel[suggestion.actionId]}
              </button>
            </div>
          ))}

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

          <div className="subpanel compact">
            <h3>Выдача материалов</h3>
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
                      {recipient.material} · {recipient.status === "issued" ? "выдано" : recipient.status === "opened" ? "открыто" : recipient.status === "needs_fix" ? "нужна правка" : "не выдано"}
                    </small>
                  </span>
                </label>
              ))}
            </div>
            <button className="secondary-action" type="button" onClick={issueLinks} disabled={selectedRecipients.length === 0}>
              Создать моковые ссылки
            </button>
            {project.shareLinks.length > 0 && (
              <div className="mock-links">
                {project.shareLinks.map((link) => (
                  <span key={link.id}>{link.label}</span>
                ))}
              </div>
            )}
          </div>

          <div className="subpanel compact">
            <h3>История</h3>
            {project.changeLog.slice(0, 4).map((entry) => (
              <div key={entry.id} className="history-row">
                <strong>{entry.title}</strong>
                <span>{entry.description}</span>
              </div>
            ))}
          </div>
        </aside>
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
