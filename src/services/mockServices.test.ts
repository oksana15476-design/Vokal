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
    });

    expect(project.scenario).toBe("education");
    expect(project.upload.fileName).toBe("lesson-song.mp3");
    expect(project.processing.steps.every((step) => step.status === "queued")).toBe(true);
  });

  it("applies director action by creating a new version and history entry", () => {
    const project = createProjectFromDemo("band-demo");
    const updated = applyDirectorAction(project, "boost-chorus");

    expect(updated.versions).toHaveLength(project.versions.length + 1);
    expect(updated.currentVersionId).not.toBe(project.currentVersionId);
    expect(updated.changeLog[0].title).toContain("припев");
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
  });
});
