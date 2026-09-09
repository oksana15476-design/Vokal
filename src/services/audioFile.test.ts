import { describe, expect, it, vi } from "vitest";
import {
  type DecodedAudio,
  formatDuration,
  qualityFromAudio,
  qualityReason,
  readAudioFacts,
} from "./audioFile";

const decoded = (over: Partial<DecodedAudio> = {}): DecodedAudio => ({
  duration: 2,
  sampleRate: 44100,
  numberOfChannels: 2,
  peak: 0.8,
  ...over,
});

const fileLike = (name: string, size: number) => ({
  name,
  size,
  arrayBuffer: () => Promise.resolve(new ArrayBuffer(size)),
});

describe("формат длительности", () => {
  it("всегда мм:сс, потому что «3 минуты» уронит сторож честности", () => {
    expect(formatDuration(0)).toBe("0:00");
    expect(formatDuration(2)).toBe("0:02");
    expect(formatDuration(62)).toBe("1:02");
    expect(formatDuration(222)).toBe("3:42");
    expect(formatDuration(3599)).toBe("59:59");
  });

  it("округляет вниз и не дает отрицательных", () => {
    expect(formatDuration(2.9)).toBe("0:02");
    expect(formatDuration(-5)).toBe("0:00");
  });
});

describe("качество исходника по содержимому", () => {
  it("стерео 44100 без клиппинга — хорошее", () => {
    expect(qualityFromAudio(decoded())).toBe("good");
  });

  it("моно понижает качество", () => {
    expect(qualityFromAudio(decoded({ numberOfChannels: 1 }))).toBe("low");
  });

  it("низкая частота дискретизации понижает качество", () => {
    expect(qualityFromAudio(decoded({ sampleRate: 22050 }))).toBe("low");
  });

  it("клиппинг НЕ делает коммерческий мастеринг непригодным", () => {
    // Регресс: правило peak >= 0.999 объявляло низкокачественным почти любой
    // отмастеренный трек — современный мастеринг штатно упирается в единицу.
    // На интервью песня музыканта была бы забракована и уронила бы обработку.
    expect(qualityFromAudio(decoded({ peak: 1 }))).toBe("medium");
    expect(qualityFromAudio(decoded({ peak: 0.9999 }))).toBe("medium");
  });

  it("непригодность определяется техническими признаками, а не громкостью", () => {
    expect(qualityFromAudio(decoded({ numberOfChannels: 1, peak: 0.5 }))).toBe("low");
    expect(qualityFromAudio(decoded({ sampleRate: 22050, peak: 0.5 }))).toBe("low");
  });

  it("стерео 32000 без клиппинга — среднее", () => {
    expect(qualityFromAudio(decoded({ sampleRate: 32000 }))).toBe("medium");
  });

  it("сообщает причину низкого качества, а не общее слово", () => {
    expect(qualityReason(decoded({ numberOfChannels: 1 }))).toContain("моно");
    expect(qualityReason(decoded({ sampleRate: 22050 }))).toContain("частота");
    expect(qualityReason(decoded())).toBeNull();
  });
});

describe("факты о файле", () => {
  it("берет длительность из декодированного буфера, а не из константы", async () => {
    const result = await readAudioFacts(fileLike("song.mp3", 4_000_000), async () =>
      decoded({ duration: 222.7, sampleRate: 48000, numberOfChannels: 1 }),
    );

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.facts.durationSeconds).toBeCloseTo(222.7);
    expect(result.facts.sampleRate).toBe(48000);
    expect(result.facts.channels).toBe(1);
    expect(result.facts.sizeBytes).toBe(4_000_000);
  });

  it("объясняет отказ декодера иначе, чем неподдерживаемый формат", async () => {
    const result = await readAudioFacts(fileLike("broken.m4a", 1000), async () => {
      throw new Error("EncodingError");
    });

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("не смог прочитать");
    expect(result.error).not.toContain("не поддерживается");
  });

  it("отклоняет пустой файл до вызова декодера", async () => {
    const decode = vi.fn();
    const result = await readAudioFacts(fileLike("empty.wav", 0), decode);

    expect(result.ok).toBe(false);
    expect(decode).not.toHaveBeenCalled();
  });

  it("отклоняет запись без звука", async () => {
    const result = await readAudioFacts(fileLike("silence.wav", 1000), async () =>
      decoded({ duration: 0 }),
    );

    expect(result.ok).toBe(false);
  });
});
