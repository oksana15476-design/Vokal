"""Статусы конвейера.

Значения повторяют `ProcessingStepStatus` и `ProcessingJob["status"]` из
`src/domain/types.ts` и `JobStepStatus`/`JobStatus` из слоя хранения. Свои
перечисления, а не импорт из `app.db.enums`, по одной причине: конвейер —
доменный слой и не должен зависеть от того, как устроена база. Расхождение
ловит тест `test_step_statuses_match_the_frontend_contract`: он падает, если
списки разъедутся, и это дешевле, чем связывать слои.

Форма записи — `StrEnum`, а в `app.db.enums` пока `str, Enum`. Расхождение
косметическое (ruff требует первую форму), на значения оно не влияет, и
совпадение значений закреплено тестом.
"""

from __future__ import annotations

from enum import StrEnum


class StepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    WARNING = "warning"
    ERROR = "error"
    # Шаг, которого на этом пути не будет вовсе: провайдер не подключен или
    # не выполняется шаг, без которого этот не запускается. Отдельный статус
    # нужен, чтобы несделанное не выглядело как «готово».
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"


class RetryScope(StrEnum):
    """Что имеет смысл перезапускать после сбоя.

    Без этого поля интерфейс не может отличить «нажмите повтор» от «повтор не
    поможет, нужен другой файл или подключенный провайдер», и кнопка «Повторить
    шаг» превращается в обещание, которое нечем исполнить.
    """

    NONE = "none"
    STEP = "step"
    RUN = "run"


class ArtifactKind(StrEnum):
    """Вид материала. Повторяет `ArtifactType` из `src/domain/types.ts`."""

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
