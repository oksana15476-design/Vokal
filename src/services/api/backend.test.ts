/**
 * Тесты фасада `src/services/backend.ts`.
 *
 * Файл лежит в `api/`, а не рядом с фасадом, потому что этот батч правит
 * только `src/services/api/**` и сам `backend.ts`: заводить новый файл прямо
 * в `src/services/` значило бы залезть в чужую зону.
 */
import { describe, expect, it } from "vitest";
import { createBackend } from "../backend";
import { isNotImplemented } from "./errors";
import { fakeRuntime, jsonResponse, networkError, stubFetch } from "./testing";

const serverBackend = (fetchImpl: ReturnType<typeof stubFetch>) =>
  createBackend({ env: { VITE_API_BASE: "http://api.local/api" }, runtime: fakeRuntime(fetchImpl) });

const mockBackend = () => createBackend({ env: {} });

const wireProject = (over: Record<string, unknown> = {}) => ({
  id: "project-1",
  name: "Песня",
  scenario: "band",
  processingGoal: {
    id: "band-rehearsal",
    scenario: "band",
    label: "К репетиции",
    description: "",
    expectedOutputs: [],
  },
  upload: {
    id: "upload-1",
    fileName: "song.mp3",
    format: "MP3",
    state: "stored",
    durationSeconds: 210,
    quality: "good",
    sourceNote: "",
    sizeBytes: 5000,
    sampleRate: 44100,
    channels: 2,
    createdAt: "2026-09-10T10:00:00Z",
  },
  bandLineup: null,
  musicians: [
    {
      id: "m1",
      name: "Костя",
      role: "guitar",
      instrumentNote: "Telecaster",
      constraint: "без каподастра",
      level: "advanced",
    },
  ],
  studentProfile: null,
  teacherProfile: null,
  classGroup: null,
  lesson: null,
  assignments: [],
  versions: [
    {
      id: "v1",
      label: "Оригинал",
      kind: "original",
      parentVersionId: null,
      createdAt: "2026-09-10T10:00:00Z",
      createdBy: "Сервер",
      status: "draft",
      changes: [],
      artifactsSnapshot: null,
      isCurrent: true,
    },
  ],
  currentVersionId: "v1",
  processing: {
    id: "job-1",
    projectId: "project-1",
    status: "ready",
    steps: [],
    warnings: [],
    progressPercent: 100,
    errorCode: null,
    retryCount: 0,
    createdAt: null,
    updatedAt: null,
    pollAfterMs: null,
  },
  analysis: {
    source: "demo",
    title: "Песня",
    artist: "Группа",
    bpm: 120,
    key: "Am",
    meter: "4/4",
    duration: "3:30",
    genre: "rock",
    sections: [],
    chords: [],
    confidenceByPart: {},
    summary: "",
  },
  stagePack: { id: "pack-1", versionId: "v1", artifacts: [] },
  reviewIssues: [],
  reviewComments: [],
  directorSuggestions: [],
  chat: [],
  changeLog: [],
  shareRecipients: [],
  shareLinks: [
    {
      id: "link-1",
      recipientId: "r1",
      label: "Гитарист",
      url: "https://vokal/s/abc",
      status: "revoked",
      artifactIds: [],
      createdAt: "2026-09-10T10:00:00Z",
      expiresAt: null,
      revokedAt: "2026-09-10T11:00:00Z",
      openedAt: null,
    },
  ],
  exportBundles: [],
  costEstimate: { tier: "fast_draft", complexity: "medium", credits: 7, notes: [] },
  setupSnapshot: { scenario: "band", title: "Состав", fields: [] },
  legalConsent: { accepted: true, versionId: "consent-1", text: "текст", acceptedAt: null },
  dataRetention: {
    sourceDeleted: false,
    resultsDeleted: false,
    sourceState: "present",
    resultsState: "purge_requested",
    retentionNote: "Метаданные сохраняются.",
  },
  createdAt: "2026-09-10T10:00:00Z",
  updatedAt: "2026-09-10T10:00:00Z",
  lastOpenedAt: "2026-09-10T10:00:00Z",
  ...over,
});

const errorEnvelope = (code: string, message: string, details: unknown = null) => ({
  error: { code, message, requestId: "rid-1", details },
});

describe("выбор источника", () => {
  it("пустая переменная окружения означает моки", () => {
    const backend = mockBackend();
    expect(backend.mode).toBe("mock");
    expect(backend.baseUrl).toBeNull();
  });

  it("заданная переменная означает сервер", () => {
    const backend = serverBackend(stubFetch([jsonResponse({})]));
    expect(backend.mode).toBe("server");
    expect(backend.baseUrl).toBe("http://api.local/api");
  });
});

describe("моковый источник", () => {
  it("отдает демо-песни списком", async () => {
    const result = await mockBackend().listProjects();

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.length).toBeGreaterThan(0);
    expect(result.data[0].name.length).toBeGreaterThan(0);
  });

  it("открывает демо-песню по идентификатору", async () => {
    const backend = mockBackend();
    const list = await backend.listProjects();
    if (!list.ok) throw new Error("список не открылся");

    const result = await backend.getProject(list.data[0].id);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.project.id).toBe(list.data[0].id);
    // Моки не знают состояний хранилища и не делают вид, что знают.
    expect(result.data.extras.uploadState).toBeNull();
    expect(result.data.extras.sourceState).toBeNull();
  });

  it("оборачивает готовые правила директора, а не повторяет их", async () => {
    const backend = mockBackend();
    const list = await backend.listProjects();
    if (!list.ok) throw new Error("список не открылся");
    const before = await backend.getProject(list.data[0].id);
    if (!before.ok) throw new Error("песня не открылась");
    const versionsBefore = before.data.project.versions.length;

    const result = await backend.applyDirectorAction(list.data[0].id, "transpose-down-2");

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.project.versions.length).toBe(versionsBefore + 1);
    expect(result.data.project.changeLog[0].title.length).toBeGreaterThan(0);
  });

  it("не притворяется, что умеет загружать файл", async () => {
    const file = new Blob(["звук"]);
    const result = await mockBackend().uploadFile(new File([file], "song.mp3"));

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("unsupported");
    if (result.error.kind !== "unsupported") return;
    expect(result.error.missing.length).toBeGreaterThan(0);
  });

  it("не притворяется, что умеет обрабатывать звук", async () => {
    const result = await mockBackend().startProcessing("project-1");

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("unsupported");
  });

  it("удаление результатов в моках честно называет свое состояние", async () => {
    const backend = mockBackend();
    const list = await backend.listProjects();
    if (!list.ok) throw new Error("список не открылся");

    const result = await backend.deleteResults(list.data[0].id);

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.state).toBe("purged");
  });
});

describe("серверный источник", () => {
  it("переводит ключи контракта в подписи домена", async () => {
    const fetchImpl = stubFetch([jsonResponse(wireProject())]);

    const result = await serverBackend(fetchImpl).getProject("project-1");

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(fetchImpl.calls[0].url).toBe("http://api.local/api/projects/project-1");
    expect(result.data.project.musicians[0].role).toBe("гитара");
    expect(result.data.project.musicians[0].level).toBe("продвинутый");
  });

  it("не показывает отозванную ссылку как рабочую", async () => {
    const fetchImpl = stubFetch([jsonResponse(wireProject())]);

    const result = await serverBackend(fetchImpl).getProject("project-1");

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Доменный тип ссылок не умеет «отозвана», поэтому список пуст, а правда
    // лежит рядом, в extras.
    expect(result.data.project.shareLinks).toEqual([]);
    expect(result.data.extras.shareLinks?.[0].status).toBe("revoked");
  });

  it("различает «удаление выполняется» и «удалено»", async () => {
    const fetchImpl = stubFetch([jsonResponse(wireProject())]);

    const result = await serverBackend(fetchImpl).getProject("project-1");

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.project.dataRetention.resultsDeleted).toBe(false);
    expect(result.data.extras.resultsState).toBe("purge_requested");
  });

  it("501 доезжает до вызывающего как отказ «этого еще нет»", async () => {
    const fetchImpl = stubFetch([
      jsonResponse(
        errorEnvelope("not_implemented", "Проекты пока не сохраняются на сервере.", {
          endpoint: "GET /api/projects/project-1",
          missing: ["слой данных проекта"],
          docs: "docs/api/README.md",
        }),
        { status: 501 },
      ),
    ]);

    const result = await serverBackend(fetchImpl).getProject("project-1");

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(isNotImplemented(result.error)).toBe(true);
  });

  it("обрыв связи не превращается в пустую песню", async () => {
    const fetchImpl = stubFetch([networkError()]);

    const result = await serverBackend(fetchImpl).getProject("project-1");

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("network");
  });

  it("заметку после занятия честно отказывается сохранять: адреса нет в контракте", async () => {
    const result = await serverBackend(stubFetch([jsonResponse({})])).addSessionNote(
      "project-1",
      "разобрали припев",
    );

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("unsupported");
  });
});
