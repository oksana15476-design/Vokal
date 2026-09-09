import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Относительные пути к ассетам: сборка открывается и по корню домена, и по
  // вложенному пути вида example.com/Vokal/. Без этого на подпути будет белая
  // страница — ассеты уйдут в /assets/ и дадут 404. Клиентского роутинга в
  // приложении нет, поэтому относительная база безопасна.
  base: "./",
  plugins: [react()],
  test: {
    environment: "node",
    testTimeout: 15000,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    passWithNoTests: true,
  },
});
