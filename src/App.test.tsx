// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

// В jsdom нет AudioContext, поэтому декодер подменяется. Ровно ради этого он
// вынесен за интерфейс в audioFile.ts.
vi.mock("./services/audioFile", async () => {
  const actual = await vi.importActual<typeof import("./services/audioFile")>("./services/audioFile");
  return {
    ...actual,
    browserDecoder: vi.fn(async () => ({
      duration: 222.7,
      sampleRate: 48000,
      numberOfChannels: 2,
      peak: 0.8,
    })),
  };
});

const pickFile = async (name = "moya-pesnya.mp3", size = 4_000_000) => {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["x"], name, { type: "audio/mpeg" });
  Object.defineProperty(file, "size", { value: size });
  Object.defineProperty(file, "arrayBuffer", { value: () => Promise.resolve(new ArrayBuffer(size)) });
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
  await waitFor(() => expect(screen.getByText(name)).toBeTruthy());
};

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

  it("принимает поддерживаемый формат и читает его", async () => {
    render(<App />);
    await pickFile("song.mp3");

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("объясняет отказ декодера иначе, чем неподдерживаемый формат", async () => {
    const { browserDecoder } = await import("./services/audioFile");
    vi.mocked(browserDecoder).mockRejectedValueOnce(new Error("EncodingError"));
    render(<App />);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["x"], "broken.m4a", { type: "audio/mp4" });
    Object.defineProperty(file, "size", { value: 1000 });
    Object.defineProperty(file, "arrayBuffer", { value: () => Promise.resolve(new ArrayBuffer(8)) });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    fireEvent.change(input);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("не смог прочитать");
    expect(alert.textContent).not.toContain("не поддерживается");
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

// Регресс: интерфейс обещал бесплатный тариф, подписку Pro и сроки обработки,
// которых в прототипе нет. Ось заменена на «собрано / имитация / нужна обработка».
// Сторож проверяет СВОЙСТВО «не обещаем цен и сроков», а не список исторических строк.
// Первая версия списка была литеральной и пропускала «3-5 минут» под подписью
// «ориентир по времени» — зеленый тест удостоверял не то, что требовалось.
// Вторая версия смотрела только в document.body и пропустила «моковый» в <head>.
// Третья версия использовала \b на кириллице. В JavaScript \b определен только
// по ASCII, поэтому /\bмок/i, /\bруб/ и /\bцена\b/ не могли совпасть НИКОГДА:
// три запрета молча ничего не проверяли, а тест был зеленым, потому что не мог
// упасть. Граница слова для кириллицы — только через \p{L} с флагом u.
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
  /₽|(?<!\p{L})руб|(?<!\p{L})цен[аыуе]|стоимост|тариф|кредит/iu,
  // жаргон разработчика
  /(?<!\p{L})мок/iu,
  /ё/,
];

describe("честность текста", () => {
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

  // Сторож проходил только демо-путь, поэтому не видел названия загруженного
  // проекта — а там жило слово «моковая».
  it("не обещает тарифов, сроков и не содержит жаргона на пути загрузки", async () => {
    const user = userEvent.setup();
    render(<App />);
    await pickFile();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Запустить демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    for (const tab of [/Обзор/, /Материалы/, /Проверка/, /AI-директор/, /Экспорт/]) {
      await user.click(screen.getByRole("tab", { name: tab }));
      const text = document.body.textContent ?? "";

      for (const pattern of forbidden) {
        expect(text, `загрузка, вкладка ${tab}: ${pattern}`).not.toMatch(pattern);
      }
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

describe("честность разметки документа", () => {
  // index.html не попадает в jsdom при рендере компонента, поэтому сторож по
  // document.body его не видел — и слово «моковый» пережило чистку текста.
  // Проверяем файл на диске тем же набором запретов.
  it("не содержит жаргона и обещаний в title и meta", async () => {
    const fs = await import("node:fs/promises");
    const html = await fs.readFile(`${process.cwd()}/index.html`, "utf-8");
    const meta = [...html.matchAll(/content="([^"]*)"/g)].map((m) => m[1]).join(" ");
    const title = html.match(/<title>([^<]*)<\/title>/)?.[1] ?? "";
    const text = `${title} ${meta}`;

    for (const pattern of forbidden) {
      expect(text, `index.html: ${pattern}`).not.toMatch(pattern);
    }
  });
});

describe("правда о загруженном файле", () => {
  const startUpload = async (user: ReturnType<typeof userEvent.setup>) => {
    await pickFile();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Запустить демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });
  };

  it("не показывает тональность и аккорды чужой песни", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // Регресс: раньше на своем файле показывались G minor, 104 BPM и аккорды демо.
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("G minor");
    expect(text).not.toContain("104 BPM");
    expect(screen.queryByLabelText("Аккорды")).toBeNull();
  });

  it("не показывает процент точности, которого нет", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    expect(document.body.textContent ?? "").not.toMatch(/точность разбора\s*\d/);
    expect(document.body.textContent ?? "").not.toContain("NaN");
  });

  it("объясняет, что звук не анализируется", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    expect(screen.getByText(/Звук не анализируется/)).toBeTruthy();
  });

  it("показывает настоящую длительность файла, а не константу", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);
    await user.click(screen.getByRole("tab", { name: /Экспорт/ }));

    // 222.7 c = 3:42. Раньше здесь стояла зашитая константа 214 c = 3:34.
    expect(screen.getAllByText(/3:42/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Частота: 48000/)).toBeTruthy();
    expect(screen.getByText(/Качество: хорошее/)).toBeTruthy();
    expect(document.body.textContent ?? "").not.toContain("3:34");
  });

  it("демо-проект по-прежнему показывает свой разбор", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    expect(document.body.textContent ?? "").toContain("G minor");
  });

  it("не делает сетевых вызовов при выборе файла", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<App />);
    await pickFile();

    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
