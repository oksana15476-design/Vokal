/**
 * Откуда фронтенд берет данные: моки или сервер.
 *
 * Решение принимается один раз и по одному признаку — переменной окружения
 * `VITE_API_BASE`. Пустая переменная означает моки; заданная — сервер. Никаких
 * догадок по адресу страницы и никакого «адреса по умолчанию»: в проекте, где
 * бэкенд отвечает `501` почти на все, тихий откат на моки — самая дорогая
 * ошибка. Разработчик уверен, что смотрит на сервер, а видит подготовленные
 * данные.
 */

/** То, что дает `import.meta.env`. Отдельным типом, чтобы функцию можно было проверить. */
export interface ApiEnvLike {
  VITE_API_BASE?: unknown;
  /** Прежнее имя из `.env.example`. Читается, чтобы чужой локальный .env не замолчал. */
  VITE_API_BASE_URL?: unknown;
}

export type ApiMode = "mock" | "server";

const asText = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/**
 * Адрес корня API вместе с префиксом `/api`, без хвостового слеша, либо `null`.
 *
 * Бросает исключение на заданном, но неразбираемом значении: опечатка в адресе
 * обязана останавливать запуск, а не превращаться в моки за спиной у человека.
 */
export const resolveApiBase = (env: ApiEnvLike): string | null => {
  const raw = asText(env.VITE_API_BASE) || asText(env.VITE_API_BASE_URL);
  if (!raw) {
    return null;
  }

  const withoutTrailingSlash = raw.replace(/\/+$/, "");

  // Относительный путь допустим: фронтенд и API за одним доменом — рабочий
  // случай, и `/api` там достаточный адрес.
  if (withoutTrailingSlash.startsWith("/")) {
    return withoutTrailingSlash;
  }

  try {
    const parsed = new URL(withoutTrailingSlash);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("протокол");
    }
  } catch {
    throw new Error(
      `VITE_API_BASE задан, но не разбирается как адрес: «${raw}». ` +
        "Ожидается http(s)://host:port/api или путь вида /api.",
    );
  }

  return withoutTrailingSlash;
};

export const apiModeOf = (baseUrl: string | null): ApiMode => (baseUrl ? "server" : "mock");

/**
 * Значение из сборки Vite. Вынесено отдельной функцией, потому что
 * `import.meta.env` недоступен в тестовой среде `node` без сборщика.
 */
export const readEnvApiBase = (): string | null => {
  const env = (import.meta as unknown as { env?: ApiEnvLike }).env ?? {};
  return resolveApiBase(env);
};
