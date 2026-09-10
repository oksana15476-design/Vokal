"""Схемы задания обработки.

Прогресс читается поллингом. Realtime-канал появится позже, но контракт от
этого не изменится: ответ задания самодостаточен, и клиенту не нужно
складывать состояние из нескольких источников.

`poll_after_ms` возвращает сервер, а не выбирает клиент. Иначе интервал
опроса становится случайной константой в интерфейсе, и очередь получает либо
шквал запросов, либо задержку показа готового результата.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import JobStatus, ProcessingGoalId, ProcessingStepStatus


class ProcessingStepOut(ApiModel):
    """Шаг обработки."""

    id: str
    label: str
    status: ProcessingStepStatus
    detail: str = Field(description="Что происходит на шаге или почему он пропущен")


class ProcessingJobOut(ApiModel):
    """Задание обработки: статус, шаги, прогресс."""

    id: str
    project_id: str
    status: JobStatus
    steps: list[ProcessingStepOut]
    warnings: list[str]
    progress_percent: int = Field(ge=0, le=100)
    error_code: str | None = Field(
        default=None,
        description="Код ошибки обработки, например failed_separation. Пусто, если ошибки нет.",
    )
    retry_count: int = Field(default=0, ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    poll_after_ms: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Через сколько миллисекунд спрашивать снова. Пусто у завершенного задания: "
            "спрашивать больше не о чем."
        ),
    )


class JobCreateRequest(ApiModel):
    """Запуск обработки.

    Идемпотентность обеспечивается заголовком `Idempotency-Key`, а не телом:
    повторный запуск обработки — это повторное списание стоимости.
    """

    goal_id: ProcessingGoalId | None = Field(
        default=None,
        description="Цель обработки. Пусто — берется цель проекта.",
    )
    force_restart: bool = Field(
        default=False,
        description="Запустить заново, даже если результат уже есть. Стоимость списывается снова.",
    )


class JobRetryRequest(ApiModel):
    """Повтор упавшего задания."""

    from_step_id: str | None = Field(
        default=None,
        description="С какого шага повторять. Пусто — с первого невыполненного.",
    )
