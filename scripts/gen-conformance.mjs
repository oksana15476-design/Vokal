/**
 * Сверяет руками написанные типы клиента с типами, сгенерированными из
 * OpenAPI. Решение из docs/architecture.md: источник правды — контракт
 * сервера, а не типы во фронтенде.
 *
 * Сверка компилируемая: если сервер изменит схему, а клиент не поправят,
 * упадет `npm run typecheck`, а не прод.
 */
import { readFileSync, writeFileSync } from "node:fs";

const contract = readFileSync("src/services/api/contract.ts", "utf8");
const spec = JSON.parse(readFileSync("docs/api/openapi.json", "utf8"));
const schemas = Object.keys(spec.components.schemas);

const wireNames = [...contract.matchAll(/^export interface Wire([A-Za-z0-9]+)/gm)].map((m) => m[1]);

// Соглашение об именах сервера: сущность наружу — XOut, ответ — XResponse.
const candidates = (name) => [`${name}Out`, name, `${name}Response`, `${name}ListResponse`];
const matched = [];
const unmatched = [];
for (const name of wireNames) {
  const hit = candidates(name).find((c) => schemas.includes(c));
  if (hit) matched.push([name, hit]);
  else unmatched.push(name);
}

const lines = [
  "// Файл создается скриптом scripts/gen-conformance.mjs. Руками не править.",
  "//",
  "// Проверка соответствия клиента контракту сервера. Решение из",
  "// docs/architecture.md: источник правды — OpenAPI, а не типы во фронтенде.",
  "// Пока часть типов написана руками, эта сверка держит их в соответствии:",
  "// разойдутся — упадет `npm run typecheck`, а не прод.",
  "",
  'import type { components } from "./schema";',
  "import type {",
  ...matched.map(([wire]) => `  Wire${wire},`),
  '} from "./contract";',
  "",
  'type Schemas = components["schemas"];',
  "",
  "/** Взаимная присваиваемость: расхождение в любую сторону — ошибка типов. */",
  "type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;",
  "type Assert<T extends true> = T;",
  "",
];

for (const [wire, schema] of matched) {
  lines.push(`export type Check${wire} = Assert<Same<Wire${wire}, Schemas["${schema}"]>>;`);
}

if (unmatched.length) {
  lines.push("");
  lines.push("// Без пары в контракте сервера. Каждое имя здесь — либо тип,");
  lines.push("// которого на сервере нет, либо расхождение в именовании:");
  for (const name of unmatched) lines.push(`//   Wire${name}`);
}
lines.push("");

writeFileSync("src/services/api/conformance.ts", lines.join("\n"));
console.log(`сверено типов: ${matched.length}, без пары: ${unmatched.length}`);
if (unmatched.length) console.log("без пары:", unmatched.join(", "));
