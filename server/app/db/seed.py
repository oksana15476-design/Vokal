"""Демо-данные: те же три проекта, что в `src/domain/mockData.ts`.

Зачем повторять моки в базе: пока фронтенд ходит в `mockData.ts`, а бэкенд — в
свою базу, «одинаковые» демо расходятся молча, и разница вылезает при
переключении фронтенда на API. Один и тот же набор в обоих местах делает
переключение проверяемым.

Что демо честно не содержит: `storage_key` у загрузок пуст. Аудиофайла за
демо-проектом нет — это записано и в моках («Демо без реального
аудиофайла»). Подставлять правдоподобный ключ значило бы обещать файл,
которого нет, и получить 404 на первой же попытке выдачи.

Запуск: `VOKAL_DATABASE_URL=... python -m app.db.seed`
Повторный запуск ничего не дублирует: идентификаторы детерминированы.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import enums, models
from app.db.repositories import (
    ArtifactCreate,
    JobCreate,
    JobStepCreate,
    MusicianCreate,
    ProjectCreate,
    ProjectPatch,
    Repositories,
    ReviewIssueCreate,
    ShareRecipientCreate,
    UploadCreate,
    UserCreate,
    VersionCreate,
)
from app.db.session import session_scope

#: Пространство имен для устойчивых идентификаторов демо-данных. Фиксированное:
#: от него зависит идемпотентность повторного запуска.
DEMO_NAMESPACE = uuid.UUID("8f4b2c10-6f1a-5d3e-9a77-0c1d2e3f4a5b")

DEMO_OWNER_CONTACT = "demo@vokal.example"

#: Ключи демо-проектов — те же, что идентификаторы в `mockData.ts`.
DEMO_PROJECT_KEYS: tuple[str, ...] = (
    "band-demo",
    "education-lesson-demo",
    "education-ensemble-demo",
)

#: Действующая версия согласия. Дублирует `src/domain/consent.ts`: правка текста
#: там — это новая версия здесь, а не редактирование этой строки.
CONSENT_VERSION_ID = "consent-2026-09-10"
CONSENT_TEXT = (
    "Я вправе обработать этот материал для приватной репетиции, урока или внутренней подготовки."
)

DEMO_MOMENT = datetime(2026, 9, 9, 12, 0, tzinfo=timezone(timedelta(hours=4)))

PROCESSING_STEPS: tuple[tuple[str, str, str], ...] = (
    ("normalize", "Нормализация аудио", "Проверяем формат и уровень громкости."),
    ("stems", "Разделение на аудиослои", "Имитируем вокал, барабаны, бас, гитару и клавиши."),
    ("tempo", "BPM, тональность и размер", "Ищем пульс, тональный центр и смены метра."),
    ("structure", "Структура песни", "Собираем intro, куплеты, припевы, bridge и coda."),
    ("chords", "Аккорды", "Строим черновую аккордовую сетку."),
    ("midi", "MIDI-черновики", "Переводим важные аудиослои в MIDI-партии."),
    ("notation", "MusicXML и PDF", "Готовим ноты и карточки страниц."),
    ("director", "Ревью AI-директора", "Ищем проблемы состава, уровня и выдачи материалов."),
)

PROCESSING_WARNINGS: tuple[str, ...] = (
    "Секция bridge содержит паузу и может потребовать ручной проверки.",
    "Гитарный аудиослой плотный: TAB будет черновиком.",
)


def demo_uuid(*parts: str) -> uuid.UUID:
    """Устойчивый идентификатор демо-объекта.

    Случайные UUID сделали бы повторный запуск скрипта дублированием, а
    сравнение фронтенда с бэкендом — невозможным.
    """
    return uuid.uuid5(DEMO_NAMESPACE, "/".join(parts))


@dataclass(frozen=True, slots=True)
class _DemoVersion:
    key: str
    label: str
    kind: enums.VersionKind
    changes: list[str]


@dataclass(frozen=True, slots=True)
class _DemoArtifact:
    key: str
    artifact_type: enums.ArtifactType
    name: str
    artifact_format: enums.ArtifactFormat
    description: str
    status: enums.ArtifactStatus
    confidence: float
    audience: enums.ArtifactAudience
    preview: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _DemoIssue:
    key: str
    title: str
    section_id: str
    bar: int
    part: str
    reason: str
    status: enums.ReviewStatus
    confidence: float


@dataclass(frozen=True, slots=True)
class _DemoMusician:
    key: str
    name: str
    role: enums.MusicianRole
    instrument_note: str
    constraint_note: str
    level: enums.MusicianLevel


@dataclass(frozen=True, slots=True)
class _DemoRecipient:
    key: str
    name: str
    role: enums.ShareRecipientRole
    material: str
    status: enums.ShareRecipientStatus


def _artifacts(scenario: enums.Scenario) -> list[_DemoArtifact]:
    """Набор материалов Stage Pack — копия `artifacts(scenario)` из моков."""
    instrument_or_student = (
        enums.ArtifactAudience.STUDENT
        if scenario is enums.Scenario.EDUCATION
        else enums.ArtifactAudience.INSTRUMENT
    )
    items = [
        _DemoArtifact(
            "full-score",
            enums.ArtifactType.SCORE,
            "Общая партитура",
            enums.ArtifactFormat.PDF,
            "Черновая партитура для проверки формы, аккордов и партий.",
            enums.ArtifactStatus.NEEDS_REVIEW,
            0.82,
            enums.ArtifactAudience.ALL,
            {
                "kind": "notation",
                "title": "Партитура",
                "lines": [
                    "1 | Gm | Eb | Bb | F",
                    "21 | Eb | Bb | F | Gm",
                    "37 | Cm | Eb | пауза | D",
                ],
            },
        ),
        _DemoArtifact(
            "vocal-part",
            enums.ArtifactType.PART,
            "Партия вокала",
            enums.ArtifactFormat.PDF,
            "Мелодия, текст, диапазон и дыхание.",
            enums.ArtifactStatus.DRAFT,
            0.91,
            instrument_or_student,
            {
                "kind": "notation",
                "title": "Вокал",
                "lines": [
                    "Куплет: спокойная тесситура",
                    "Припев: кульминация на верхней ноте",
                    "Bridge: проверить вход после паузы",
                ],
            },
        ),
        _DemoArtifact(
            "guitar-tab",
            enums.ArtifactType.TAB,
            "Гитара + TAB",
            enums.ArtifactFormat.PDF,
            "Рифф, аккорды и удобная аппликатура.",
            enums.ArtifactStatus.NEEDS_REVIEW,
            0.72,
            enums.ArtifactAudience.INSTRUMENT,
            {
                "kind": "notation",
                "title": "Гитара",
                "lines": [
                    "Intro: рифф на 3 струне",
                    "Припев: акценты второй гитары отмечены",
                    "TAB: такты 21-24 требуют проверки",
                ],
            },
        ),
        _DemoArtifact(
            "bass-part",
            enums.ArtifactType.PART,
            "Бас",
            enums.ArtifactFormat.PDF,
            "Басовая линия с ограничением диапазона.",
            enums.ArtifactStatus.READY,
            0.84,
            enums.ArtifactAudience.INSTRUMENT,
            {
                "kind": "notation",
                "title": "Бас",
                "lines": [
                    "Куплет: тоника и пятая",
                    "Припев: движение к Eb",
                    "Coda: оставить простую опору",
                ],
            },
        ),
        _DemoArtifact(
            "chord-chart",
            enums.ArtifactType.CHORDS,
            "Таблица аккордов",
            enums.ArtifactFormat.PDF,
            "Секции, такты и аккорды для быстрой репетиции.",
            enums.ArtifactStatus.DRAFT,
            0.86,
            enums.ArtifactAudience.ALL,
            {
                "kind": "text",
                "title": "Аккорды",
                "lines": [
                    "Intro: Gm | Eb | Bb | F",
                    "Verse: Bb | F | Gm | Eb",
                    "Chorus: Eb | Bb | F | Gm",
                ],
            },
        ),
        _DemoArtifact(
            "midi-full",
            enums.ArtifactType.MIDI,
            "Общий MIDI",
            enums.ArtifactFormat.MIDI,
            "Черновой MIDI для проверки партий.",
            enums.ArtifactStatus.DRAFT,
            0.76,
            enums.ArtifactAudience.ALL,
            {
                "kind": "midi",
                "title": "MIDI дорожки",
                "lines": [
                    "Vocal: 78 нот",
                    "Bass: 142 события",
                    "Keys: 4 слоя",
                    "Drums: groove + fills",
                ],
            },
        ),
        _DemoArtifact(
            "stems",
            enums.ArtifactType.STEM,
            "Аудиослои",
            enums.ArtifactFormat.WAV,
            "Вокал, барабаны, бас, гитара, клавиши и прочие слои.",
            enums.ArtifactStatus.READY,
            0.87,
            enums.ArtifactAudience.ALL,
            {
                "kind": "waveform",
                "title": "Аудиослои",
                "lines": ["Вокал", "Барабаны", "Бас", "Гитара", "Клавиши", "Прочее"],
            },
        ),
        _DemoArtifact(
            "minus-track",
            enums.ArtifactType.MINUS,
            "Минус",
            enums.ArtifactFormat.WAV,
            "Тренировочный микс без основного вокала.",
            enums.ArtifactStatus.READY,
            0.88,
            enums.ArtifactAudience.ALL,
            {
                "kind": "waveform",
                "title": "Минус",
                "lines": ["Intro", "Verse", "Chorus", "Bridge", "Chorus"],
            },
        ),
        _DemoArtifact(
            "click-track",
            enums.ArtifactType.CLICK,
            "Клик",
            enums.ArtifactFormat.WAV,
            "Клик с подсказками входов.",
            enums.ArtifactStatus.READY,
            0.93,
            enums.ArtifactAudience.ALL,
            {
                "kind": "waveform",
                "title": "Клик",
                "lines": ["Count-in 2 bars", "Bridge cue", "Final stop"],
            },
        ),
        _DemoArtifact(
            "practice-bass",
            enums.ArtifactType.PRACTICE,
            "Репетиционный трек без баса",
            enums.ArtifactFormat.WAV,
            "Трек для самостоятельной практики басиста.",
            enums.ArtifactStatus.READY,
            0.84,
            enums.ArtifactAudience.INSTRUMENT,
            {
                "kind": "waveform",
                "title": "Без баса",
                "lines": ["Vocals", "Drums", "Guitar", "Keys", "Click cue"],
            },
        ),
    ]

    if scenario is enums.Scenario.EDUCATION:
        items.append(
            _DemoArtifact(
                "student-pack",
                enums.ArtifactType.STUDENT,
                "Версия ученика",
                enums.ArtifactFormat.PDF,
                "Партия, подсказки и домашнее задание.",
                enums.ArtifactStatus.READY,
                0.86,
                enums.ArtifactAudience.STUDENT,
                {
                    "kind": "bundle",
                    "title": "Пакет ученика",
                    "lines": ["Full Score.pdf", "Chords.pdf", "MIDI.mid", "Minus.wav", "Click.wav"],
                },
            )
        )
        items.append(
            _DemoArtifact(
                "teacher-notes",
                enums.ArtifactType.TEACHER,
                "Заметки преподавателя",
                enums.ArtifactFormat.PDF,
                "Форма, сложные места, домашка и подсказки по уроку.",
                enums.ArtifactStatus.DRAFT,
                0.88,
                enums.ArtifactAudience.TEACHER,
                {
                    "kind": "text",
                    "title": "Заметки",
                    "lines": [
                        "Цель урока: уверенный переход в припев",
                        "Домашка: 8 тактов медленно с кликом",
                        "Проверить: Dm -> G",
                    ],
                },
            )
        )
    else:
        items.append(
            _DemoArtifact(
                "zip-pack",
                enums.ArtifactType.ZIP,
                "Общий ZIP",
                enums.ArtifactFormat.ZIP,
                "Все материалы Stage Pack одним пакетом.",
                enums.ArtifactStatus.READY,
                0.86,
                enums.ArtifactAudience.ALL,
                {
                    "kind": "bundle",
                    "title": "ZIP",
                    "lines": ["Full Score.pdf", "Chords.pdf", "MIDI.mid", "Minus.wav", "Click.wav"],
                },
            )
        )
    return items


BAND_ANALYSIS: dict[str, Any] = {
    "source": "demo",
    "title": "Late Train Home",
    "artist": "Demo Cover",
    "bpm": 104,
    "key": "Gm",
    "meter": "4/4",
    "duration": "3:42",
    "genre": "pop/rock",
    "summary": (
        "Песня держится на плотном припеве, вокальном hook и двух гитарных слоях. "
        "Для одного гитариста нужна адаптация."
    ),
    "confidenceByPart": {
        "Вокал": 0.91,
        "Барабаны": 0.88,
        "Бас": 0.84,
        "Гитара": 0.72,
        "Клавиши": 0.78,
    },
    "sections": [
        {
            "id": "intro",
            "label": "Intro",
            "startBar": 1,
            "endBar": 4,
            "note": "Гитарный рифф и короткий pickup.",
        },
        {
            "id": "verse-1",
            "label": "Куплет 1",
            "startBar": 5,
            "endBar": 20,
            "note": "Вокал ниже, бас играет простую опору.",
        },
        {
            "id": "chorus-1",
            "label": "Припев 1",
            "startBar": 21,
            "endBar": 36,
            "note": "Струнный слой и вторая гитара добавляют энергию.",
        },
        {
            "id": "bridge",
            "label": "Bridge",
            "startBar": 37,
            "endBar": 44,
            "note": "Пауза перед возвратом припева.",
        },
        {
            "id": "chorus-2",
            "label": "Припев 2",
            "startBar": 45,
            "endBar": 60,
            "note": "Концертную концовку можно усилить стопом.",
        },
    ],
    "chords": [
        {"bar": 1, "beat": 1, "chord": "Gm", "confidence": 0.92},
        {"bar": 3, "beat": 1, "chord": "Eb", "confidence": 0.87},
        {"bar": 5, "beat": 1, "chord": "Bb", "confidence": 0.89},
        {"bar": 7, "beat": 1, "chord": "F", "confidence": 0.9},
        {"bar": 21, "beat": 1, "chord": "Eb", "confidence": 0.74},
        {"bar": 23, "beat": 1, "chord": "Bb", "confidence": 0.81},
        {"bar": 37, "beat": 1, "chord": "Cm", "confidence": 0.68},
        {"bar": 45, "beat": 1, "chord": "Gm", "confidence": 0.86},
    ],
}

LESSON_ANALYSIS: dict[str, Any] = {
    "source": "demo",
    "title": "Warm Lights",
    "artist": "Demo Lesson",
    "bpm": 92,
    "key": "C",
    "meter": "4/4",
    "duration": "2:58",
    "genre": "acoustic pop",
    "summary": (
        "Песня удобна для урока гитары: простая форма, ясные аккорды, один сложный "
        "переход перед припевом."
    ),
    "confidenceByPart": {"Мелодия": 0.88, "Аккорды": 0.9, "Гитара": 0.82, "Бас": 0.75},
    "sections": [
        {
            "id": "lesson-intro",
            "label": "Intro",
            "startBar": 1,
            "endBar": 4,
            "note": "Можно пропустить для первой домашки.",
        },
        {
            "id": "lesson-verse",
            "label": "Куплет",
            "startBar": 5,
            "endBar": 20,
            "note": "Основной паттерн правой руки.",
        },
        {
            "id": "lesson-chorus",
            "label": "Припев",
            "startBar": 21,
            "endBar": 36,
            "note": "Подходит для первой цельной версии.",
        },
        {
            "id": "lesson-outro",
            "label": "Outro",
            "startBar": 37,
            "endBar": 40,
            "note": "Сокращенная концовка для урока.",
        },
    ],
    "chords": [
        {"bar": 1, "beat": 1, "chord": "C", "confidence": 0.94},
        {"bar": 3, "beat": 1, "chord": "Am", "confidence": 0.92},
        {"bar": 5, "beat": 1, "chord": "F", "confidence": 0.89},
        {"bar": 7, "beat": 1, "chord": "G", "confidence": 0.91},
        {"bar": 21, "beat": 1, "chord": "Dm", "confidence": 0.77},
        {"bar": 23, "beat": 1, "chord": "G", "confidence": 0.9},
    ],
}

ENSEMBLE_ANALYSIS: dict[str, Any] = {
    "source": "demo",
    "title": "School Hall",
    "artist": "Demo Ensemble",
    "bpm": 118,
    "key": "D",
    "meter": "4/4",
    "duration": "3:16",
    "genre": "school concert pop",
    "summary": (
        "Материал можно разложить на гитару, клавиши, перкуссию и вокальный ответ. "
        "В припеве нужен крупный сценический вид."
    ),
    "confidenceByPart": {"Вокал": 0.86, "Гитара": 0.8, "Клавиши": 0.83, "Перкуссия": 0.88},
    "sections": [
        {
            "id": "ensemble-intro",
            "label": "Intro",
            "startBar": 1,
            "endBar": 8,
            "note": "Клавиши дают вступление, перкуссия входит с 5 такта.",
        },
        {
            "id": "ensemble-verse",
            "label": "Куплет",
            "startBar": 9,
            "endBar": 24,
            "note": "Гитара держит аккорды, вокал отвечает короткими фразами.",
        },
        {
            "id": "ensemble-chorus",
            "label": "Припев",
            "startBar": 25,
            "endBar": 40,
            "note": "Можно добавить второй голос и хлопки.",
        },
        {
            "id": "ensemble-coda",
            "label": "Coda",
            "startBar": 41,
            "endBar": 48,
            "note": "Нелинейная концовка с повтором последней строки.",
        },
    ],
    "chords": [
        {"bar": 1, "beat": 1, "chord": "D", "confidence": 0.91},
        {"bar": 5, "beat": 1, "chord": "G", "confidence": 0.88},
        {"bar": 9, "beat": 1, "chord": "Bm", "confidence": 0.82},
        {"bar": 13, "beat": 1, "chord": "A", "confidence": 0.9},
        {"bar": 25, "beat": 1, "chord": "G", "confidence": 0.8},
        {"bar": 29, "beat": 1, "chord": "D", "confidence": 0.88},
        {"bar": 41, "beat": 1, "chord": "A/C#", "confidence": 0.67},
    ],
}


@dataclass(frozen=True, slots=True)
class _DemoProject:
    key: str
    name: str
    scenario: enums.Scenario
    goal: enums.ProcessingGoalId
    file_name: str
    duration_seconds: int
    quality: enums.UploadQuality
    analysis: dict[str, Any]
    versions: tuple[_DemoVersion, _DemoVersion]
    issues: tuple[_DemoIssue, ...]
    musicians: tuple[_DemoMusician, ...]
    recipients: tuple[_DemoRecipient, ...]
    cost_estimate: dict[str, Any]
    setup_snapshot: dict[str, Any]
    band_lineup: dict[str, Any] | None = None
    student_profile: dict[str, Any] | None = None
    teacher_profile: dict[str, Any] | None = None
    class_group: dict[str, Any] | None = None
    lesson: dict[str, Any] | None = None
    assignments: list[dict[str, Any]] | None = None
    retention_note: str = ""


def _cost(complexity: str, credits: int) -> dict[str, Any]:
    return {
        "tier": "multi_version" if complexity == "high" else "fast_draft",
        "complexity": complexity,
        "credits": credits,
        "notes": [
            "Оценка демонстрационная.",
            "Сложность зависит от длительности, аудиослоев, партий и повторной обработки.",
        ],
    }


BAND_RECIPIENTS: tuple[_DemoRecipient, ...] = (
    _DemoRecipient(
        "vocalist-1",
        "Оксана",
        enums.ShareRecipientRole.VOCALIST,
        "Вокал + текст",
        enums.ShareRecipientStatus.OPENED,
    ),
    _DemoRecipient(
        "guitarist-1",
        "Илья",
        enums.ShareRecipientRole.GUITARIST,
        "Гитара + TAB",
        enums.ShareRecipientStatus.NOT_ISSUED,
    ),
    _DemoRecipient(
        "bassist-1",
        "Марк",
        enums.ShareRecipientRole.BASSIST,
        "Бас + трек без баса",
        enums.ShareRecipientStatus.NOT_ISSUED,
    ),
    _DemoRecipient(
        "keys-1",
        "Лена",
        enums.ShareRecipientRole.KEYS,
        "Клавиши + струнный слой",
        enums.ShareRecipientStatus.NEEDS_FIX,
    ),
    _DemoRecipient(
        "drummer-1",
        "Даня",
        enums.ShareRecipientRole.DRUMMER,
        "Партия барабанов + клик",
        enums.ShareRecipientStatus.NOT_ISSUED,
    ),
)

EDUCATION_RECIPIENTS: tuple[_DemoRecipient, ...] = (
    _DemoRecipient(
        "student-1",
        "Аня",
        enums.ShareRecipientRole.STUDENT,
        "Партия ученика",
        enums.ShareRecipientStatus.NOT_ISSUED,
    ),
    _DemoRecipient(
        "student-2",
        "Миша",
        enums.ShareRecipientRole.STUDENT,
        "Клавиши easy",
        enums.ShareRecipientStatus.NOT_ISSUED,
    ),
    _DemoRecipient(
        "student-3",
        "Соня",
        enums.ShareRecipientRole.STUDENT,
        "Перкуссия",
        enums.ShareRecipientStatus.OPENED,
    ),
    _DemoRecipient(
        "teacher-1",
        "Преподаватель",
        enums.ShareRecipientRole.TEACHER,
        "Версия преподавателя",
        enums.ShareRecipientStatus.OPENED,
    ),
)


DEMO_PROJECTS: tuple[_DemoProject, ...] = (
    _DemoProject(
        key="band-demo",
        name="Late Train Home: подготовка к репетиции",
        scenario=enums.Scenario.BAND,
        goal=enums.ProcessingGoalId.BAND_REHEARSAL,
        file_name="late-train-home-demo.mp3",
        duration_seconds=222,
        quality=enums.UploadQuality.MEDIUM,
        analysis=BAND_ANALYSIS,
        versions=(
            _DemoVersion(
                "original",
                "Оригинал",
                enums.VersionKind.ORIGINAL,
                ["Исходная структура и найденные партии."],
            ),
            _DemoVersion(
                "band-main",
                "Для группы",
                enums.VersionKind.BAND,
                [
                    "Две гитары сведены в рабочий черновик.",
                    "Струнные отмечены для переноса на клавиши.",
                ],
            ),
        ),
        issues=(
            _DemoIssue(
                "issue-guitar-21",
                "Проверить гитарный акцент",
                "chorus-1",
                21,
                "Гитара",
                "Аудиослой содержит две гитары, TAB может смешивать партии.",
                enums.ReviewStatus.NEEDS_REVIEW,
                0.62,
            ),
            _DemoIssue(
                "issue-bridge-37",
                "Пауза перед bridge",
                "bridge",
                37,
                "Вся группа",
                "Найдено резкое падение энергии и возможная остановка.",
                enums.ReviewStatus.UNCERTAIN,
                0.58,
            ),
        ),
        musicians=(
            _DemoMusician(
                "vocalist-1",
                "Оксана",
                enums.MusicianRole.VOCAL,
                "ведущий вокал",
                "диапазон A2-G4",
                enums.MusicianLevel.ADVANCED,
            ),
            _DemoMusician(
                "guitarist-1",
                "Илья",
                enums.MusicianRole.GUITAR,
                "электрогитара, строй E",
                "играет один за две партии",
                enums.MusicianLevel.MIDDLE,
            ),
            _DemoMusician(
                "bassist-1",
                "Марк",
                enums.MusicianRole.BASS,
                "5 струн, нижняя E1",
                "слэп не играет",
                enums.MusicianLevel.MIDDLE,
            ),
            _DemoMusician(
                "keys-1",
                "Лена",
                enums.MusicianRole.KEYS,
                "2 слоя, Nord Stage",
                "закрывает струнные оригинала",
                enums.MusicianLevel.ADVANCED,
            ),
            _DemoMusician(
                "drummer-1",
                "Даня",
                enums.MusicianRole.DRUMS,
                "акустическая установка",
                "без двойной педали",
                enums.MusicianLevel.BEGINNER,
            ),
        ),
        recipients=BAND_RECIPIENTS,
        cost_estimate=_cost("medium", 7),
        band_lineup={
            "leadVocal": True,
            "vocalRange": "A2-E4",
            "guitars": 1,
            "guitarTuning": "Standard E",
            "capo": "нет",
            "bass": "4 strings",
            "keys": True,
            "keysCanCoverLayers": True,
            "drums": True,
            "backingVocals": False,
            "musicianLevel": "middle",
            "targetStyle": "плотнее и сценически",
        },
        setup_snapshot={
            "scenario": "band",
            "title": "Состав группы",
            "fields": [
                {"label": "Диапазон вокала", "value": "A2-E4"},
                {"label": "Гитаристов", "value": "1"},
                {"label": "Бас", "value": "4 струны"},
                {"label": "Клавиши", "value": "да, закрывают слои"},
                {"label": "Стиль версии", "value": "плотнее и сценически"},
            ],
        },
        retention_note="Исходник и результаты можно удалить из проекта.",
    ),
    _DemoProject(
        key="education-lesson-demo",
        name="Warm Lights: урок гитары",
        scenario=enums.Scenario.EDUCATION,
        goal=enums.ProcessingGoalId.LESSON_EASY,
        file_name="warm-lights-demo.m4a",
        duration_seconds=178,
        quality=enums.UploadQuality.GOOD,
        analysis=LESSON_ANALYSIS,
        versions=(
            _DemoVersion(
                "lesson-original", "Оригинал", enums.VersionKind.ORIGINAL, ["Исходная форма песни."]
            ),
            _DemoVersion(
                "lesson-easy",
                "Easy",
                enums.VersionKind.EASY,
                ["Оставлены куплет и припев.", "Ритм правой руки упрощен."],
            ),
        ),
        issues=(
            _DemoIssue(
                "issue-dm-21",
                "Переход Dm-G",
                "lesson-chorus",
                21,
                "Гитара",
                "Для начального уровня переход может быть слишком быстрым.",
                enums.ReviewStatus.NEEDS_REVIEW,
                0.7,
            ),
        ),
        musicians=(),
        recipients=EDUCATION_RECIPIENTS,
        cost_estimate=_cost("low", 4),
        student_profile={
            "name": "Аня",
            "instrument": "Гитара",
            "level": "начальный",
            "ageGroup": "10-12",
            "notationReading": "простые ноты",
            "chordKnowledge": "C, Am, F, G",
            "homeInstrument": "акустическая гитара",
        },
        teacher_profile={
            "name": "Оксана",
            "format": "индивидуальный урок",
            "focus": "переходы аккордов и ровный ритм",
        },
        lesson={
            "goal": "сыграть куплет и припев с кликом",
            "homeworkFormat": "короткий PDF + минус",
            "desiredDifficulty": "проще оригинала",
        },
        assignments=[
            {
                "id": "assignment-1",
                "title": "8 тактов припева с кликом",
                "recipient": "Аня",
                "status": "assigned",
            }
        ],
        setup_snapshot={
            "scenario": "education",
            "title": "Учебная задача",
            "fields": [
                {"label": "Инструмент ученика", "value": "гитара"},
                {"label": "Уровень", "value": "начальный"},
                {"label": "Цель урока", "value": "сыграть куплет и припев с кликом"},
                {"label": "Сложность результата", "value": "проще оригинала"},
                {"label": "Кому выдать", "value": "ученику и преподавателю"},
            ],
        },
        retention_note="Учебные материалы можно удалить после урока.",
    ),
    _DemoProject(
        key="education-ensemble-demo",
        name="School Hall: ансамбль учеников",
        scenario=enums.Scenario.EDUCATION,
        goal=enums.ProcessingGoalId.LESSON_ENSEMBLE,
        file_name="school-hall-demo.wav",
        duration_seconds=196,
        quality=enums.UploadQuality.MEDIUM,
        analysis=ENSEMBLE_ANALYSIS,
        versions=(
            _DemoVersion(
                "ensemble-original", "Оригинал", enums.VersionKind.ORIGINAL, ["Исходная песня."]
            ),
            _DemoVersion(
                "ensemble-main",
                "Ансамблевая",
                enums.VersionKind.ENSEMBLE,
                ["Песня разложена на 4 учебные партии.", "Coda отмечена для проверки."],
            ),
        ),
        issues=(
            _DemoIssue(
                "issue-coda-41",
                "Повтор в coda",
                "ensemble-coda",
                41,
                "Ансамбль",
                "Найдена нелинейная концовка с повтором последней строки.",
                enums.ReviewStatus.UNCERTAIN,
                0.61,
            ),
            _DemoIssue(
                "issue-vocal-25",
                "Второй голос в припеве",
                "ensemble-chorus",
                25,
                "Вокал",
                "Интервал может быть сложным для учеников.",
                enums.ReviewStatus.NEEDS_REVIEW,
                0.69,
            ),
        ),
        musicians=(
            _DemoMusician(
                "student-1",
                "Аня",
                enums.MusicianRole.GUITAR,
                "акустическая гитара",
                "читает простые ноты",
                enums.MusicianLevel.BEGINNER,
            ),
            _DemoMusician(
                "student-2",
                "Миша",
                enums.MusicianRole.KEYS,
                "цифровое пианино",
                "октава без растяжки",
                enums.MusicianLevel.BEGINNER,
            ),
            _DemoMusician(
                "student-3",
                "Соня",
                enums.MusicianRole.DRUMS,
                "перкуссия",
                "без установки",
                enums.MusicianLevel.MIDDLE,
            ),
        ),
        recipients=EDUCATION_RECIPIENTS,
        cost_estimate=_cost("high", 10),
        student_profile={
            "name": "Группа 5Б",
            "instrument": "ансамбль",
            "level": "средний",
            "ageGroup": "11-13",
            "notationReading": "простые ноты",
            "chordKnowledge": "D, G, A, Bm",
            "homeInstrument": "гитара или клавиши",
        },
        teacher_profile={
            "name": "Оксана",
            "format": "школьный ансамбль",
            "focus": "сценическая версия и роли учеников",
        },
        class_group={
            "name": "Ансамбль 5Б",
            "studentsCount": 4,
            "instruments": ["гитара", "клавиши", "перкуссия", "вокал"],
        },
        lesson={
            "goal": "подготовить номер к школьному концерту",
            "homeworkFormat": "партии по ученикам + общий минус",
            "desiredDifficulty": "близко к оригиналу",
        },
        assignments=[
            {
                "id": "assignment-ensemble-1",
                "title": "Гитара: аккорды припева",
                "recipient": "Аня",
                "status": "in_progress",
            },
            {
                "id": "assignment-ensemble-2",
                "title": "Клавиши: hook припева",
                "recipient": "Миша",
                "status": "assigned",
            },
            {
                "id": "assignment-ensemble-3",
                "title": "Перкуссия: пульс и стоп",
                "recipient": "Соня",
                "status": "ready_for_concert",
            },
        ],
        setup_snapshot={
            "scenario": "education",
            "title": "Ансамблевая задача",
            "fields": [
                {"label": "Инструменты", "value": "гитара, клавиши, перкуссия, вокал"},
                {"label": "Количество партий", "value": "4"},
                {"label": "Цель урока", "value": "подготовить номер к школьному концерту"},
                {"label": "Сложность результата", "value": "близко к оригиналу"},
                {"label": "Кому выдать", "value": "ансамблю и преподавателю"},
            ],
        },
        retention_note="Материалы можно удалить после концерта.",
    ),
)


async def _ensure_owner(repos: Repositories, contact: str) -> models.User:
    existing = await repos.users.get_by_contact(contact)
    if existing is not None:
        return existing
    return await repos.users.create(
        UserCreate(contact=contact), entity_id=demo_uuid("user", contact)
    )


async def _seed_one(repos: Repositories, owner: models.User, demo: _DemoProject) -> models.Project:
    project_id = demo_uuid("project", demo.key)
    existing = await repos.projects.get(project_id)
    if existing is not None:
        return existing

    project = await repos.projects.create(
        ProjectCreate(
            user_id=owner.id,
            name=demo.name,
            scenario=demo.scenario,
            processing_goal_id=demo.goal,
            last_opened_at=DEMO_MOMENT,
            setup_snapshot=demo.setup_snapshot,
            band_lineup=demo.band_lineup,
            student_profile=demo.student_profile,
            teacher_profile=demo.teacher_profile,
            class_group=demo.class_group,
            lesson=demo.lesson,
            assignments=demo.assignments,
            analysis=demo.analysis,
            cost_estimate=demo.cost_estimate,
            consent_accepted=True,
            consent_version_id=CONSENT_VERSION_ID,
            consent_text=CONSENT_TEXT,
            consent_accepted_at=DEMO_MOMENT,
            retention_note=demo.retention_note,
        ),
        entity_id=project_id,
    )

    # Загрузка без ключа объекта: за демо нет файла, и делать вид, что есть,
    # нельзя — первая же попытка выдачи упрется в отсутствующий объект.
    await repos.uploads.create(
        UploadCreate(
            project_id=project.id,
            file_name=demo.file_name,
            file_format=enums.UploadFormat.DEMO,
            duration_seconds=demo.duration_seconds,
            quality=demo.quality,
            source_note="Демо без реального аудиофайла.",
        )
    )

    # Версии разнесены по времени на минуту: в моках у них одинаковая отметка,
    # но порядок версий — это то, по чему строится история и откат, и
    # одинаковое время делает его неопределенным.
    created_versions: list[models.Version] = []
    for index, item in enumerate(demo.versions):
        created_versions.append(
            await repos.versions.create(
                VersionCreate(
                    project_id=project.id,
                    label=item.label,
                    kind=item.kind,
                    created_by="AI-директор",
                    status=enums.VersionStatus.NEEDS_REVIEW,
                    created_at=DEMO_MOMENT + timedelta(minutes=index),
                    changes=item.changes,
                    parent_version_id=created_versions[index - 1].id if index else None,
                )
            )
        )
    await repos.session.flush()
    current = created_versions[-1]
    await repos.projects.update(project.id, ProjectPatch(current_version_id=current.id))

    job = await repos.jobs.create(
        JobCreate(
            project_id=project.id,
            idempotency_key=f"demo-{demo.key}",
            status=enums.JobStatus.READY,
            progress_percent=100,
            warnings=list(PROCESSING_WARNINGS),
        )
    )
    await repos.session.flush()
    for position, (step_key, label, detail) in enumerate(PROCESSING_STEPS):
        await repos.job_steps.create(
            JobStepCreate(
                job_id=job.id,
                step_key=step_key,
                label=label,
                # Шаг структуры в моках помечен предупреждением: демо честно
                # показывает, что разбор формы требует проверки руками.
                status=(
                    enums.JobStepStatus.WARNING
                    if step_key == "structure"
                    else enums.JobStepStatus.DONE
                ),
                detail=detail,
                position=position,
            )
        )

    for artifact in _artifacts(demo.scenario):
        await repos.artifacts.create(
            ArtifactCreate(
                project_id=project.id,
                version_id=current.id,
                artifact_type=artifact.artifact_type,
                name=artifact.name,
                artifact_format=artifact.artifact_format,
                description=artifact.description,
                status=artifact.status,
                confidence=artifact.confidence,
                audience=artifact.audience,
                preview=artifact.preview,
            )
        )

    for issue in demo.issues:
        await repos.review_issues.create(
            ReviewIssueCreate(
                project_id=project.id,
                title=issue.title,
                version_id=current.id,
                section_id=issue.section_id,
                bar=issue.bar,
                part=issue.part,
                reason=issue.reason,
                status=issue.status,
                confidence=issue.confidence,
            )
        )

    for position, musician in enumerate(demo.musicians):
        await repos.musicians.create(
            MusicianCreate(
                project_id=project.id,
                name=musician.name,
                role=musician.role,
                level=musician.level,
                instrument_note=musician.instrument_note,
                constraint_note=musician.constraint_note,
                position=position,
            )
        )

    for position, recipient in enumerate(demo.recipients):
        await repos.share_recipients.create(
            ShareRecipientCreate(
                project_id=project.id,
                name=recipient.name,
                role=recipient.role,
                material=recipient.material,
                status=recipient.status,
                position=position,
            )
        )

    await repos.session.flush()
    return project


async def seed_demo_projects(
    session: AsyncSession, *, owner_contact: str = DEMO_OWNER_CONTACT
) -> list[models.Project]:
    """Кладет в базу три демо-проекта. Повторный запуск ничего не дублирует."""
    repos = Repositories(session)
    owner = await _ensure_owner(repos, owner_contact)
    return [await _seed_one(repos, owner, demo) for demo in DEMO_PROJECTS]


async def _main() -> None:
    async with session_scope() as session:
        projects = await seed_demo_projects(session)
    for project in projects:
        print(f"{project.id}  {project.name}")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
