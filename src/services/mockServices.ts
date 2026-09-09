import {
  createQueuedProcessing,
  demoProjects,
  directorActionResults,
  processingGoals,
} from "../domain/mockData";
import { formatDuration } from "./audioFile";
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
  SongAnalysis,
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

const extensionToFormat = (fileName: string): "MP3" | "WAV" | "FLAC" | "M4A" => {
  const extension = extensionOf(fileName);

  if (extension === "wav") return "WAV";
  if (extension === "flac") return "FLAC";
  if (extension === "m4a") return "M4A";
  return "MP3";
};

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
    notes: ["Оценка демонстрационная.", "Учтены цель обработки и настройки сценария."],
  };
};

const titleFromFileName = (fileName: string) => fileName.replace(/\.[^.]+$/, "") || fileName;

/**
 * Разбора у загруженного файла нет и подставлять чужой нельзя: пользователь
 * увидит тональность и аккорды другой песни. Пустой разбор честнее.
 */
const emptyAnalysis = (fileName: string, durationSeconds: number): SongAnalysis => ({
  source: "none",
  title: titleFromFileName(fileName),
  artist: "",
  bpm: 0,
  key: "",
  meter: "",
  duration: formatDuration(durationSeconds),
  genre: "",
  sections: [],
  chords: [],
  confidenceByPart: {},
  summary: "Звук не анализируется. Форма, аккорды и партии появятся с настоящей обработкой.",
});

export const createProjectFromUpload = (input: UploadProjectInput): Project => {
  const base = cloneProject(input.scenario === "band" ? demoProjects[0] : demoProjects[1]);
  const goal = getGoal(input.goalId);
  const facts = input.facts;
  // Разбор по подписям заменён типами: см. `ProjectSetup` в domain/types.ts.
  const bandSetup = input.setup?.kind === "band" ? input.setup : undefined;
  const lessonSetup = input.setup?.kind === "lesson" ? input.setup : undefined;

  return {
    ...base,
    id: `project-upload-${Date.now()}`,
    name: `${titleFromFileName(input.fileName)}: подготовка`,
    // Состав демо-группы на своем файле — та же подмена, что чужой разбор:
    // этих людей пользователь не заводил.
    musicians: [],
    scenario: input.scenario,
    processingGoal: goal,
    upload: {
      id: `upload-${Date.now()}`,
      fileName: input.fileName,
      format: extensionToFormat(input.fileName),
      durationSeconds: facts?.durationSeconds ?? 0,
      quality: facts?.quality ?? "medium",
      sourceNote: "Файл остается на устройстве и никуда не отправляется.",
      sizeBytes: facts?.sizeBytes,
      sampleRate: facts?.sampleRate,
      channels: facts?.channels,
    },
    analysis: emptyAnalysis(input.fileName, facts?.durationSeconds ?? 0),
    reviewIssues: [],
    reviewComments: [],
    stagePack: { ...base.stagePack, artifacts: [] },
    directorSuggestions: [],
    chat: [],
    assignments: [],
    // Получатели и пакеты приходили от демо-группы: на своем файле пользователь
    // видел чужих музыкантов по именам.
    shareRecipients: [],
    exportBundles: [],
    bandLineup:
      input.scenario === "band"
        ? {
            leadVocal: true,
            vocalRange: bandSetup?.vocalRange || base.bandLineup?.vocalRange || "A2-E4",
            guitars: bandSetup?.guitars || base.bandLineup?.guitars || 1,
            guitarTuning: base.bandLineup?.guitarTuning ?? "Standard E",
            capo: base.bandLineup?.capo ?? "нет",
            bass: (bandSetup?.bass ?? "4 струны").includes("5") ? "5 strings" : "4 strings",
            keys: (bandSetup?.keys ?? "да").toLowerCase() !== "нет",
            keysCanCoverLayers: /layer|сло/i.test(bandSetup?.keys ?? "слои"),
            drums: (bandSetup?.drums ?? "да").toLowerCase() !== "нет",
            backingVocals: base.bandLineup?.backingVocals ?? false,
            musicianLevel: base.bandLineup?.musicianLevel ?? "middle",
            targetStyle: bandSetup?.targetStyle || base.bandLineup?.targetStyle || "рабочая версия",
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
            instrument: lessonSetup?.instrument || base.studentProfile?.instrument || "гитара",
            level: (lessonSetup?.level ?? base.studentProfile?.level ?? "начальный").includes("силь")
              ? "сильный"
              : (lessonSetup?.level ?? base.studentProfile?.level ?? "начальный").includes("сред")
                ? "средний"
                : "начальный",
          }
        : undefined,
    lesson:
      input.scenario === "education"
        ? {
            goal: lessonSetup?.lessonGoal || base.lesson?.goal || "разобрать песню",
            homeworkFormat: base.lesson?.homeworkFormat ?? "ученику",
            desiredDifficulty: (lessonSetup?.difficulty ?? "проще оригинала").includes("слож")
              ? "сложнее оригинала"
              : (lessonSetup?.difficulty ?? "проще оригинала").includes("близ")
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
        changes: ["Проект создан из выбранного файла."],
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
        description: "Файл прочитан в браузере и остался на устройстве.",
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

/**
 * Применяет действие директора. `userCommand` — то, чем пользователь его
 * вызвал: команда попадает в переписку рядом с ответом, иначе разговор
 * получается односторонним и непонятно, на что директор отвечает.
 */
export const applyDirectorAction = (
  project: Project,
  actionId: DirectorActionId,
  userCommand?: string,
): Project => {
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
      ...(userCommand?.trim()
        ? [
            {
              id: `chat-${actionId}-${Date.now()}-user`,
              author: "user" as const,
              text: userCommand.trim(),
              createdAt: now(),
            },
          ]
        : []),
      {
        id: `chat-${actionId}-${Date.now()}`,
        author: "director" as const,
        text: `${result.historyTitle}. Я создал новую версию и отметил материалы, которые нужно проверить или пересобрать.`,
        createdAt: now(),
      },
    ],
  };
};

/**
 * Ответ директора на команду, которую он не разобрал. Пишет в переписку и
 * саму команду, и честный ответ: разбора языка в продукте нет, поэтому
 * выполнять непонятое как что-то похожее — значит врать о результате.
 */
/**
 * Собирает одну версию сразу из нескольких предложений директора.
 *
 * По одному предложению за раз получалось по версии на каждое: три правки —
 * три шага истории и три отката, хотя решение было одно. Бренд-бук ровно про
 * это: «Собрать версию v5 из двух вариантов».
 *
 * Снимок материалов покидаемой версии делается один раз и до правок —
 * иначе откат вернул бы уже изменённое состояние.
 */
export const applyDirectorActions = (
  project: Project,
  actionIds: DirectorActionId[],
  userCommand?: string,
): Project => {
  if (actionIds.length === 0) {
    return project;
  }
  if (actionIds.length === 1) {
    return applyDirectorAction(project, actionIds[0], userCommand);
  }

  const results = actionIds.map((actionId) => getDirectorActionResult(actionId));
  const currentVersion = project.versions.find((version) => version.id === project.currentVersionId);
  const versionId = `combined-${project.versions.length + 1}`;
  const changes = results.flatMap((result) => result.changes);
  const staleTypes = [...new Set(results.flatMap((result) => result.staleArtifactTypes))];
  const historyTitle = `Собрана версия из ${actionIds.length} предложений`;

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
        label: results[0].versionLabel,
        kind: results[0].versionKind,
        parentVersionId: currentVersion?.id,
        createdAt: now(),
        createdBy: "AI-директор",
        status: "needs_review" as const,
        changes,
      },
    ],
    stagePack: {
      ...project.stagePack,
      versionId,
      artifacts: project.stagePack.artifacts.map((artifact) => ({
        ...artifact,
        isStale: artifact.isStale || staleTypes.includes(artifact.type),
        status: markArtifact(artifact.status, staleTypes, artifact.type),
      })),
    },
    exportBundles: project.exportBundles.map((bundle) => ({
      ...bundle,
      status: staleTypes.includes("zip") ? ("stale" as const) : bundle.status,
    })),
    changeLog: [
      {
        id: `change-combined-${Date.now()}`,
        title: historyTitle,
        description: changes.join(" "),
        createdAt: now(),
        actor: "AI-директор",
      },
      ...project.changeLog,
    ],
    chat: [
      ...project.chat,
      ...(userCommand?.trim()
        ? [
            {
              id: `chat-combined-${Date.now()}-user`,
              author: "user" as const,
              text: userCommand.trim(),
              createdAt: now(),
            },
          ]
        : []),
      {
        id: `chat-combined-${Date.now()}-director`,
        author: "director" as const,
        text: `${historyTitle}. Правки сведены в один шаг: откатить их можно вместе, а не по очереди.`,
        createdAt: now(),
      },
    ],
  };
};

export const addUnderstoodNothingReply = (project: Project, userCommand: string): Project => ({
  ...project,
  chat: [
    ...project.chat,
    {
      id: `chat-unmatched-${Date.now()}-user`,
      author: "user" as const,
      text: userCommand,
      createdAt: now(),
    },
    {
      id: `chat-unmatched-${Date.now()}-director`,
      author: "director" as const,
      text:
        "Не разобрал команду. Пока понимаю только простые формулировки: транспонировать, " +
        "усилить припев, объединить гитары, упростить барабаны, собрать трек без баса, " +
        "перенести струнные на клавиши. Или выберите предложение карточкой выше.",
      createdAt: now(),
    },
  ],
});

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

/**
 * Свой комментарий к сомнительному месту. До этого в переписку по месту
 * попадали только автоматические записи о смене статуса: почему решили
 * именно так, записать было негде, и на репетиции это выяснялось заново.
 */
export const addReviewComment = (project: Project, issueId: string, text: string): Project => {
  const trimmed = text.trim();
  if (!trimmed) {
    return project;
  }

  return {
    ...project,
    reviewComments: [
      ...project.reviewComments,
      {
        id: `comment-own-${issueId}-${Date.now()}`,
        issueId,
        author: "Пользователь",
        text: trimmed,
        createdAt: now(),
      },
    ],
  };
};

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
        description: `Создано демо-ссылок: ${newLinks.length}.`,
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
    retentionNote: "Исходный файл удален. Результаты пока сохранены.",
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
