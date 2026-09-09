import { describe, expect, it } from "vitest";
import { processingMilestones, processingStepIds } from "../domain/mockData";
import {
  applyDirectorAction,
  addSessionNote,
  createProjectFromDemo,
  createProjectFromUpload,
  createShareLinks,
  deleteProjectResults,
  deleteProjectSource,
  listDemoProjects,
  qualityForSize,
  rebuildExportBundle,
  rollbackToVersion,
  updateReviewIssue,
  validateUploadFile,
} from "./mockServices";

describe("mock services", () => {
  it("loads three demo projects", () => {
    expect(listDemoProjects()).toHaveLength(3);
  });

  it("creates a copied demo project with an upload and stage pack", () => {
    const project = createProjectFromDemo("band-demo");

    expect(project.name).toContain("репетиции");
    expect(project.stagePack.artifacts.length).toBeGreaterThan(6);
    expect(project.legalConsent.accepted).toBe(true);
  });

  it("creates an upload project with pending generated material", () => {
    const project = createProjectFromUpload({
      scenario: "education",
      goalId: "lesson-analysis",
      fileName: "lesson-song.mp3",
      acceptedConsent: true,
      setupSnapshot: {
        scenario: "education",
        title: "Учебная задача",
        fields: [
          { label: "Инструмент ученика", value: "фортепиано" },
          { label: "Уровень", value: "сильный" },
          { label: "Цель урока", value: "подготовить школьный концерт" },
          { label: "Сложность результата", value: "сложнее оригинала" },
          { label: "Кому выдать", value: "ансамблю и преподавателю" },
        ],
      },
    });

    expect(project.scenario).toBe("education");
    expect(project.upload.fileName).toBe("lesson-song.mp3");
    expect(project.studentProfile?.instrument).toBe("фортепиано");
    expect(project.studentProfile?.level).toBe("сильный");
    expect(project.lesson?.desiredDifficulty).toBe("сложнее оригинала");
    expect(project.setupSnapshot.fields.find((field) => field.label === "Цель урока")?.value).toBe(
      "подготовить школьный концерт",
    );
    expect(project.processing.steps.every((step) => step.status === "queued")).toBe(true);
  });

  it("understands Russian setup wording for keys covering layers", () => {
    const project = createProjectFromUpload({
      scenario: "band",
      goalId: "band-rehearsal",
      fileName: "band-song.wav",
      acceptedConsent: true,
      setupSnapshot: {
        scenario: "band",
        title: "Состав группы",
        fields: [
          { label: "Диапазон вокала", value: "A2-E4" },
          { label: "Гитаристов", value: "1" },
          { label: "Бас", value: "4 струны" },
          { label: "Клавиши", value: "да, закрывает слои" },
          { label: "Барабаны", value: "средний уровень" },
        ],
      },
    });

    expect(project.bandLineup?.keys).toBe(true);
    expect(project.bandLineup?.keysCanCoverLayers).toBe(true);
  });

  it("applies director action by creating a new version and history entry", () => {
    const project = createProjectFromDemo("band-demo");
    const updated = applyDirectorAction(project, "boost-chorus");

    expect(updated.versions).toHaveLength(project.versions.length + 1);
    expect(updated.currentVersionId).not.toBe(project.currentVersionId);
    expect(updated.changeLog[0].title).toContain("припев");
  });

  it("marks affected artifacts as stale after director action", () => {
    const project = createProjectFromDemo("band-demo");
    const updated = applyDirectorAction(project, "boost-chorus");

    expect(updated.stagePack.artifacts.find((artifact) => artifact.type === "score")?.isStale).toBe(true);
    expect(updated.stagePack.artifacts.find((artifact) => artifact.type === "zip")?.status).toBe("rebuild_required");
    expect(updated.exportBundles[0].status).toBe("stale");
  });

  it("updates review issue status", () => {
    const project = createProjectFromDemo("band-demo");
    const issue = project.reviewIssues[0];
    const updated = updateReviewIssue(project, issue.id, "checked");

    expect(updated.reviewIssues.find((item) => item.id === issue.id)?.status).toBe("checked");
  });

  it("creates mock share links for selected recipients", () => {
    const project = createProjectFromDemo("education-ensemble-demo");
    const updated = createShareLinks(project, ["student-1", "student-2"]);

    expect(updated.shareLinks).toHaveLength(2);
    expect(updated.shareRecipients.filter((recipient) => recipient.status === "issued")).toHaveLength(2);
    expect(updated.changeLog[0].title).toBe("Материалы выданы");
  });

  it("rebuilds stale export bundle and zip artifacts", () => {
    const project = applyDirectorAction(createProjectFromDemo("band-demo"), "boost-chorus");
    const rebuilt = rebuildExportBundle(project);

    expect(rebuilt.exportBundles[0].status).toBe("ready");
    expect(rebuilt.stagePack.artifacts.find((artifact) => artifact.type === "zip")?.status).toBe("ready");
    expect(rebuilt.stagePack.artifacts.find((artifact) => artifact.type === "zip")?.isStale).toBe(false);
  });

  it("tracks source and result deletion state", () => {
    const project = createProjectFromDemo("band-demo");
    const sourceDeleted = deleteProjectSource(project);
    const resultsDeleted = deleteProjectResults(sourceDeleted);

    expect(sourceDeleted.dataRetention.sourceDeleted).toBe(true);
    expect(resultsDeleted.dataRetention.resultsDeleted).toBe(true);
    expect(resultsDeleted.stagePack.artifacts.every((artifact) => artifact.status === "pending")).toBe(true);
  });

  it("adds a post session note as a new arrangement version", () => {
    const project = createProjectFromDemo("education-lesson-demo");
    const updated = addSessionNote(project, "Ученик легко сыграл припев, можно дать вариант сложнее.");

    expect(updated.versions[updated.versions.length - 1].kind).toBe("after-lesson");
    expect(updated.changeLog[0].title).toContain("После урока");
  });
});

describe("processing milestones", () => {
  it("covers every processing step exactly once", () => {
    const covered = processingMilestones.flatMap((milestone) => milestone.stepIds);

    expect([...covered].sort()).toEqual([...processingStepIds].sort());
  });

  it("references only real step ids", () => {
    for (const milestone of processingMilestones) {
      for (const stepId of milestone.stepIds) {
        expect(processingStepIds).toContain(stepId);
      }
    }
  });
});

describe("upload validation", () => {
  it("rejects an unsupported format", () => {
    expect(validateUploadFile({ name: "notes.txt", size: 1000 })).toContain("не поддерживается");
  });

  it("rejects a file over the size limit", () => {
    expect(validateUploadFile({ name: "song.wav", size: 80 * 1024 * 1024 })).toContain("больше");
  });

  it("accepts every supported format", () => {
    for (const name of ["song.mp3", "song.WAV", "song.flac", "song.m4a"]) {
      expect(validateUploadFile({ name, size: 5 * 1024 * 1024 })).toBeNull();
    }
  });

  it("marks a heavy source as low quality so processing can surface it", () => {
    expect(qualityForSize(5 * 1024 * 1024)).toBe("medium");
    expect(qualityForSize(30 * 1024 * 1024)).toBe("low");
  });
});

describe("cost estimate", () => {
  it("is attached to an uploaded project", () => {
    const project = createProjectFromUpload({
      scenario: "band",
      goalId: "band-rehearsal",
      fileName: "song.mp3",
      fileSizeBytes: 4_000_000,
      acceptedConsent: true,
    });

    expect(project.costEstimate.credits).toBeGreaterThan(0);
    expect(["low", "medium", "high"]).toContain(project.costEstimate.complexity);
    // Срока в оценке быть не должно: обработки нет, обещать нечего.
    expect(JSON.stringify(project.costEstimate)).not.toMatch(/минут|секунд|час/i);
  });
});

describe("version rollback", () => {
  it("restores the artifact state the version was left in", () => {
    const project = createProjectFromDemo("band-demo");
    const baseVersionId = project.currentVersionId;
    const scoreBefore = project.stagePack.artifacts.find((artifact) => artifact.type === "score");
    expect(scoreBefore?.isStale).toBe(false);

    const changed = applyDirectorAction(project, "boost-chorus");
    expect(changed.stagePack.artifacts.find((artifact) => artifact.type === "score")?.isStale).toBe(true);

    const rolledBack = rollbackToVersion(changed, baseVersionId);

    expect(rolledBack.currentVersionId).toBe(baseVersionId);
    expect(rolledBack.stagePack.versionId).toBe(baseVersionId);
    expect(rolledBack.stagePack.artifacts.find((artifact) => artifact.type === "score")?.isStale).toBe(false);
    expect(rolledBack.exportBundles.every((bundle) => bundle.status === "ready")).toBe(true);
    expect(rolledBack.changeLog[0].title).toContain("Откат");
  });

  it("ignores a rollback to the current or unknown version", () => {
    const project = createProjectFromDemo("band-demo");

    expect(rollbackToVersion(project, project.currentVersionId)).toBe(project);
    expect(rollbackToVersion(project, "no-such-version")).toBe(project);
  });
});

describe("review comments", () => {
  it("records a readable status change", () => {
    const project = createProjectFromDemo("band-demo");
    const issue = project.reviewIssues[0];
    const updated = updateReviewIssue(project, issue.id, "accepted_for_rehearsal");

    expect(updated.reviewComments[updated.reviewComments.length - 1].text).toContain("принято для репетиции");
  });
});
