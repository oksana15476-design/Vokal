"""Схемы удаления исходника и результатов.

Две операции, а не одна с параметром: у них разный смысл и разные последствия.
`delete-source` убирает исходную запись, но оставляет разбор и материалы;
`delete-results` убирает материалы и гасит все выданные ссылки. Слить их в один
адрес с флагом — верный способ однажды выполнить не ту.

Удаление — **задача с подтвержденным статусом**, а не флаг
(`docs/DELETION_AND_RETENTION_DESIGN.md`). Пока хранилище не отчиталось,
пользователю показывается «удаление выполняется», а не «удалено». Повторный
запуск на уже удаленном проекте завершается успехом: операция идемпотентна.

Обе операции необратимы, поэтому запускаются только явным подтверждением —
пустое тело их не запускает.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import DeletionState


class DeletionRequest(ApiModel):
    """Запуск необратимого удаления."""

    confirm: bool = Field(
        description=(
            "Явное подтверждение. Без него операция не запускается: восстановить "
            "удаленное будет нечем."
        )
    )
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Причина для аудит-лога. Не обязательна.",
    )

    @model_validator(mode="after")
    def _must_confirm(self) -> DeletionRequest:
        if not self.confirm:
            raise ValueError("Необратимая операция требует подтверждения: confirm = true.")
        return self


class DeletionTargetStatus(ApiModel):
    """Состояние одной из двух операций удаления."""

    state: DeletionState
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = Field(
        default=None,
        description=(
            "Причина, по которой удаление не выполнено. Исчерпание попыток — инцидент: "
            "неисполненное обещание удаления, а не строка в логе."
        ),
    )


class DeletionStatusOut(ApiModel):
    """Состояние удаления по проекту целиком."""

    project_id: str
    source: DeletionTargetStatus
    results: DeletionTargetStatus
    retention_note: str = Field(
        description=(
            "Что сохраняется после удаления, дословно для показа: метаданные проекта, "
            "аудит-лог, события биллинга."
        )
    )


class DeletionAcceptedOut(ApiModel):
    """Ответ на запуск удаления.

    Возвращается `202`: задача принята. `200` здесь означал бы «уже удалено», а
    подтверждения от хранилища еще нет.
    """

    project_id: str
    state: DeletionState
    requested_at: datetime
    status_url: str = Field(description="Где спрашивать статус удаления")
    revoked_links_count: int | None = Field(
        default=None,
        description="Сколько выданных ссылок погашено. Только для удаления результатов.",
    )


class DataRetentionStateOut(ApiModel):
    """Состояние хранения в карточке проекта.

    Булевы значения оставлены для совместимости с `types.ts`, но истина —
    в `source_state` и `results_state`: до подтверждения хранилища «удалено»
    показывать нельзя.
    """

    source_deleted: bool
    results_deleted: bool
    source_state: DeletionState
    results_state: DeletionState
    retention_note: str
