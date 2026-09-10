import { describe, expect, it } from "vitest";
import {
  toDomainArtifact,
  toDomainBandLineup,
  toDomainLesson,
  toDomainMusician,
  toDomainStudentProfile,
  toDomainTeacherProfile,
} from "./mapping";

describe("перевод ключей контракта в подписи домена", () => {
  it("роль и уровень музыканта переводятся таблицей, а не догадкой", () => {
    const musician = toDomainMusician({
      id: "m1",
      name: "Аня",
      role: "backing_vocal",
      instrumentNote: "два слоя",
      constraint: "диапазон A3-C5",
      level: "middle",
    });

    expect(musician.role).toBe("бэк-вокал");
    expect(musician.level).toBe("средний");
  });

  it("число струн баса переводится в формулировку домена", () => {
    const lineup = toDomainBandLineup({
      leadVocal: true,
      vocalRange: "A2-E4",
      guitars: 2,
      guitarTuning: "Standard E",
      capo: "нет",
      bass: "5_strings",
      keys: true,
      keysCanCoverLayers: true,
      drums: true,
      backingVocals: false,
      musicianLevel: "advanced",
      targetStyle: "концертная",
    });

    expect(lineup.bass).toBe("5 strings");
    expect(lineup.musicianLevel).toBe("advanced");
  });

  it("уровень ученика и чтение нот переводятся в подписи домена", () => {
    const student = toDomainStudentProfile({
      name: "Петя",
      instrument: "гитара",
      level: "strong",
      ageGroup: "13-15",
      notationReading: "confident",
      chordKnowledge: "баррэ",
      homeInstrument: "акустика",
    });

    expect(student.level).toBe("сильный");
    expect(student.notationReading).toBe("уверенно");
  });

  it("формат занятий и желаемая сложность переводятся в подписи домена", () => {
    expect(toDomainTeacherProfile({ name: "И.", format: "school_ensemble", focus: "ансамбль" }).format).toBe(
      "школьный ансамбль",
    );
    expect(
      toDomainLesson({ goal: "разобрать", homeworkFormat: "ученику", desiredDifficulty: "harder" })
        .desiredDifficulty,
    ).toBe("сложнее оригинала");
  });

  it("материал без предпросмотра получает пустой предпросмотр, а не выдуманные строки", () => {
    const artifact = toDomainArtifact({
      id: "a1",
      type: "score",
      name: "Партитура",
      format: "PDF",
      description: "",
      status: "draft",
      confidence: 0.5,
      audience: "all",
      isStale: false,
      preview: null,
      updatedAt: null,
    });

    expect(artifact.preview.lines).toEqual([]);
    expect(artifact.preview.title).toBe("Партитура");
  });
});
