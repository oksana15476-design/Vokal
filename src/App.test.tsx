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
    const log = screen.getByLabelText("Разговор с AI-директором");
    expect(log.textContent).toContain("Я нашел две гитарные партии");
    const before = log.querySelectorAll(".chat-bubble").length;

    await user.click(within(screen.getByRole("tabpanel")).getAllByText("Усилить припев")[0]);

    // Две реплики: команда пользователя и ответ директора. Раньше писалась
    // только вторая, и было непонятно, на что директор отвечает.
    await waitFor(() =>
      expect(screen.getByLabelText("Разговор с AI-директором").querySelectorAll(".chat-bubble").length).toBe(
        before + 2,
      ),
    );
  });

  it("кодирует точность цветом, а не длиной полосы", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    // Пороги задаёт дизайн-система: 85 и выше — акцент, 75-84 — внимание,
    // ниже 75 — опасность. Вокал 91 -> high, Клавиши 78 -> mid, Гитара 72 -> low.
    // Раньше градиент красил высокие значения в красный независимо от порогов.
    const barFor = (part: string) => {
      const row = [...document.querySelectorAll(".console-track-row")].find((node) =>
        node.querySelector(".track-name strong")?.textContent?.includes(part),
      );
      expect(row, `нет дорожки «${part}»`).toBeTruthy();
      return row!.querySelector(".track-confidence b")!.className;
    };

    expect(barFor("Вокал")).toBe("high");
    expect(barFor("Клавиши")).toBe("mid");
    expect(barFor("Гитара")).toBe("low");
  });

  it("откатывает материалы к предыдущей версии", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    const versionsBefore = document.querySelectorAll(".version-row").length;
    const activeLabel = document.querySelector(".version-row.active span")!.textContent!;

    await user.click(within(screen.getByRole("tabpanel")).getAllByText("Усилить припев")[0]);
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

    await user.click(screen.getByRole("tab", { name: /Выдача/ }));
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
    await user.click(screen.getByRole("button", { name: /Разобрать мой файл/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    for (const tab of [/Обзор/, /Материалы/, /Проверка/, /AI-директор/, /Выдача/]) {
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

    for (const tab of [/Обзор/, /Материалы/, /Проверка/, /AI-директор/, /Выдача/]) {
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
    await user.click(screen.getByRole("button", { name: /Разобрать мой файл/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });
  };

  it("не показывает тональность и аккорды чужой песни", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // Регресс: раньше на своем файле показывались Gm, 104 BPM и аккорды демо.
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("Gm");
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
    await user.click(screen.getByRole("tab", { name: /Выдача/ }));

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

    expect(document.body.textContent ?? "").toContain("Gm");
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

describe("свой файл не выдается за демо", () => {
  it("кнопка запуска на своем файле не называет разбор демонстрационным", async () => {
    render(<App />);
    await pickFile();

    expect(screen.getByRole("button", { name: /Разобрать мой файл/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Запустить демо-разбор/ })).toBeNull();
  });

  it("пустое состояние открывает демо-разбор, а не выбрасывает на главную", async () => {
    const user = userEvent.setup();
    render(<App />);
    await pickFile();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Разобрать мой файл/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    // Регресс: кнопка была подписана «Посмотреть на демо-разборе», а вызывала
    // возврат на первый экран — обещанное действие не выполнялось.
    await user.click(screen.getAllByRole("button", { name: /Открыть демо-разбор/ })[0]);
    await waitFor(() => expect(document.body.textContent).toContain("Gm"), {
      timeout: PROCESSING_MS,
    });
  });
});

describe("пустые вкладки объясняют пустоту", () => {
  const uploadPath = async (user: ReturnType<typeof userEvent.setup>) => {
    await pickFile();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Разобрать мой файл/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });
  };

  it("не выдает отсутствие разбора за успех", async () => {
    const user = userEvent.setup();
    render(<App />);
    await uploadPath(user);

    // Регресс: «без разбора» рисовалось классом успеха, а сводка справа
    // утверждала, что форма и аккорды собраны — на этом пути это неправда.
    expect(screen.getByText("без разбора").className).not.toContain("ready");
    const summary = screen.getByText("Собрано").closest("span")!;
    expect(summary.textContent).not.toContain("аккорды");
  });

  it("не показывает три нуля вместо состояния проекта", async () => {
    const user = userEvent.setup();
    render(<App />);
    await uploadPath(user);

    // Регресс: полоса показывала «0/0 материалов», «0 на проверку», «0/0 получателей».
    const strip = screen.getByLabelText("Состояние песни");
    expect(strip.textContent).not.toContain("0/0");
    expect(strip.textContent).toContain("разбора песни нет");
  });

  it("объясняет, почему нет сомнительных тактов, вместо «0 в работе»", async () => {
    const user = userEvent.setup();
    render(<App />);
    await uploadPath(user);
    await user.click(screen.getByRole("tab", { name: /Проверка/ }));

    // Ноль без объяснения читается как «проверено, проблем нет» — обратное правде.
    expect(screen.getByText(/Сомнительных мест нет, потому что нет разбора/)).toBeTruthy();
    expect(screen.queryByText(/в работе/)).toBeNull();
  });

  it("объясняет пустого AI-директора и пустой экспорт", async () => {
    const user = userEvent.setup();
    render(<App />);
    await uploadPath(user);

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    expect(screen.getByText(/Предложений пока нет/)).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: /Выдача/ }));
    expect(screen.getByText(/Получателей пока нет/)).toBeTruthy();
  });

  it("демо-путь пустых состояний не показывает", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: /Открыть демо-разбор/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: /Материалы/ })).toBeTruthy(), {
      timeout: PROCESSING_MS,
    });

    await user.click(screen.getByRole("tab", { name: /Проверка/ }));
    expect(screen.queryByText(/Сомнительных мест нет/)).toBeNull();
    expect(screen.getByText(/в работе/)).toBeTruthy();
  });
});

describe("шаги обработки не рапортуют о несделанном (B71)", () => {
  // Останавливается на экране обработки, а не проскакивает его насквозь.
  const startUpload = async (user: ReturnType<typeof userEvent.setup>) => {
    await pickFile();
    await user.click(screen.getByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: /Разобрать мой файл/ }));
    await screen.findByRole("heading", { name: /Читаем ваш файл/ });
  };

  it("не доводит до «готово» шаги, результата которых не существует", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // На пути загрузки Stage Pack пуст: разделения слоев, аккордов, MIDI и
    // нот не произошло. Восемь зеленых шагов были отчетом о несделанном.
    const milestones = [...document.querySelectorAll(".processing-milestone")];
    expect(milestones.length).toBeGreaterThan(0);
    expect(milestones.every((node) => !node.className.includes("done"))).toBe(true);
    expect(milestones.every((node) => node.className.includes("skipped"))).toBe(true);
  });

  it("подписывает пропущенный шаг словами, а не только классом", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // Класс пользователь не видит. Причину он должен прочитать.
    expect(screen.getAllByText(/не выполняется/i).length).toBeGreaterThan(0);
  });

  it("доводит прогресс до 100%, когда выполнять нечего", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // Знаменатель считается по выполняемым шагам. Со старым знаменателем
    // полоса застревала, а все тесты оставались зелеными.
    await waitFor(() => expect(screen.getByLabelText("Прогресс 100%")).toBeTruthy(), { timeout: PROCESSING_MS });
  });

  it("не обещает, что шаги идут, там где они не идут", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);
    expect(screen.queryByText(/Шаги идут по таймеру/)).toBeNull();
  });

  it("не оценивает работу, которая не будет выполнена", async () => {
    const user = userEvent.setup();
    render(<App />);
    await startUpload(user);

    // Экран уже сказал «Разбор не создается». Оценка сложности рядом с этой
    // строкой оценивает работу, которой не будет, — два соседних утверждения
    // противоречат друг другу.
    expect(screen.queryByText(/Оценка сложности/)).toBeNull();
    expect(screen.queryByText(/условных единиц сложности/)).toBeNull();
  });

  it("на демо-разборе шаги по-прежнему выполняются", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await screen.findByRole("heading", { name: /Собираем демо-разбор/ });

    // Демо-данные существуют, поэтому шаги на этом пути настоящие.
    // Правка не должна превратить в «пропущено» и их.
    const milestones = [...document.querySelectorAll(".processing-milestone")];
    expect(milestones.some((node) => node.className.includes("skipped"))).toBe(false);
    await waitFor(() => expect(screen.getByLabelText("Прогресс 100%")).toBeTruthy(), { timeout: PROCESSING_MS });
  });
});

describe("бренд-бук: структура экранов", () => {
  it("показывает шапку продукта со знаком и навигацией", async () => {
    render(<App />);

    const header = document.querySelector(".app-header");
    expect(header).not.toBeNull();
    expect(within(header as HTMLElement).getByText("Vokal")).toBeTruthy();
  });

  it("показывает полосу метрик песни до открытия вкладок", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    const strip = document.querySelector(".metric-strip");
    expect(strip).not.toBeNull();
    // BPM, готовые материалы, такты на проверку, выдача.
    expect(strip!.querySelectorAll(".metric-card").length).toBe(4);
    expect(within(strip as HTMLElement).getByText(/BPM/)).toBeTruthy();
  });

  it("собирает весь звук на одной графитовой панели", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    const console_ = document.querySelector(".console-panel");
    expect(console_).not.toBeNull();
    // Транспорт, форма песни, дорожки и аккорды — внутри неё, а не рядом.
    for (const part of [".console-transport", ".console-wave", ".console-sections", ".console-tracks", ".console-chords"]) {
      expect(console_!.querySelector(part), `нет ${part} внутри пульта`).not.toBeNull();
    }
  });

  it("подписывает процентом каждую полосу уверенности", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    const rows = [...document.querySelectorAll(".console-track-row")];
    expect(rows.length).toBeGreaterThan(0);
    // Цвет — не единственный сигнал: число стоит рядом с полосой.
    for (const row of rows) {
      expect(row.querySelector(".track-confidence"), "нет полосы").not.toBeNull();
      expect(row.querySelector(".track-percent")?.textContent, "нет процента").toMatch(/^\d+%$/);
    }
  });

  it("отличает аккорд под вопросом рамкой, а не только наведением", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    const chords = [...document.querySelectorAll(".console-chords .chord-chip")];
    expect(chords.length).toBeGreaterThan(0);
    expect(chords.some((chip) => chip.className.includes("uncertain"))).toBe(true);
  });

  it("держит не больше одной графитовой кнопки на экране", async () => {
    const user = userEvent.setup();
    render(<App />);

    // Правило бренд-бука: главное действие шага — одно. Стартовый экран
    // раньше держал два графитовых CTA рядом: «подготовить» и «демо».
    expect(document.querySelectorAll("button.btn-primary").length).toBe(1);

    await openBandDemo(user);
    await waitForStagePack();
    expect(document.querySelectorAll("button.btn-primary").length).toBeLessThanOrEqual(1);

    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));
    expect(document.querySelectorAll("button.btn-primary").length).toBeLessThanOrEqual(1);
  });

  it("дает вернуться к открытой песне после ухода на главный экран", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    await user.click(screen.getByRole("button", { name: /На главный экран/ }));

    // Песня остается в памяти, но раньше к ней не вело ничего: работа
    // становилась недостижимой без предупреждения.
    const resume = await screen.findByRole("button", { name: /Вернуться к песне/ });
    await user.click(resume);
    expect(await screen.findByRole("tab", { name: /Материалы/ })).toBeTruthy();
  });

  it("не выполняет нераспознанную команду как чужую", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();
    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));

    const versionsBefore = document.querySelectorAll(".version-row").length;
    await user.type(screen.getByRole("textbox", { name: /Команда AI-директору/ }), "сделай красиво и по-своему");
    await user.click(screen.getByRole("button", { name: /Применить в демо/ }));

    const thread = screen.getByLabelText("Разговор с AI-директором");
    // Текст пользователя остается в переписке дословно, а не подменяется
    // названием действия, которое он не просил.
    await waitFor(() => expect(thread.textContent).toContain("сделай красиво и по-своему"));
    // Раньше любая нераспознанная команда молча выполнялась как «усилить
    // припев» и создавала версию с чужими правками.
    expect(thread.textContent).not.toContain("Усилить припев");
    expect(document.querySelectorAll(".version-row").length).toBe(versionsBefore);
  });

  it("выполняет распознанную команду и пишет ее в переписку", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();
    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));

    const versionsBefore = document.querySelectorAll(".version-row").length;
    await user.type(screen.getByRole("textbox", { name: /Команда AI-директору/ }), "транспонируй ниже");
    await user.click(screen.getByRole("button", { name: /Применить в демо/ }));

    await waitFor(() => expect(document.querySelectorAll(".version-row").length).toBe(versionsBefore + 1));
    expect(screen.getByLabelText("Разговор с AI-директором").textContent).toContain("транспонируй ниже");
  });

  it("не выдает за рабочие кнопки Solo и Mute", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    // Звука нет, солировать и заглушать нечего. Кнопка, которая нажимается
    // и ничего не делает, — обещание, как и кнопка воспроизведения.
    const controls = [...document.querySelectorAll(".track-controls button")].filter(
      (node) => node.textContent === "M" || node.textContent === "S",
    ) as HTMLButtonElement[];
    expect(controls.length).toBeGreaterThan(0);
    for (const button of controls) {
      expect(button.disabled, `кнопка ${button.textContent} нажимается вхолостую`).toBe(true);
    }
  });

  it("дает каждой партии урока свою команду, а не одну на всех", async () => {
    const user = userEvent.setup();
    render(<App />);
    // Демо урока: партии «Мелодия», «Аккорды», «Гитара», «Бас». Вокала в нем
    // нет, и ветка урока раздавала «усложнить» всем четырем.
    await user.click(screen.getByRole("button", { name: /Warm Lights: урок гитары/ }));
    await waitForStagePack();

    const byPart = new Map(
      [...document.querySelectorAll(".console-track-row")].map((row) => [
        row.querySelector(".track-name strong")?.textContent?.trim() ?? "",
        row.querySelector(".track-command")?.textContent?.trim() ?? "",
      ]),
    );

    expect(byPart.size).toBeGreaterThan(2);
    // Раньше все четыре получали «усложнить» — одна команда на весь урок.
    expect(new Set(byPart.values()).size).toBeGreaterThan(1);
    // «Усложнить аккорды» не имеет смысла ни в одном прочтении.
    expect(byPart.get("Аккорды")).not.toBe("усложнить");
    // «Разбор к уроку» не доставался никому: ветка искала вокал, которого нет.
    expect([...byPart.values()]).toContain("разбор к уроку");
    // Ярлыки стоят в колонке фиксированной ширины и не переносятся.
    for (const label of byPart.values()) {
      expect(label.length, `ярлык «${label}» длиннее 14 знаков`).toBeLessThanOrEqual(14);
    }
  });

  it("не выдает за рабочие органы, которых нет", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();

    // Звука в продукте нет. Кнопка воспроизведения, которая нажимается и
    // ничего не делает, — обещание, а не элемент управления.
    const play = document.querySelector(".console-play") as HTMLButtonElement;
    expect(play).not.toBeNull();
    expect(play.disabled).toBe(true);
    expect(play.getAttribute("aria-label")).toMatch(/звук/i);

    // То же про режимы транспорта: клика, скорости и петли не существует.
    expect(document.querySelectorAll(".console-modes .mono-chip").length).toBeLessThanOrEqual(1);
  });

  it("показывает разговор с директором репликами, а не списком карточек", async () => {
    const user = userEvent.setup();
    render(<App />);
    await openBandDemo(user);
    await waitForStagePack();
    await user.click(screen.getByRole("tab", { name: /AI-директор/ }));

    // В демо директор уже сказал первое слово, но пользователь — ещё нет.
    expect(document.querySelectorAll(".director-thread .chat-bubble.from-director").length).toBe(1);
    expect(document.querySelectorAll(".director-thread .chat-bubble.from-user").length).toBe(0);

    await user.click(within(document.querySelector(".suggestions-grid") as HTMLElement).getAllByRole("button")[0]);

    const thread = document.querySelector(".director-thread");
    expect(thread).not.toBeNull();
    // Команда пользователя тоже остаётся в переписке, а не только ответ директора.
    expect(thread!.querySelectorAll(".chat-bubble.from-user").length).toBeGreaterThan(0);
    expect(thread!.querySelectorAll(".chat-bubble.from-director").length).toBeGreaterThan(0);
  });
});
