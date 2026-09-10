import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

/*
 * Шрифты дизайн-системы подключаются локально, а не с Google Fonts. Причины две:
 * handoff прямо требует self-host с subset ru+latin, и внешний CDN шрифтов для
 * российского рынка ненадежен — при недоступности вся типографика системы молча
 * заменяется системной, и это не видно ни в одном тесте.
 * Берем только нужные подмножества: кириллица и латиница.
 */
// Вариативная сборка Manrope: один файл на все веса 200-800. Подмножества
// разделены unicode-range, поэтому браузер скачивает только кириллицу и латиницу.
import "@fontsource-variable/manrope/index.css";
import "@fontsource/ibm-plex-mono/cyrillic-400.css";
import "@fontsource/ibm-plex-mono/cyrillic-500.css";
import "@fontsource/ibm-plex-mono/cyrillic-600.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "@fontsource/ibm-plex-mono/latin-600.css";

import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
