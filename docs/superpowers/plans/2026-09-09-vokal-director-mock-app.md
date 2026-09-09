# План реализации мокового приложения Vokal Director

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать русскоязычный кликабельный веб-прототип `Vokal Director` на моковых данных, который ведет пользователя от выбора сценария и загрузки песни до рабочего экрана `Stage Pack`.

**Architecture:** Vite + React + TypeScript, frontend-first. Доменные сущности, моковые данные и сервисы отделяются от экранных компонентов, чтобы позже заменить моки реальными backend/API-интеграциями без переписывания UI. Целевая продуктовая и AI/audio-архитектура описана в `docs/architecture.md`.

**Tech Stack:** Vite, React, TypeScript, Vitest, lucide-react, CSS modules-free single stylesheet with design tokens.

## Общие ограничения

- Интерфейс и рабочая продуктовая документация ведутся на русском.
- Приложение должно ощущаться как рабочий инструмент, а не как лендинг.
- Обработка аудио, ноты, stems, MIDI и ответы AI в первом инкременте моковые.
- Моковый слой должен использовать реальные доменные сущности.
- Не добавлять реальные аудиофайлы или партитуры, защищенные авторским правом.
- Не коммитить токены, пароли, ключи, строки подключения.
- Desktop-макет: слева материалы, в центре просмотр, справа AI-директор.
- Mobile-макет: вкладки `Материалы`, `Просмотр`, `AI-директор`.
- Не делать настоящую обработку аудио, MusicXML rendering, авторизацию, платежи, backend API, реальные скачивания, реальные AI-вызовы и настоящие ссылки общего доступа.

---

## Структура файлов

- Create: `package.json` — scripts, dependencies, QA commands.
- Create: `index.html` — Vite entry document.
- Create: `tsconfig.json` — TypeScript strict app configuration.
- Create: `tsconfig.node.json` — TypeScript config for Vite config.
- Create: `vite.config.ts` — Vite React build and Vitest environment.
- Create: `src/main.tsx` — React mount.
- Create: `src/App.tsx` — product flow, state orchestration, screens.
- Create: `src/styles.css` — design tokens, layout, responsive states.
- Create: `src/domain/types.ts` — product domain types from the spec.
- Create: `src/domain/mockData.ts` — demo projects, artifacts, warnings, versions, recipients.
- Create: `src/services/mockServices.ts` — mock processing, AI actions, review, versioning, sharing, legal and cost operations.
- Create: `src/services/mockServices.test.ts` — service behavior tests.
- Modify: `README.md` — explain local run, mock limitations, QA commands.
- Read: `docs/architecture.md` — target architecture, provider/model choices, and Vokal-owned model boundaries.

## Задача 1: Каркас приложения и инструменты

**Files:**
- Create: `package.json`
- Create: `index.html`
- Create: `tsconfig.json`
- Create: `tsconfig.node.json`
- Create: `vite.config.ts`
- Create: `src/main.tsx`
- Create: `src/App.tsx`
- Create: `src/styles.css`

**Interfaces:**
- Consumes: no product interfaces yet.
- Produces: Vite app mounted at `#root`, with `npm run dev`, `npm run typecheck`, `npm run build`, `npm run test`.

- [x] **Step 1: Add package scripts and dependencies**

Create `package.json`:

```json
{
  "name": "vokal-director",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "typecheck": "tsc --noEmit",
    "build": "tsc --noEmit && vite build",
    "test": "vitest"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^5.0.0",
    "lucide-react": "^0.468.0",
    "vite": "^6.0.0",
    "typescript": "^5.7.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "vitest": "^2.1.0"
  }
}
```

- [x] **Step 2: Add Vite and TypeScript configuration**

Create `index.html`:

```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta
      name="description"
      content="Vokal Director: моковый AI-директор для подготовки песен к репетиции и уроку"
    />
    <title>Vokal Director</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

Create `vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
  },
});
```

- [x] **Step 3: Add minimal mounted app**

Create `src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Create initial `src/App.tsx`:

```tsx
export default function App() {
  return (
    <main className="app-shell">
      <h1>Vokal Director</h1>
      <p>Моковый AI-директор для подготовки песни к репетиции или уроку.</p>
    </main>
  );
}
```

Create initial `src/styles.css`:

```css
:root {
  color: #18201d;
  background: #f4f1ea;
  font-family:
    Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI",
    sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
}

button,
input,
select,
textarea {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  padding: 32px;
}
```

- [x] **Step 4: Install dependencies**

Run: `npm install`

Expected: `package-lock.json` is created and dependencies are installed.

- [x] **Step 5: Verify scaffold**

Run: `npm run typecheck`

Expected: PASS with no TypeScript errors.

Run: `npm run build`

Expected: PASS and `dist/` is generated.

- [x] **Step 6: Commit scaffold**

```bash
git add package.json package-lock.json index.html tsconfig.json tsconfig.node.json vite.config.ts src/main.tsx src/App.tsx src/styles.css
git commit -m "feat: scaffold Vokal Director app"
```

## Задача 2: Доменная модель, моковые данные и сервисы

**Files:**
- Create: `src/domain/types.ts`
- Create: `src/domain/mockData.ts`
- Create: `src/services/mockServices.ts`
- Create: `src/services/mockServices.test.ts`
- Modify: `src/App.tsx`

**Interfaces:**
- Produces:
  - `type Scenario = "band" | "education"`
  - `type ProcessingGoal`
  - `interface Project`
  - `interface ArrangementVersion`
  - `interface Artifact`
  - `interface ReviewIssue`
  - `interface DirectorSuggestion`
  - `interface ShareRecipient`
  - `function listDemoProjects(): Project[]`
  - `function createProjectFromDemo(projectId: string): Project`
  - `function createProjectFromUpload(input: UploadProjectInput): Project`
  - `function applyDirectorAction(project: Project, actionId: string): Project`
  - `function updateReviewIssue(project: Project, issueId: string, status: ReviewStatus): Project`
  - `function createShareLinks(project: Project, recipientIds: string[]): Project`
- Consumes: no backend.

- [x] **Step 1: Write service tests first**

Create `src/services/mockServices.test.ts`:

```ts
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
```

- [x] **Step 2: Run tests to verify they fail**

Run: `npm run test -- --run src/services/mockServices.test.ts`

Expected: FAIL because `mockServices.ts` and domain types do not exist yet.

- [x] **Step 3: Add domain types**

Create `src/domain/types.ts` with explicit domain interfaces from the spec: project, upload, processing, song analysis, artifacts, versions, review, AI suggestions, recipients, export bundle, legal consent and cost estimate.

- [x] **Step 4: Add realistic mock data**

Create `src/domain/mockData.ts` with:

- `band-demo`
- `education-lesson-demo`
- `education-ensemble-demo`
- goals for `Для группы` and `Для обучения`
- processing steps
- warnings for low confidence, complex mix, nonlinear form
- artifact lists for score, parts, chord chart, lyrics, MIDI, stems, minus, click, rehearsal tracks
- recipients and share states

- [x] **Step 5: Add mock services**

Create `src/services/mockServices.ts` implementing project creation, director action, review update, share link creation and processing progress helpers as pure functions.

- [x] **Step 6: Run service tests**

Run: `npm run test -- --run src/services/mockServices.test.ts`

Expected: PASS.

- [x] **Step 7: Commit domain layer**

```bash
git add src/domain/types.ts src/domain/mockData.ts src/services/mockServices.ts src/services/mockServices.test.ts
git commit -m "feat: add Vokal mock domain services"
```

## Задача 3: Загрузка, настройка и обработка

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- Consumes:
  - `listDemoProjects()`
  - `createProjectFromDemo(projectId)`
  - `createProjectFromUpload(input)`
- Produces: interactive flow states `start`, `setup`, `processing`, `stagePack`; selected scenario, selected goal, consent, uploaded file name, processing steps.

- [x] **Step 1: Add product state to `App.tsx`**

Replace the scaffold component with a reducer-driven app that stores scenario, processing goal, file name, consent, current project, current screen, processing progress, selected artifact and mobile tab.

- [x] **Step 2: Build first working screen**

Add:

- top product bar with `Vokal Director`;
- segmented scenario control: `Для группы` / `Для обучения`;
- goal buttons;
- upload panel with file input for `MP3`, `WAV`, `FLAC`, `M4A`;
- `Открыть пример` actions for demo projects;
- consent checkbox;
- complexity estimate;
- recent projects.

- [x] **Step 3: Build setup screen**

For `Для группы`, show fields for vocal range, guitars, bass, keys, drums, backing vocals, target style and rehearsal date.

For `Для обучения`, show fields for student instrument, level, lesson goal, desired difficulty, number of parts, available class instruments, recipient format and homework materials.

- [x] **Step 4: Build processing screen**

Show queued/running/ready/warning/error states for processing steps. Use timers in React state to advance mock processing and route to `Stage Pack` when complete.

- [x] **Step 5: Verify flow manually**

Run: `npm run dev`

Expected:

- app opens on the working upload screen;
- scenario switch changes goals and setup fields;
- opening any demo starts processing;
- upload path requires consent before continue;
- processing advances through visible steps;
- app lands on `Stage Pack`.

- [x] **Step 6: Commit flow**

```bash
git add src/App.tsx src/styles.css
git commit -m "feat: add Vokal upload and processing flow"
```

## Задача 4: Рабочая область Stage Pack

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/styles.css`
- Modify: `src/services/mockServices.test.ts`

**Interfaces:**
- Consumes:
  - `Project`
  - `applyDirectorAction(project, actionId)`
  - `updateReviewIssue(project, issueId, status)`
  - `createShareLinks(project, recipientIds)`
- Produces: desktop three-pane workspace and mobile tabbed workspace.

- [x] **Step 1: Add tests for Stage Pack actions**

Extend `src/services/mockServices.test.ts` with expectations that AI actions mark artifacts as stale/rebuilt, review actions update issue status, and sharing actions create visible link records.

- [x] **Step 2: Build artifact list**

Show all `Stage Pack` artifacts grouped by type. Each row must include name, format, status, confidence and freshness state.

- [x] **Step 3: Build central preview**

For selected artifact types, show:

- notation as stylized bars and chord events;
- audio/stems as waveform strips;
- MIDI as piano-roll strips;
- ZIP/share materials as a file bundle list;
- empty state for material not ready.

- [x] **Step 4: Build AI-директор panel**

Show arrangement summary, issue cards, fast actions and chat command field. Fast actions must call `applyDirectorAction` and visibly update version, history and artifacts.

- [x] **Step 5: Build version, review, and sharing areas**

Show:

- version selector and current diff summary;
- suspicious bars with statuses `нужно проверить`, `проверено`, `исправлено`, `сомнительно`, `принято для репетиции`;
- recipients for group and school scenarios;
- buttons to issue selected mock links and rebuild ZIP.

- [x] **Step 6: Verify workspace manually**

Expected:

- user can switch artifacts;
- user can run at least five AI actions;
- user can create an advanced student version;
- user can strengthen chorus/concert ending;
- user can change suspicious bar status;
- user can issue mock links to recipients;
- all visible copy stays in Russian.

- [x] **Step 7: Commit workspace**

```bash
git add src/App.tsx src/styles.css src/services/mockServices.test.ts
git commit -m "feat: add Vokal Stage Pack workspace"
```

## Задача 5: Адаптивная полировка, документация и QA

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/styles.css`
- Modify: `README.md`

**Interfaces:**
- Consumes: complete app from Tasks 1-4.
- Produces: polished Russian prototype, updated README, passing QA, pushed GitHub branch.

- [x] **Step 1: Polish visual system**

Use a restrained professional palette that avoids one-note purple/blue SaaS defaults:

- paper background `#f4f1ea`;
- ink `#18201d`;
- pine `#1f4f45`;
- coral action `#c9563c`;
- brass accent `#b6842e`;
- blue-gray utility `#58717a`;
- neutral borders `#d8d0c2`.

- [x] **Step 2: Polish responsive behavior**

Desktop must keep three stable columns. Mobile must collapse into tabs `Материалы`, `Просмотр`, `AI-директор` without overlapping labels.

- [x] **Step 3: Update README**

Add:

- what Vokal Director is;
- how to run locally;
- QA commands;
- what is mocked;
- what future integrations replace.

- [x] **Step 4: Run full QA**

Run:

```bash
npm run typecheck
npm run test -- --run
npm run build
git diff --check
```

Expected: all pass.

- [x] **Step 5: Start local dev server**

Run: `npm run dev`

Expected: local URL is available, usually `http://127.0.0.1:5173/`.

- [x] **Step 6: Commit polish and docs**

```bash
git add src/App.tsx src/styles.css README.md
git commit -m "feat: polish Vokal Director prototype"
```

- [x] **Step 7: Push branch**

```bash
git push origin claude/music-instrument-skills-copy-s3580g
```

## Самопроверка

**Spec coverage:** Plan covers scenario switch, demo projects, setup, processing, `Stage Pack`, versions, AI actions, review statuses, instrument/education constraints, sharing, privacy consent, complexity estimate, Russian UI, responsive desktop/mobile, README mock explanation and QA.

**Draft marker scan:** Черновых маркеров и пустых шагов нет.

**Type consistency:** Type and function names used in Tasks 2-5 match the produced service interfaces.

**Scope note:** This plan intentionally keeps all work in one React app. Real audio processing, backend API, auth, payments, cloud storage, legal documents and real share links remain out of scope for this increment.

---

## Статус выполнения

План выполнен полностью; шаги отмечены. Отличия от плана, принятые по ходу работы:

- `vite.config.ts` импортирует `defineConfig` из `vitest/config` (не из `vite`) —
  иначе секция `test` не типизируется.
- `vitest` поднят до `^5.0.0`, добавлены `jsdom` и `@testing-library/react`
  для компонентных тестов.
- Мобильная раскладка `Stage Pack` собрана не из трёх вкладок, а из пяти
  (`Обзор`, `Материалы`, `Проверка`, `AI-директор`, `Экспорт`) с горизонтальной
  прокруткой: разделов стало больше, чем предполагал план.
- Пуш идёт в ветку `claude/repo-and-work-review-7vh4df`, а не в
  `claude/music-instrument-skills-copy-s3580g`, указанную в Задаче 5.
- Направление первого экрана изменено — см. раздел «Поправки» в спеке.
