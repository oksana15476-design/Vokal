import type { Project } from "../domain/types";

/**
 * Хранилище песен между перезагрузками (B6, B94).
 *
 * Локальное и только локальное: `localStorage` браузера, а не облако. Песни
 * не уходят с устройства, не синхронизируются между браузерами и исчезают
 * вместе с очисткой данных сайта. Интерфейс не должен обещать иного, пока
 * нет backend, — строка об этом занесена в реестр обязательных раскрытий.
 *
 * Схема версионирована. Сохранение, сделанное другой версией приложения,
 * выбрасывается целиком: восстановленный наполовину проект хуже, чем
 * отсутствующий, — он выглядит рабочим и врет в деталях.
 */
const STORAGE_KEY = "vokal.projects.v2";
const SCHEMA_VERSION = 2;

/**
 * Хранилище браузера конечно. Без предела запись однажды падает по квоте, и
 * пользователь теряет текущую работу из-за песен, которые не открывал
 * месяцами. Вытесняем самые старые по времени открытия.
 */
const MAX_PROJECTS = 20;

export interface StoredProject {
  project: Project;
  savedAt: string;
}

interface StoredEnvelope {
  schema: number;
  projects: StoredProject[];
}

/** Минимальная проверка формы. Полной валидации схемы здесь нет намеренно:
 *  ее место — на границе с backend, которого еще нет. */
const looksLikeProject = (value: unknown): value is Project => {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<Project>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.name === "string" &&
    typeof candidate.currentVersionId === "string" &&
    Array.isArray(candidate.versions) &&
    Array.isArray(candidate.shareRecipients) &&
    typeof candidate.analysis === "object" &&
    typeof candidate.stagePack === "object"
  );
};

const read = (): StoredProject[] => {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Приватный режим и запрет на хранение данных сайта: работаем без
    // сохранения, а не падаем.
    return [];
  }
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredEnvelope>;
    if (parsed.schema !== SCHEMA_VERSION || !Array.isArray(parsed.projects)) {
      forgetProject();
      return [];
    }
    return parsed.projects.filter(
      (item): item is StoredProject =>
        typeof item === "object" && item !== null && typeof item.savedAt === "string" && looksLikeProject(item.project),
    );
  } catch {
    // Битое сохранение не должно ронять приложение: пользователь остается
    // без песен, но с работающим экраном.
    forgetProject();
    return [];
  }
};

const write = (projects: StoredProject[]): void => {
  try {
    const envelope: StoredEnvelope = { schema: SCHEMA_VERSION, projects };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
  } catch {
    // Квота переполнена или хранение запрещено. Терять работу из-за этого
    // нельзя: песня остается в памяти вкладки.
  }
};

/** Песни, недавно открытая первой. */
export const listStoredProjects = (): StoredProject[] =>
  [...read()].sort((a, b) => b.savedAt.localeCompare(a.savedAt));

/** Последняя открытая песня. */
export const loadProject = (): Project | null => listStoredProjects()[0]?.project ?? null;

export const saveProject = (project: Project, savedAt: string): void => {
  const rest = read().filter((item) => item.project.id !== project.id);
  const next = [...rest, { project, savedAt }]
    .sort((a, b) => b.savedAt.localeCompare(a.savedAt))
    .slice(0, MAX_PROJECTS);
  write(next);
};

export const removeStoredProject = (projectId: string): void => {
  write(read().filter((item) => item.project.id !== projectId));
};

export const forgetProject = (): void => {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Нечего чистить — значит нечего и терять.
  }
};
