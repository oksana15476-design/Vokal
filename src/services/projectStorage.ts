import type { Project } from "../domain/types";

/**
 * Сохранение открытой песни между перезагрузками (B6).
 *
 * Хранилище локальное и только локальное: это `localStorage` браузера, а не
 * облако. Песня не уходит с устройства, не синхронизируется между
 * браузерами и исчезает вместе с очисткой данных сайта. Интерфейс не должен
 * обещать иного, пока нет backend.
 *
 * Схема версионирована. Сохранение, сделанное другой версией приложения,
 * выбрасывается целиком: восстановленный наполовину проект хуже, чем
 * отсутствующий, — он выглядит рабочим и врет в деталях.
 */
const STORAGE_KEY = "vokal.project.v1";
const SCHEMA_VERSION = 1;

interface StoredEnvelope {
  schema: number;
  savedAt: string;
  project: Project;
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

export const loadProject = (): Project | null => {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    // Приватный режим и запрет на хранение данных сайта: работаем без
    // сохранения, а не падаем.
    return null;
  }
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<StoredEnvelope>;
    if (parsed.schema !== SCHEMA_VERSION || !looksLikeProject(parsed.project)) {
      forgetProject();
      return null;
    }
    return parsed.project;
  } catch {
    // Битое сохранение не должно ронять приложение: пользователь остается
    // без песни, но с работающим экраном.
    forgetProject();
    return null;
  }
};

export const saveProject = (project: Project, savedAt: string): void => {
  try {
    const envelope: StoredEnvelope = { schema: SCHEMA_VERSION, savedAt, project };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
  } catch {
    // Квота переполнена или хранение запрещено. Терять работу из-за этого
    // нельзя: песня остается в памяти вкладки.
  }
};

export const forgetProject = (): void => {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Нечего чистить — значит нечего и терять.
  }
};
