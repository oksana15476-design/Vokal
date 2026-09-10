"""Схемы версий аранжировки и отката.

Версия хранит снимок материалов (`artifacts_snapshot`) — состояние на момент
выхода из версии. Без снимка откат вернул бы структуру песни, но оставил
материалы от более поздней версии, и пользователь получил бы ноты, которых в
этой версии не было.

Откат возможен на **любую** глубину: целью служит любая версия проекта, а не
только родительская. Поэтому цель — идентификатор в адресе, а не «шаг назад».
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.artifacts import ArtifactOut
from app.api.schemas.common import ApiModel
from app.api.schemas.enums import VersionKind, VersionStatus


class ArrangementVersionOut(ApiModel):
    """Версия аранжировки."""

    id: str
    label: str
    kind: VersionKind
    parent_version_id: str | None = Field(
        default=None, description="Родительская версия. Пусто у исходной."
    )
    created_at: datetime
    created_by: str = Field(description="Кто создал: человек или действие директора")
    status: VersionStatus
    changes: list[str] = Field(description="Что изменилось относительно родителя")
    artifacts_snapshot: list[ArtifactOut] | None = Field(
        default=None,
        description="Состояние материалов на момент выхода из версии. По нему делается откат.",
    )
    is_current: bool = Field(description="Выбрана ли версия сейчас")


class VersionListResponse(ApiModel):
    items: list[ArrangementVersionOut]
    current_version_id: str | None = None


class VersionSelectRequest(ApiModel):
    """Переключение текущей версии без создания новой."""

    comment: str | None = Field(default=None, max_length=2000)


class VersionRollbackRequest(ApiModel):
    """Откат на версию, указанную в адресе."""

    comment: str | None = Field(default=None, max_length=2000)
    label: str | None = Field(
        default=None,
        max_length=200,
        description="Подпись новой версии. Пусто — соберется из подписи целевой версии.",
    )


class VersionRollbackResponse(ApiModel):
    """Результат отката.

    Новая версия, а не переписанная история: откат — такое же событие, как
    правка, и он обязан остаться в списке версий. Иначе по истории нельзя
    понять, почему материалы вдруг стали прежними.
    """

    version: ArrangementVersionOut
    restored_from_version_id: str
    restored_artifacts: list[ArtifactOut]
    stale_artifact_ids: list[str] = Field(
        default_factory=list,
        description="Материалы, которые придется пересобрать: снимка для них не было",
    )
