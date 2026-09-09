// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";

afterEach(cleanup);

const PROCESSING_MS = 8000;

const openBandDemo = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));
};

const waitForStagePack = async () =>
  waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
    timeout: PROCESSING_MS,
  });

describe("экран обработки", () => {
  it("доводит все вехи до готовности, включая «Ревью»", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);

    const review = await screen.findByText("Ревью");
    const milestone = review.closest(".processing-milestone");
    expect(milestone).not.toBeNull();

    // Регресс: веха «Ревью» ссылалась на несуществующий шаг и навсегда оставалась queued.
    await waitFor(() => expect(milestone!.className).not.toContain("queued"), { timeout: PROCESSING_MS });
  });

  it("показывает предупреждения обработки", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);

    expect(await screen.findByLabelText("Предупреждения обработки")).toBeTruthy();
  });

  it("показывает оценку сложности обработки", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);

    const estimate = await screen.findByLabelText("Оценка сложности обработки");
    expect(within(estimate).getByText(/единиц сложности/)).toBeTruthy();
    expect(within(estimate).getByText(/средняя сложность/)).toBeTruthy();
  });
});

describe("загрузка файла", () => {
  it("отклоняет неподдерживаемый формат и объясняет причину", async () => {
    render(<App />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["x"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    fireEvent.change(input);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("не поддерживается");
  });

  it("объясняет, почему кнопка запуска недоступна", async () => {
    render(<App />);

    expect(screen.getByText("Чтобы продолжить, выберите файл песни.")).toBeTruthy();
  });

  it("принимает поддерживаемый формат", async () => {
    const user = userEvent.setup();
    render(<App />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["x"], "song.mp3", { type: "audio/mpeg" }));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("song.mp3")).toBeTruthy();
  });
});

describe("Stage Pack", () => {
  it("показывает ответ AI-директора в диалоге после действия", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    // Демо-проекты приходят с готовой репликой директора: до правки она не рендерилась вовсе.
    const log = screen.getByLabelText("Диалог с AI-директором");
    expect(log.textContent).toContain("Я нашел две гитарные партии");
    const before = log.querySelectorAll(".chat-message").length;

    await user.click(within(screen.getByRole("tabpanel")).getAllByText("Усилить")[0]);

    await waitFor(() =>
      expect(screen.getByLabelText("Диалог с AI-директором").querySelectorAll(".chat-message").length).toBe(
        before + 1,
      ),
    );
  });

  it("кодирует точность цветом, а не длиной полосы", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    // Вокал 91% -> high, Гитара 72% -> mid. Раньше градиент красил высокие значения в красный.
    const vocal = screen.getByLabelText(/Вокал: точность разбора/);
    const guitar = screen.getByLabelText(/Гитара: точность разбора/);

    expect(vocal.querySelector("b")!.className).toBe("high");
    expect(guitar.querySelector("b")!.className).toBe("mid");
  });

  it("откатывает материалы к предыдущей версии", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    const versionsBefore = document.querySelectorAll(".version-row").length;
    const activeLabel = document.querySelector(".version-row.active span")!.textContent!;

    await user.click(within(screen.getByRole("tabpanel")).getAllByText("Усилить")[0]);
    await waitFor(() => expect(document.querySelectorAll(".version-row").length).toBe(versionsBefore + 1));

    await user.click(screen.getByRole("tab", { name: /Материалы/ }));
    expect(screen.getAllByText("нужно пересобрать").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    const target = [...document.querySelectorAll(".version-row")].find(
      (row) => row.querySelector("span")?.textContent === activeLabel,
    )!;
    await user.click(target as HTMLElement);

    await user.click(screen.getByRole("tab", { name: /Материалы/ }));
    await waitFor(() => expect(screen.queryByText("нужно пересобрать")).toBeNull());
  });
});

describe("доменные поля на экране", () => {
  it("показывает жанр, аудиторию материала и данные исходника", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    // Жанр лежал в модели, но не выводился нигде.
    expect(screen.getByText("pop/rock")).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: /Материалы/ }));
    expect(document.body.textContent).toContain("всем");

    await user.click(screen.getByRole("tab", { name: /Экспорт/ }));
    expect(screen.getByText(/Формат: DEMO/)).toBeTruthy();
    expect(screen.getByText(/Качество: среднее/)).toBeTruthy();
  });
});

describe("честность текста", () => {
  // Регресс: интерфейс обещал бесплатный тариф, подписку Pro и сроки обработки,
  // которых в прототипе нет. Ось заменена на «собрано / имитация / нужна обработка».
  // Сторож проверяет СВОЙСТВО «не обещаем цен и сроков», а не список исторических строк.
  // Первая версия списка была литеральной и пропускала «3-5 минут» под подписью
  // «ориентир по времени» — зеленый тест удостоверял не то, что требовалось.
  const forbidden = [
    /бесплатн/i,
    /подписк/i,
    /\bPro\b/,
    /\bFree\b/,
    /без оплаты/i,
    // любое обещание срока: число рядом с единицей времени
    /\d+\s*[-–—]?\s*\d*\s*(секунд|минут|час)/i,
    /за несколько (секунд|минут|час)/i,
    // любое обещание цены
    /₽|\bруб|\bцена\b|стоимост|тариф|кредит/i,
    /\bмок/i,
    /ё/,
  ];

  it("не обещает тарифов, сроков и не содержит жаргона на первом экране", () => {
    render(<App />);
    const text = document.body.textContent ?? "";

    for (const pattern of forbidden) {
      expect(text, `первый экран: ${pattern}`).not.toMatch(pattern);
    }
  });

  it("не обещает сроков на экране обработки", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));

    // Блок оценки живет здесь, а сторож его раньше не видел вовсе.
    await screen.findByLabelText("Оценка сложности обработки");
    const text = document.body.textContent ?? "";

    for (const pattern of forbidden) {
      expect(text, `экран обработки: ${pattern}`).not.toMatch(pattern);
    }
  });

  it("не обещает тарифов, сроков и не содержит жаргона в Stage Pack", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    for (const tab of [/Обзор/, /Материалы/, /Проверка/, /AI-директор/, /Экспорт/]) {
      await user.click(screen.getByRole("tab", { name: tab }));
      const text = document.body.textContent ?? "";

      for (const pattern of forbidden) {
        expect(text, `вкладка ${tab}: ${pattern}`).not.toMatch(pattern);
      }
    }
  });
});
