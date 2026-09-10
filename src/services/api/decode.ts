/**
 * Проверка ответа сервера на соответствие контракту.
 *
 * Зачем это вообще: `as ProjectOut` в TypeScript — обещание, а не проверка. В
 * рантайме от него ничего не остается, и разошедшийся контракт вскрывается не
 * здесь, а через три экрана, в виде `undefined` в верстке. В `projectStorage.ts`
 * уже записано, что место полной проверки схемы — на границе с бэкендом; это
 * она и есть.
 *
 * Библиотеку не берем: добавление зависимости меняет `package.json`, а он
 * принадлежит другому батчу. Набор проверок ниже покрывает контракт целиком.
 *
 * Правило снисходительности: **лишние поля в ответе разрешены**. Сервер строг
 * ко входу (`extra="forbid"` в схемах), клиент терпим к выходу — иначе
 * добавление поля на сервере ломает все выложенные фронтенды разом.
 */

export class DecodeError extends Error {
  readonly path: string;

  constructor(path: string, expected: string, received: unknown) {
    super(`Поле «${path || "<корень>"}»: ожидалось ${expected}, пришло ${describe(received)}`);
    this.name = "DecodeError";
    this.path = path;
  }
}

const describe = (value: unknown): string => {
  if (value === null) return "null";
  if (Array.isArray(value)) return "массив";
  return typeof value;
};

export type Decoder<T> = (value: unknown, path?: string) => T;

const at = (path: string, key: string | number): string =>
  typeof key === "number" ? `${path}[${key}]` : path ? `${path}.${key}` : key;

export const str: Decoder<string> = (value, path = "") => {
  if (typeof value !== "string") throw new DecodeError(path, "строка", value);
  return value;
};

export const num: Decoder<number> = (value, path = "") => {
  if (typeof value !== "number" || Number.isNaN(value)) {
    throw new DecodeError(path, "число", value);
  }
  return value;
};

export const bool: Decoder<boolean> = (value, path = "") => {
  if (typeof value !== "boolean") throw new DecodeError(path, "булево", value);
  return value;
};

export const anything: Decoder<unknown> = (value) => value;

/** `null` и отсутствие поля — одно и то же: сервер шлет `null`, а не пропуск. */
export const nullable =
  <T>(inner: Decoder<T>): Decoder<T | null> =>
  (value, path = "") =>
    value === null || value === undefined ? null : inner(value, path);

export const withDefault =
  <T>(inner: Decoder<T>, fallback: T): Decoder<T> =>
  (value, path = "") =>
    value === null || value === undefined ? fallback : inner(value, path);

export const arr =
  <T>(inner: Decoder<T>): Decoder<T[]> =>
  (value, path = "") => {
    if (!Array.isArray(value)) throw new DecodeError(path, "массив", value);
    return value.map((item, index) => inner(item, at(path, index)));
  };

export const record =
  <T>(inner: Decoder<T>): Decoder<Record<string, T>> =>
  (value, path = "") => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new DecodeError(path, "объект", value);
    }
    const result: Record<string, T> = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = inner(item, at(path, key));
    }
    return result;
  };

export type ShapeOf<S> = { [K in keyof S]: S[K] extends Decoder<infer T> ? T : never };

export const obj =
  <S extends Record<string, Decoder<unknown>>>(shape: S): Decoder<ShapeOf<S>> =>
  (value, path = "") => {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new DecodeError(path, "объект", value);
    }
    const source = value as Record<string, unknown>;
    const result: Record<string, unknown> = {};
    for (const [key, decoder] of Object.entries(shape)) {
      result[key] = decoder(source[key], at(path, key));
    }
    return result as ShapeOf<S>;
  };

/**
 * Значение из закрытого списка. Незнакомое значение — отказ, а не подстановка
 * первого варианта: молча выбранный статус хуже видимой ошибки.
 */
export const oneOf =
  <T extends string>(values: readonly T[]): Decoder<T> =>
  (value, path = "") => {
    if (typeof value !== "string" || !values.includes(value as T)) {
      throw new DecodeError(path, `одно из: ${values.join(", ")}`, value);
    }
    return value as T;
  };

/** Пусто — тела нет (204 и подобные). */
export const empty: Decoder<null> = () => null;
