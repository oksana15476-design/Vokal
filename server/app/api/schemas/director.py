"""Схемы AI-директора.

Главное ограничение контракта: клиент присылает **код действия из закрытого
списка**, а не текст правки. Незнакомый код — отказ `422`, а не попытка
угадать намерение. Причина в архитектуре: музыкальные изменения применяет
детерминированный слой, LLM только объясняет и выбирает действие. Свободный
текст живет в разговоре и превращается в действие тем же путем.

Два адреса вместо одного: одно действие и сборка версии сразу из нескольких.
Разница не в удобстве, а в истории версий. Пять действий по одному дадут пять
версий и пять пересборок материалов; те же пять действий пакетом дают одну
версию с перечнем изменений — то, что и нужно перед репетицией.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import (
    ArtifactType,
    ChatAuthor,
    DirectorActionId,
    DirectorSuggestionImpact,
    DirectorSuggestionScope,
    VersionKind,
)
from app.api.schemas.versions import ArrangementVersionOut


class DirectorSuggestionOut(ApiModel):
    """Предложение директора: описание и код действия за ним."""

    id: str
    title: str
    description: str
    action_id: DirectorActionId
    scenario: DirectorSuggestionScope
    impact: DirectorSuggestionImpact


class DirectorSuggestionListResponse(ApiModel):
    items: list[DirectorSuggestionOut]


class DirectorActionRequest(ApiModel):
    """Одно действие директора."""

    action_id: DirectorActionId
    base_version_id: str = Field(
        description=(
            "Версия, к которой применяется действие. Обязательна: без нее правка "
            "легла бы на версию, которую пользователь уже не видит на экране."
        )
    )
    comment: str | None = Field(default=None, max_length=2000)


class DirectorActionBatchRequest(ApiModel):
    """Сборка одной версии сразу из нескольких действий."""

    action_ids: list[DirectorActionId] = Field(
        min_length=1,
        max_length=20,
        description="Порядок значим: действия применяются в нем",
    )
    base_version_id: str
    label: str | None = Field(
        default=None, max_length=200, description="Подпись будущей версии"
    )
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("action_ids")
    @classmethod
    def _no_duplicates(cls, value: list[DirectorActionId]) -> list[DirectorActionId]:
        # Повтор действия в одном пакете почти всегда означает разошедшийся
        # экран, а не намерение применить правку дважды.
        if len(set(value)) != len(value):
            raise ValueError("Одно и то же действие указано дважды.")
        return value


class DirectorActionResultOut(ApiModel):
    """Что сделало действие. Повторяет `DirectorActionResult` из `types.ts`."""

    version_label: str
    version_kind: VersionKind
    history_title: str = Field(description="Строка для истории изменений")
    changes: list[str]
    stale_artifact_types: list[ArtifactType] = Field(
        description="Типы материалов, которые придется пересобрать после этого действия"
    )


class DirectorActionResponse(ApiModel):
    """Ответ на действие: новая версия и перечень последствий."""

    version: ArrangementVersionOut
    result: DirectorActionResultOut
    applied_action_ids: list[DirectorActionId]


class ChatMessageOut(ApiModel):
    id: str
    author: ChatAuthor
    text: str
    created_at: datetime


class DirectorChatRequest(ApiModel):
    """Реплика человека директору."""

    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Пустая реплика.")
        return stripped


class DirectorChatResponse(ApiModel):
    """Ответ директора.

    `suggested_action_id` пустой — нормальный исход: команду не поняли. Честный
    ответ «не понял» лучше, чем выполнение похожего действия.
    """

    message: ChatMessageOut
    reply: ChatMessageOut
    suggested_action_id: DirectorActionId | None = None
