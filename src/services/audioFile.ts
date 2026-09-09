import type { Upload } from "../domain/types";

/**
 * Всё, что нужно знать о декодированном аудио. Отдельный тип, потому что
 * настоящий AudioBuffer в jsdom не существует, а тестировать правила надо.
 */
export interface DecodedAudio {
  duration: number;
  sampleRate: number;
  numberOfChannels: number;
  /** Пиковая амплитуда 0..1. Единица означает клиппинг. */
  peak: number;
}

/** Декодирование за интерфейсом: в тестах подставляется, в браузере — Web Audio. */
export type AudioDecoder = (bytes: ArrayBuffer) => Promise<DecodedAudio>;

export interface AudioFacts {
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  sizeBytes: number;
  quality: Upload["quality"];
}

export type AudioFactsResult = { ok: true; facts: AudioFacts } | { ok: false; error: string };

/**
 * Только мм:сс. Формат «3 минуты 42 секунды» уронит сторож честности:
 * число рядом с единицей времени читается как обещание срока обработки.
 */
export const formatDuration = (seconds: number): string => {
  const total = Math.max(0, Math.floor(seconds));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

/**
 * Качество считается по содержимому записи, а не по размеру файла: размер
 * говорит о битрейте контейнера и ничего не говорит о самой записи.
 */
export const qualityFromAudio = (audio: DecodedAudio): Upload["quality"] => {
  const clipping = audio.peak >= 0.999;

  if (audio.numberOfChannels < 2 || audio.sampleRate < 32000 || clipping) {
    return "low";
  }

  return audio.sampleRate >= 44100 ? "good" : "medium";
};

interface FileLike {
  name: string;
  size: number;
  arrayBuffer: () => Promise<ArrayBuffer>;
}

export const readAudioFacts = async (
  file: FileLike,
  decode: AudioDecoder,
): Promise<AudioFactsResult> => {
  if (file.size === 0) {
    return { ok: false, error: "Файл пустой. Выберите запись со звуком." };
  }

  let audio: DecodedAudio;
  try {
    audio = await decode(await file.arrayBuffer());
  } catch {
    return {
      ok: false,
      error: "Браузер не смог прочитать этот файл. Попробуйте MP3 или WAV.",
    };
  }

  if (audio.duration <= 0) {
    return { ok: false, error: "В файле не нашлось звука." };
  }

  return {
    ok: true,
    facts: {
      durationSeconds: audio.duration,
      sampleRate: audio.sampleRate,
      channels: audio.numberOfChannels,
      sizeBytes: file.size,
      quality: qualityFromAudio(audio),
    },
  };
};

/** Декодер на Web Audio. В jsdom отсутствует, поэтому подставляется только в браузере. */
export const browserDecoder: AudioDecoder = async (bytes) => {
  const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const context = new Ctor();

  try {
    const buffer = await context.decodeAudioData(bytes);
    const channel = buffer.getChannelData(0);
    let peak = 0;
    // Шаг по выборкам: на пятиминутной записи это миллионы значений, полный
    // проход блокирует поток без пользы для оценки клиппинга.
    for (let i = 0; i < channel.length; i += 64) {
      const value = Math.abs(channel[i]);
      if (value > peak) peak = value;
    }

    return {
      duration: buffer.duration,
      sampleRate: buffer.sampleRate,
      numberOfChannels: buffer.numberOfChannels,
      peak,
    };
  } finally {
    void context.close();
  }
};
