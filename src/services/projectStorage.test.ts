// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { forgetProject, listStoredProjects, loadProject, removeStoredProject, saveProject } from "./projectStorage";
import { createProjectFromDemo, listDemoProjects } from "./mockServices";

const demoId = () => listDemoProjects()[0].id.replace("project-", "");

describe("хранилище песен", () => {
  beforeEach(() => window.localStorage.clear());

  it("держит несколько песен, а не последнюю", () => {
    const first = createProjectFromDemo("band-demo");
    const second = createProjectFromDemo("education-lesson-demo");

    saveProject(first, "2026-09-09T10:00:00Z");
    saveProject(second, "2026-09-09T11:00:00Z");

    const stored = listStoredProjects();
    expect(stored.map((item) => item.project.id)).toContain(first.id);
    expect(stored.map((item) => item.project.id)).toContain(second.id);
  });

  it("показывает недавно открытую первой", () => {
    const first = createProjectFromDemo("band-demo");
    const second = createProjectFromDemo("education-lesson-demo");

    saveProject(first, "2026-09-09T10:00:00Z");
    saveProject(second, "2026-09-09T11:00:00Z");
    saveProject(first, "2026-09-09T12:00:00Z");

    expect(listStoredProjects()[0].project.id).toBe(first.id);
  });

  it("обновляет песню на месте, а не заводит вторую копию", () => {
    const project = createProjectFromDemo("band-demo");
    saveProject(project, "2026-09-09T10:00:00Z");
    saveProject({ ...project, name: "Другое имя" }, "2026-09-09T11:00:00Z");

    const stored = listStoredProjects().filter((item) => item.project.id === project.id);
    expect(stored).toHaveLength(1);
    expect(stored[0].project.name).toBe("Другое имя");
  });

  it("удаляет одну песню, не трогая остальные", () => {
    const first = createProjectFromDemo("band-demo");
    const second = createProjectFromDemo("education-lesson-demo");
    saveProject(first, "2026-09-09T10:00:00Z");
    saveProject(second, "2026-09-09T11:00:00Z");

    removeStoredProject(first.id);

    const ids = listStoredProjects().map((item) => item.project.id);
    expect(ids).not.toContain(first.id);
    expect(ids).toContain(second.id);
  });

  it("возвращает последнюю открытую как текущую", () => {
    const first = createProjectFromDemo("band-demo");
    const second = createProjectFromDemo("education-lesson-demo");
    saveProject(first, "2026-09-09T10:00:00Z");
    saveProject(second, "2026-09-09T11:00:00Z");

    expect(loadProject()?.id).toBe(second.id);
  });

  it("не падает на испорченном хранилище", () => {
    window.localStorage.setItem("vokal.projects.v2", "{это не json");
    expect(listStoredProjects()).toEqual([]);
    expect(loadProject()).toBeNull();
  });

  it("забывает все по forgetProject", () => {
    saveProject(createProjectFromDemo("band-demo"), "2026-09-09T10:00:00Z");
    forgetProject();
    expect(listStoredProjects()).toEqual([]);
  });

  it("не растет без предела", () => {
    for (let i = 0; i < 30; i++) {
      const project = createProjectFromDemo("band-demo");
      saveProject({ ...project, id: `project-${i}` }, `2026-09-09T10:${String(i).padStart(2, "0")}:00Z`);
    }
    // Хранилище браузера конечно: без предела запись однажды падает по квоте,
    // и пользователь теряет текущую работу из-за старых песен.
    expect(listStoredProjects().length).toBeLessThanOrEqual(20);
    expect(demoId()).toBeTruthy();
  });
});
