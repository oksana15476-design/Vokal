import { describe, expect, it } from "vitest";
import {
  applyDirectorAction,
  createProjectFromDemo,
  createProjectFromUpload,
  createShareLinks,
  listDemoProjects,
  updateReviewIssue,
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
});
