"""Схемы выдачи материалов.

Два требования из `docs/DELETION_AND_RETENTION_DESIGN.md` заданы прямо в схеме,
потому что нарушить их дешевле всего именно здесь:

1. **Ссылка ведет на наш адрес**, а не в хранилище. Подписанную ссылку на
   объект невозможно отозвать, и «удалить результаты» перестало бы работать
   для всех, кому ссылку уже отправили.
2. **Ссылку можно отозвать** — отсюда `revoked_at` и статус `revoked`.

Разным ролям выдается разное. У преподавателя может быть версия с заметками,
у ученика — только его партия и домашнее задание. Поэтому в ссылке есть выбор
материалов, а не «весь пакет всем».
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import (
    ExportBundleStatus,
    ShareLinkStatus,
    ShareRecipientRole,
    ShareRecipientStatus,
)


class ShareRecipientOut(ApiModel):
    """Получатель материалов."""

    id: str
    name: str
    role: ShareRecipientRole
    material: str = Field(description="Что именно ему выдается, словами для экрана")
    status: ShareRecipientStatus


class ShareRecipientListResponse(ApiModel):
    items: list[ShareRecipientOut]
    total: int = Field(ge=0)


class ShareRecipientCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    role: ShareRecipientRole
    material: str | None = Field(default=None, max_length=500)


class ShareRecipientUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: ShareRecipientRole | None = None
    material: str | None = Field(default=None, max_length=500)


class ShareLinkOut(ApiModel):
    """Выданная ссылка."""

    id: str
    recipient_id: str
    label: str
    url: str = Field(
        description=(
            "Адрес нашего сервиса с отзываемым токеном. Прямая подписанная ссылка "
            "на объект хранилища сюда не попадает никогда: ее нельзя отозвать."
        )
    )
    status: ShareLinkStatus
    artifact_ids: list[str] = Field(description="Какие материалы открывает ссылка")
    created_at: datetime
    expires_at: datetime | None = Field(
        default=None, description="Когда ссылка перестанет работать сама"
    )
    revoked_at: datetime | None = Field(
        default=None, description="Когда ссылку отозвали. Заполняется и при удалении результатов."
    )
    opened_at: datetime | None = None


class ShareLinkListResponse(ApiModel):
    items: list[ShareLinkOut]
    total: int = Field(ge=0)


class ShareLinkCreate(ApiModel):
    """Выдача ссылки получателю."""

    recipient_id: str = Field(description="Кому выдаем. Ссылка без адресата не выдается.")
    artifact_ids: list[str] = Field(
        default_factory=list,
        description="Какие материалы открыть. Пусто — материалы по роли получателя.",
    )
    expires_in_hours: int | None = Field(
        default=None,
        ge=1,
        le=24 * 90,
        description="Срок жизни ссылки. Пусто — срок по умолчанию сервиса.",
    )
    label: str | None = Field(default=None, max_length=200)


class ExportBundleOut(ApiModel):
    """Собранный архив материалов."""

    id: str
    label: str
    files_count: int = Field(ge=0)
    status: ExportBundleStatus
    version_id: str
    created_at: datetime
    is_stale: bool = Field(description="Архив собран из материалов, которые уже устарели")


class ExportBundleListResponse(ApiModel):
    items: list[ExportBundleOut]
    total: int = Field(ge=0)


class ExportBundleCreate(ApiModel):
    """Пересборка архива."""

    audience: ShareRecipientRole | None = Field(
        default=None, description="Собрать для конкретной роли. Пусто — общий пакет."
    )
    artifact_ids: list[str] = Field(default_factory=list)
    label: str | None = Field(default=None, max_length=200)
