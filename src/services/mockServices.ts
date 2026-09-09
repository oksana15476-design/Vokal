import {
  createQueuedProcessing,
  demoProjects,
  directorActionResults,
  processingGoals,
} from "../domain/mockData";
import type {
  ArtifactStatus,
  ArtifactType,
  DirectorActionId,
  CostEstimate,
  ProcessingGoalId,
  Project,
  ReviewStatus,
  Scenario,
  SetupSnapshot,
  Upload,
  UploadProjectInput,
} from "../domain/types";

const now = () => new Date().toISOString();

const reviewStatusLabels: Record<ReviewStatus, string> = {
  needs_review: "нужно проверить",
  checked: "проверено",
  fixed: "исправлено",
  uncertain: "сомнительно",
  accepted_for_rehearsal: "принято для репетиции",
};

const cloneProject = (project: Project): Project => JSON.parse(JSON.stringify(project)) as Project;

export const listDemoProjects = (): Project[] => demoProjects.map(cloneProject);

export const getGoalsForScenario = (scenario: Scenario) =>
  processingGoals.filter((goal) => goal.scenario === scenario);

const getGoal = (goalId: ProcessingGoalId) => {
  const goal = processingGoals.find((item) => item.id === goalId);
  if (!goal) {
    throw new Error(`Unknown processing goal: ${goalId}`);
  }

  return goal;
};

export const createProjectFromDemo = (projectId: string): Project => {
  const project = demoProjects.find((item) => item.id === projectId);
  if (!project) {
    throw new Error(`Unknown demo project: ${projectId}`);
  }

  const copy = cloneProject(project);
  copy.id = `${project.id}-copy-${Date.now()}`;
  return copy;
};

export const supportedUploadExtensions = ["mp3", "wav", "flac", "m4a"] as const;
export const maxUploadBytes = 50 * 1024 * 1024;
export const lowQualityUploadBytes = 20 * 1024 * 1024;

const extensionOf = (fileName: string) => fileName.split(".").pop()?.toLowerCase() ?? "";

export const validateUploadFile = (file: { name: string; size: number }): string | null => {
  const extension = extensionOf(file.name);

  if (!supportedUploadExtensions.includes(extension as (typeof supportedUploadExtensions)[number])) {
    return `Формат .${extension || "?"} не поддерживается. Подойдут MP3, WAV, FLAC или M4A.`;
  }

  if (file.size > maxUploadBytes) {
    return `Файл больше ${Math.round(maxUploadBytes / 1024 / 1024)} МБ. Для прототипа возьмите файл покороче.`;
  }

  return null;
};

export const qualityForSize = (sizeBytes: number): Upload["quality"] =>
  sizeBytes >= lowQualityUploadBytes ? "low" : "medium";

const extensionToFormat = (fileName: string): "MP3" | "WAV" | "FLAC" | "M4A" => {
  const extension = extensionOf(fileName);

  if (extension === "wav") return "WAV";
  if (extension === "flac") return "FLAC";
  if (extension === "m4a") return "M4A";
  return "MP3";
};

const getSetupValue = (snapshot: SetupSnapshot | undefined, label: string, fallback: string) =>
  snapshot?.fields.find((field) => field.label === label)?.value || fallback;

const estimateFromSetup = (scenario: Scenario, snapshot: SetupSnapshot | undefined): CostEstimate => {
  const highComplexitySignals = ["сложнее", "ансамб", "концерт", "плотнее", "сцен"];
  const setupText = snapshot?.fields.map((field) => field.value.toLowerCase()).join(" ") ?? "";
  const complexity: CostEstimate["complexity"] = highComplexitySignals.some((signal) => setupText.includes(signal))
    ? "high"
    : scenario === "education"
      ? "low"
      : "medium";

  return {
    tier: complexity === "high" ? "multi_version" : "fast_draft",
    complexity,
    credits: complexity === "high" ? 10 : complexity === "medium" ? 7 : 4,
    runtime: complexity === "high" ? "8-12 минут" : complexity === "medium" ? "5-7 минут" : "3-5 минут",
    notes: ["Оценка демонстрационная.", "Учтены цель обработки и настройки сценария."],
  };
};

export const createProjectFromUpload = (input: UploadProjectInput): Project => {
  const base = cloneProject(input.scenario === "band" ? demoProjects[0] : demoProjects[1]);
  const goal = getGoal(input.goalId);

  return {
    ...base,
    id: `project-upload-${Date.now()}`,
    name: `${input.fileName}: моковая подготовка`,
    scenario: input.scenario,
    processingGoal: goal,
    upload: {
      id: `upload-${Date.now()}`,
      fileName: input.fileName,
      format: extensionToFormat(input.fileName),
      durationSeconds: 214,
      quality: qualityForSize(input.fileSizeBytes ?? 0),
      sourceNote: "Локальная моковая запись: файл не отправлен на сервер.",
    },
    bandLineup:
      input.scenario === "band"
        ? {
            leadVocal: true,
            vocalRange: getSetupValue(input.setupSnapshot, "Диапазон вокала", base.bandLineup?.vocalRange ?? "A2-E4"),
            guitars: Number.parseInt(getSetupValue(input.setupSnapshot, "Гитаристов", String(base.bandLineup?.guitars ?? 1)), 10) || 1,
            guitarTuning: base.bandLineup?.guitarTuning ?? "Standard E",
            capo: base.bandLineup?.capo ?? "нет",
            bass: getSetupValue(input.setupSnapshot, "Бас", "4 струны").includes("5") ? "5 strings" : "4 strings",
            keys: getSetupValue(input.setupSnapshot, "Клавиши", "да").toLowerCase() !== "нет",
            keysCanCoverLayers: /layer|сло/i.test(getSetupValue(input.setupSnapshot, "Клавиши", "слои")),
            drums: getSetupValue(input.setupSnapshot, "Барабаны", "да").toLowerCase() !== "нет",
            backingVocals: base.bandLineup?.backingVocals ?? false,
            musicianLevel: base.bandLineup?.musicianLevel ?? "middle",
            targetStyle: getSetupValue(input.setupSnapshot, "Стиль версии", base.bandLineup?.targetStyle ?? "рабочая версия"),
          }
        : undefined,
    studentProfile:
      input.scenario === "education"
        ? {
            ...(base.studentProfile ?? {
              name: "Ученик",
              instrument: "гитара",
              level: "начальный",
              ageGroup: "10-12",
              notationReading: "простые ноты",
              chordKnowledge: "базовые аккорды",
              homeInstrument: "домашний инструмент",
            }),
            instrument: getSetupValue(input.setupSnapshot, "Инструмент ученика", base.studentProfile?.instrument ?? "гитара"),
            level: getSetupValue(input.setupSnapshot, "Уровень", base.studentProfile?.level ?? "начальный").includes("силь")
              ? "сильный"
              : getSetupValue(input.setupSnapshot, "Уровень", base.studentProfile?.level ?? "начальный").includes("сред")
                ? "средний"
                : "начальный",
          }
        : undefined,
    lesson:
      input.scenario === "education"
        ? {
            goal: getSetupValue(input.setupSnapshot, "Цель урока", base.lesson?.goal ?? "разобрать песню"),
            homeworkFormat: getSetupValue(input.setupSnapshot, "Кому выдать", base.lesson?.homeworkFormat ?? "ученику"),
            desiredDifficulty: getSetupValue(input.setupSnapshot, "Сложность результата", "проще оригинала").includes("слож")
              ? "сложнее оригинала"
              : getSetupValue(input.setupSnapshot, "Сложность результата", "проще оригинала").includes("близ")
                ? "близко к оригиналу"
                : "проще оригинала",
          }
        : undefined,
    versions: [
      {
        id: "uploaded-draft",
        label: "Черновик",
        kind: input.scenario === "band" ? "band" : "easy",
        createdAt: now(),
        createdBy: "Пользователь",
        status: "draft",
        changes: ["Создан моковый проект из выбранного файла."],
      },
    ],
    currentVersionId: "uploaded-draft",
    processing: createQueuedProcessing(`job-upload-${Date.now()}`),
    costEstimate: estimateFromSetup(input.scenario, input.setupSnapshot),
    setupSnapshot:
      input.setupSnapshot ?? {
        scenario: input.scenario,
        title: input.scenario === "band" ? "Состав группы" : "Учебная задача",
        fields: [],
      },
    legalConsent: {
      accepted: input.acceptedConsent,
      text: "Материал используется для приватной репетиции, урока или внутренней подготовки.",
      acceptedAt: input.acceptedConsent ? now() : undefined,
    },
    changeLog: [
      {
        id: `change-upload-${Date.now()}`,
        title: "Создан проект из файла",
        description: "Файл сохранен как моковая запись без реальной загрузки.",
        createdAt: now(),
        actor: "Пользователь",
      },
    ],
    shareLinks: [],
  };
};

export const getDirectorActionResult = (actionId: DirectorActionId) => {
  const result = directorActionResults[actionId];
  if (!result) {
    throw new Error(`Unknown director action: ${actionId}`);
  }

  return result;
};

const markArtifact = (
  status: ArtifactStatus,
  staleTypes: ArtifactType[],
  artifactType: ArtifactType,
): ArtifactStatus => {
  if (!staleTypes.includes(artifactType)) {
    return status;
  }

  if (artifactType === "practice" || artifactType === "zip") {
    return "rebuild_required";
  }

  return "needs_review";
};

export const applyDirectorAction = (project: Project, actionId: DirectorActionId): Project => {
  const result = getDirectorActionResult(actionId);
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const versionId = `${actionId}-${project.versions.length + 1}`;

  return {
    ...project,
    currentVersionId: versionId,
    versions: [
      ...project.versions.map((version) =>
        version.id === project.currentVersionId && !version.artifactsSnapshot
          ? { ...version, artifactsSnapshot: project.stagePack.artifacts.map((artifact) => ({ ...artifact })) }
          : version,
      ),
      {
        id: versionId,
        label: result.versionLabel,
        kind: result.versionKind,
        parentVersionId: currentVersion?.id,
        createdAt: now(),
        createdBy: "AI-директор",
        status: "needs_review",
        changes: result.changes,
      },
    ],
    stagePack: {
      ...project.stagePack,
      versionId,
      artifacts: project.stagePack.artifacts.map((artifact) => ({
        ...artifact,
        isStale: artifact.isStale || result.staleArtifactTypes.includes(artifact.type),
        status: markArtifact(artifact.status, result.staleArtifactTypes, artifact.type),
      })),
    },
    exportBundles: project.exportBundles.map((bundle) => ({
      ...bundle,
      status: result.staleArtifactTypes.includes("zip") ? "stale" : bundle.status,
    })),
    changeLog: [
      {
        id: `change-${actionId}-${Date.now()}`,
        title: result.historyTitle,
        description: result.changes.join(" "),
        createdAt: now(),
        actor: "AI-директор",
      },
      ...project.changeLog,
    ],
    chat: [
      ...project.chat,
      {
        id: `chat-${actionId}-${Date.now()}`,
        author: "director",
        text: `${result.historyTitle}. Я создал новую версию и отметил материалы, которые нужно проверить или пересобрать.`,
        createdAt: now(),
      },
    ],
  };
};

export const rollbackToVersion = (project: Project, versionId: string): Project => {
  const target = project.versions.find((version) => version.id === versionId);
  if (!target || versionId === project.currentVersionId) {
    return project;
  }

  const restoredArtifacts = target.artifactsSnapshot ?? project.stagePack.artifacts;
  const hasStale = restoredArtifacts.some((artifact) => artifact.isStale);

  return {
    ...project,
    currentVersionId: versionId,
    stagePack: {
      ...project.stagePack,
      versionId,
      artifacts: restoredArtifacts.map((artifact) => ({ ...artifact })),
    },
    exportBundles: project.exportBundles.map((bundle) => ({
      ...bundle,
      status: hasStale ? "stale" : "ready",
    })),
    changeLog: [
      {
        id: `change-rollback-${versionId}-${Date.now()}`,
        title: `Откат к версии «${target.label}»`,
        description: target.artifactsSnapshot
          ? "Материалы вернулись к состоянию этой версии."
          : "Для этой версии снимок материалов не сохранялся, показан текущий набор.",
        createdAt: now(),
        actor: "Пользователь",
      },
      ...project.changeLog,
    ],
  };
};

export const updateReviewIssue = (project: Project, issueId: string, status: ReviewStatus): Project => ({
  ...project,
  reviewIssues: project.reviewIssues.map((issue) =>
    issue.id === issueId
      ? {
          ...issue,
          status,
        }
      : issue,
  ),
  reviewComments: [
    ...project.reviewComments,
    {
      id: `comment-${issueId}-${Date.now()}`,
      issueId,
      author: "Пользователь",
      text: `Статус изменен на «${reviewStatusLabels[status]}».`,
      createdAt: now(),
    },
  ],
});

export const createShareLinks = (project: Project, recipientIds: string[]): Project => {
  const newLinks = recipientIds.map((recipientId) => {
    const recipient = project.shareRecipients.find((item) => item.id === recipientId);

    return {
      id: `share-${recipientId}-${Date.now()}`,
      recipientId,
      label: recipient ? `${recipient.name}: ${recipient.material}` : recipientId,
      url: `https://vokal.local/mock-share/${project.id}/${recipientId}`,
      status: "mock_created" as const,
    };
  });

  return {
    ...project,
    shareRecipients: project.shareRecipients.map((recipient) =>
      recipientIds.includes(recipient.id) ? { ...recipient, status: "issued" } : recipient,
    ),
    shareLinks: [...project.shareLinks.filter((link) => !recipientIds.includes(link.recipientId)), ...newLinks],
    changeLog: [
      {
        id: `change-share-${Date.now()}`,
        title: "Материалы выданы",
        description: `Созданы моковые ссылки: ${newLinks.length}.`,
        createdAt: now(),
        actor: "Пользователь",
      },
      ...project.changeLog,
    ],
  };
};

export const rebuildExportBundle = (project: Project): Project => ({
  ...project,
  stagePack: {
    ...project.stagePack,
    artifacts: project.stagePack.artifacts.map((artifact) =>
      artifact.type === "zip" || artifact.type === "practice"
        ? {
            ...artifact,
            isStale: false,
            status: "ready",
          }
        : artifact,
    ),
  },
  exportBundles: project.exportBundles.map((bundle) => ({
    ...bundle,
    status: "ready",
  })),
  changeLog: [
    {
      id: `change-rebuild-${Date.now()}`,
      title: "Пакет материалов пересобран",
      description: "ZIP и репетиционные треки снова отмечены как актуальные.",
      createdAt: now(),
      actor: "Пользователь",
    },
    ...project.changeLog,
  ],
});

export const deleteProjectSource = (project: Project): Project => ({
  ...project,
  dataRetention: {
    ...project.dataRetention,
    sourceDeleted: true,
    retentionNote: "Исходный файл удален из мокового проекта. Результаты пока сохранены.",
  },
  changeLog: [
    {
      id: `change-delete-source-${Date.now()}`,
      title: "Исходник удален",
      description: "Моковый исходный файл помечен как удаленный.",
      createdAt: now(),
      actor: "Пользователь",
    },
    ...project.changeLog,
  ],
});

export const deleteProjectResults = (project: Project): Project => ({
  ...project,
  dataRetention: {
    ...project.dataRetention,
    resultsDeleted: true,
    retentionNote: "Исходник и результаты помечены как удаленные.",
  },
  stagePack: {
    ...project.stagePack,
    artifacts: project.stagePack.artifacts.map((artifact) => ({
      ...artifact,
      status: "pending",
      isStale: true,
    })),
  },
  exportBundles: project.exportBundles.map((bundle) => ({
    ...bundle,
    status: "pending",
  })),
  shareLinks: project.shareLinks.map((link) => ({
    ...link,
    status: "stale",
  })),
  changeLog: [
    {
      id: `change-delete-results-${Date.now()}`,
      title: "Результаты удалены",
      description: "Материалы Stage Pack и ссылки помечены как недоступные.",
      createdAt: now(),
      actor: "Пользователь",
    },
    ...project.changeLog,
  ],
});

export const addSessionNote = (project: Project, note: string): Project => {
  const kind = project.scenario === "education" ? "after-lesson" : "after-rehearsal";
  const label = project.scenario === "education" ? "После урока" : "После репетиции";
  const versionId = `${kind}-${project.versions.length + 1}`;

  return {
    ...project,
    currentVersionId: versionId,
    versions: [
      ...project.versions,
      {
        id: versionId,
        label,
        kind,
        parentVersionId: project.currentVersionId,
        createdAt: now(),
        createdBy: "Пользователь",
        status: "draft",
        changes: [note, "Следующая версия должна учитывать живую обратную связь."],
      },
    ],
    changeLog: [
      {
        id: `change-session-note-${Date.now()}`,
        title: `${label}: добавлена заметка`,
        description: note,
        createdAt: now(),
        actor: "Пользователь",
      },
      ...project.changeLog,
    ],
  };
};
