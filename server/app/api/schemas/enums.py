"""Перечисления контракта. Повторяют литеральные типы `src/domain/types.ts`.

Одно осознанное расхождение с фронтендом — **латинские ключи вместо русских
подписей**. В `types.ts` роль и уровень музыканта записаны по-русски
(`"гитара"`, `"средний"`), а тот же уровень в `BandLineup` уже латиницей
(`"beginner" | "middle" | "advanced"`). Через границу API нельзя гонять
отображаемую подпись как ключ данных: продукт уже обжигался ровно на этом —
сервис искал настройки по русским подписям, и переименование подписи
копирайтером молча подменяло значение пользователя (комментарий к `BandSetup`
в `types.ts`).

Поэтому в контракте — устойчивые латинские ключи, подписи живут в слое
представления. Тот же выбор сделан в `app/db/enums.py`, так что API и база
говорят на одном языке. Таблица соответствия — в `docs/api/README.md`,
и фронтенду предстоит ее применить: это развилка, вынесенная владельцу.

Свободные строки (тональность, строй, стиль, домашнее задание) намеренно
остаются строками: там нет закрытого списка, и придумывать его на сервере
значило бы запретить пользователю его собственные слова.
"""

from __future__ import annotations

from enum import Enum


class Scenario(str, Enum):
    """Сценарий работы: подготовка группы или урок."""

    BAND = "band"
    EDUCATION = "education"


class ProcessingGoalId(str, Enum):
    """Цель обработки. Префикс кода связан со сценарием и проверяется схемой."""

    BAND_ANALYSIS = "band-analysis"
    BAND_REHEARSAL = "band-rehearsal"
    BAND_PERFORMANCE = "band-performance"
    BAND_MINUS = "band-minus"
    BAND_PARTS = "band-parts"
    BAND_TRANSPOSE = "band-transpose"
    BAND_ADAPT_LINEUP = "band-adapt-lineup"
    BAND_BOOST = "band-boost"
    LESSON_ANALYSIS = "lesson-analysis"
    LESSON_EASY = "lesson-easy"
    LESSON_ORIGINAL = "lesson-original"
    LESSON_ADVANCED = "lesson-advanced"
    LESSON_CONCERT = "lesson-concert"
    LESSON_ENSEMBLE = "lesson-ensemble"
    LESSON_HOMEWORK = "lesson-homework"
    LESSON_PRACTICE_TRACKS = "lesson-practice-tracks"


# Цель обязана соответствовать сценарию: «урок» с целью группы — не опечатка
# пользователя, а разошедшееся состояние экрана.
GOAL_PREFIX_BY_SCENARIO: dict[Scenario, str] = {
    Scenario.BAND: "band-",
    Scenario.EDUCATION: "lesson-",
}


class UploadFormat(str, Enum):
    """Формат исходника. `DEMO` — у демо-проектов, за ним нет файла."""

    MP3 = "MP3"
    WAV = "WAV"
    FLAC = "FLAC"
    M4A = "M4A"
    DEMO = "DEMO"


class UploadQuality(str, Enum):
    GOOD = "good"
    MEDIUM = "medium"
    LOW = "low"


class UploadState(str, Enum):
    """Состояние загрузки.

    `awaiting_file` отделено от `stored`: запись о загрузке заводится до того,
    как файл доехал, и показывать «файл принят» в этот момент нельзя.
    """

    AWAITING_FILE = "awaiting_file"
    STORED = "stored"
    REJECTED = "rejected"
    PURGED = "purged"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"


class ProcessingStepStatus(str, Enum):
    """Статус шага обработки.

    `skipped` — шаг не выполняется на этом пути, результата у него не будет.
    Отдельный статус нужен, чтобы несделанное не выдавалось за «готово».
    """

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class AnalysisSource(str, Enum):
    """Откуда взят разбор.

    Промежуточного состояния нет намеренно: подставлять чужой разбор к своему
    файлу нельзя, пустой разбор честнее.
    """

    DEMO = "demo"
    NONE = "none"


class VersionKind(str, Enum):
    ORIGINAL = "original"
    BAND = "band"
    EASY = "easy"
    ORIGINAL_LIKE = "original-like"
    ADVANCED = "advanced"
    CONCERT = "concert"
    ENSEMBLE = "ensemble"
    AFTER_REHEARSAL = "after-rehearsal"
    AFTER_LESSON = "after-lesson"


class VersionStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    DISTRIBUTED = "distributed"


class ArtifactType(str, Enum):
    SCORE = "score"
    PART = "part"
    TAB = "tab"
    CHORDS = "chords"
    LYRICS = "lyrics"
    MIDI = "midi"
    STEM = "stem"
    MINUS = "minus"
    CLICK = "click"
    PRACTICE = "practice"
    TEACHER = "teacher"
    STUDENT = "student"
    ZIP = "zip"


class ArtifactFormat(str, Enum):
    PDF = "PDF"
    MIDI = "MIDI"
    WAV = "WAV"
    ZIP = "ZIP"
    MUSICXML = "MusicXML"
    VIEW = "VIEW"


class ArtifactStatus(str, Enum):
    READY = "ready"
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    REBUILD_REQUIRED = "rebuild_required"
    PENDING = "pending"


class ArtifactAudience(str, Enum):
    """Кому предназначен материал. Разным ролям выдается разное."""

    ALL = "all"
    BAND = "band"
    TEACHER = "teacher"
    STUDENT = "student"
    INSTRUMENT = "instrument"


class ArtifactPreviewKind(str, Enum):
    NOTATION = "notation"
    WAVEFORM = "waveform"
    MIDI = "midi"
    BUNDLE = "bundle"
    TEXT = "text"


class ReviewStatus(str, Enum):
    NEEDS_REVIEW = "needs_review"
    CHECKED = "checked"
    FIXED = "fixed"
    UNCERTAIN = "uncertain"
    ACCEPTED_FOR_REHEARSAL = "accepted_for_rehearsal"


class DirectorActionId(str, Enum):
    """Детерминированная команда директора.

    Список закрытый: LLM выбирает действие из него, а не правит материалы
    напрямую. Незнакомый код — `422`, а не попытка угадать намерение.
    """

    TRANSPOSE_DOWN_2 = "transpose-down-2"
    MERGE_GUITARS = "merge-guitars"
    MOVE_STRINGS_TO_KEYS = "move-strings-to-keys"
    SIMPLIFY_DRUMS = "simplify-drums"
    BEGINNER_BASS = "beginner-bass"
    BOOST_CHORUS = "boost-chorus"
    PRACTICE_WITHOUT_BASS = "practice-without-bass"
    EDUCATION_VERSION = "education-version"
    ADVANCED_STUDENT_PART = "advanced-student-part"
    STUDENT_ENSEMBLE = "student-ensemble"
    LESSON_ANALYSIS = "lesson-analysis"


class DirectorSuggestionScope(str, Enum):
    BAND = "band"
    EDUCATION = "education"
    BOTH = "both"


class DirectorSuggestionImpact(str, Enum):
    ARRANGEMENT = "arrangement"
    EDUCATION = "education"
    EXPORT = "export"
    REVIEW = "review"


class ChatAuthor(str, Enum):
    USER = "user"
    DIRECTOR = "director"


class MusicianRole(str, Enum):
    VOCAL = "vocal"
    GUITAR = "guitar"
    BASS = "bass"
    KEYS = "keys"
    DRUMS = "drums"
    BACKING_VOCAL = "backing_vocal"


class MusicianLevel(str, Enum):
    BEGINNER = "beginner"
    MIDDLE = "middle"
    ADVANCED = "advanced"


class BassStrings(str, Enum):
    FOUR = "4_strings"
    FIVE = "5_strings"


class StudentLevel(str, Enum):
    STARTER = "starter"
    MIDDLE = "middle"
    STRONG = "strong"


class NotationReading(str, Enum):
    NONE = "none"
    SIMPLE = "simple"
    CONFIDENT = "confident"


class TeacherFormat(str, Enum):
    INDIVIDUAL = "individual"
    GROUP = "group"
    SCHOOL_ENSEMBLE = "school_ensemble"


class LessonDifficulty(str, Enum):
    EASIER = "easier"
    ORIGINAL_LIKE = "original_like"
    HARDER = "harder"


class AssignmentStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    ANALYZED = "analyzed"
    READY_FOR_CONCERT = "ready_for_concert"


class ShareRecipientRole(str, Enum):
    VOCALIST = "vocalist"
    GUITARIST = "guitarist"
    BASSIST = "bassist"
    KEYS = "keys"
    DRUMMER = "drummer"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"


class ShareRecipientStatus(str, Enum):
    NOT_ISSUED = "not_issued"
    ISSUED = "issued"
    OPENED = "opened"
    NEEDS_FIX = "needs_fix"


class ShareLinkStatus(str, Enum):
    """Состояние выданной ссылки.

    `revoked` обязателен: `docs/DELETION_AND_RETENTION_DESIGN.md` требует, чтобы
    удаление результатов гасило уже выданные ссылки. Без отзыва обещание
    «удалено» ложно для всех, кому ссылку уже отправили.
    """

    ACTIVE = "active"
    STALE = "stale"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ExportBundleStatus(str, Enum):
    READY = "ready"
    STALE = "stale"
    PENDING = "pending"


class CostTier(str, Enum):
    FAST_DRAFT = "fast_draft"
    ACCURATE = "accurate"
    MULTI_VERSION = "multi_version"


class CostComplexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DeletionState(str, Enum):
    """Состояние удаления исходника или результатов.

    Флага «удалено» недостаточно: пока хранилище не отчиталось, показывать
    «удалено» нельзя. Исчерпание попыток — инцидент, отсюда `purge_failed`
    отдельным состоянием, а не молчанием.
    """

    PRESENT = "present"
    PURGE_REQUESTED = "purge_requested"
    PURGED = "purged"
    PURGE_FAILED = "purge_failed"
