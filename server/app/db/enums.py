"""Перечисления домена.

Значения повторяют литеральные типы из `src/domain/types.ts`: база обязана
поддержать ту же модель, что уже описана на фронтенде.

Одно осознанное расхождение — **латиница вместо русских подписей**. В
`types.ts` роль и уровень музыканта записаны по-русски (`"гитара"`,
`"средний"`), а тот же уровень в `BandLineup` уже латиницей
(`"beginner" | "middle" | "advanced"`). Держать в базе два написания одного
понятия нельзя, а выбирать русское — значит сделать ключом данных
отображаемую подпись. Ровно на этом продукт один раз уже обжегся: сервис искал
настройки по русским подписям, и переименование подписи копирайтером молча
подменяло значение пользователя (комментарий к `BandSetup` в `types.ts`).
Поэтому в базе лежат устойчивые латинские ключи, а подписи живут в слое
представления.
"""

from __future__ import annotations

from enum import StrEnum


class Scenario(StrEnum):
    BAND = "band"
    EDUCATION = "education"


class ProcessingGoalId(StrEnum):
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


class UploadFormat(StrEnum):
    MP3 = "MP3"
    WAV = "WAV"
    FLAC = "FLAC"
    M4A = "M4A"
    DEMO = "DEMO"


class UploadQuality(StrEnum):
    GOOD = "good"
    MEDIUM = "medium"
    LOW = "low"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"


class JobStepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    WARNING = "warning"
    ERROR = "error"
    # Шаг, которого на этом пути не будет вовсе. Отдельный статус нужен, чтобы
    # несделанное не выдавалось за «готово» (см. `types.ts`).
    SKIPPED = "skipped"


class VersionKind(StrEnum):
    ORIGINAL = "original"
    BAND = "band"
    EASY = "easy"
    ORIGINAL_LIKE = "original-like"
    ADVANCED = "advanced"
    CONCERT = "concert"
    ENSEMBLE = "ensemble"
    AFTER_REHEARSAL = "after-rehearsal"
    AFTER_LESSON = "after-lesson"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    DISTRIBUTED = "distributed"


class ArtifactType(StrEnum):
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


class ArtifactFormat(StrEnum):
    PDF = "PDF"
    MIDI = "MIDI"
    WAV = "WAV"
    ZIP = "ZIP"
    MUSICXML = "MusicXML"
    VIEW = "VIEW"


class ArtifactStatus(StrEnum):
    READY = "ready"
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    REBUILD_REQUIRED = "rebuild_required"
    PENDING = "pending"


class ArtifactAudience(StrEnum):
    ALL = "all"
    BAND = "band"
    TEACHER = "teacher"
    STUDENT = "student"
    INSTRUMENT = "instrument"


class ReviewStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    CHECKED = "checked"
    FIXED = "fixed"
    UNCERTAIN = "uncertain"
    ACCEPTED_FOR_REHEARSAL = "accepted_for_rehearsal"


class MusicianRole(StrEnum):
    VOCAL = "vocal"
    GUITAR = "guitar"
    BASS = "bass"
    KEYS = "keys"
    DRUMS = "drums"
    BACKING_VOCAL = "backing_vocal"


class MusicianLevel(StrEnum):
    BEGINNER = "beginner"
    MIDDLE = "middle"
    ADVANCED = "advanced"


class ShareRecipientRole(StrEnum):
    VOCALIST = "vocalist"
    GUITARIST = "guitarist"
    BASSIST = "bassist"
    KEYS = "keys"
    DRUMMER = "drummer"
    TEACHER = "teacher"
    STUDENT = "student"
    PARENT = "parent"


class ShareRecipientStatus(StrEnum):
    NOT_ISSUED = "not_issued"
    ISSUED = "issued"
    OPENED = "opened"
    NEEDS_FIX = "needs_fix"


class DeletionState(StrEnum):
    """Состояние удаления исходника или результатов.

    Флага «удалено» недостаточно. `DELETION_AND_RETENTION_DESIGN.md` требует
    подтвержденного статуса: пока объектное хранилище не отчиталось, показывать
    «удалено» нельзя, а исчерпание попыток — инцидент, а не строка в логе.
    """

    PRESENT = "present"
    PURGE_REQUESTED = "purge_requested"
    PURGED = "purged"
    PURGE_FAILED = "purge_failed"
