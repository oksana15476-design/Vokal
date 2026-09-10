"""Общее основание всех схем API.

Две вещи задаются здесь и больше нигде, потому что разнобой в них дороже
любой отдельной схемы:

1. **Имена полей.** Наружу уходит camelCase — так устроен домен фронтенда
   (`src/domain/types.ts`), и клиент генерируется из этой схемы. Внутри
   Python остается snake_case. Перевод делает генератор псевдонимов, а не
   человек в каждой модели.
2. **Незнакомое поле — ошибка.** `extra="forbid"` выбран не из строгости:
   продукт уже обжигался на тихой подмене настроек пользователя умолчанием
   (комментарий к `BandSetup` в `types.ts`). Опечатка в имени поля обязана
   отвечать `422`, а не молча терять то, что человек ввел.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """База для всех схем контракта."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class ValidationFieldError(ApiModel):
    """Одно поле, не прошедшее проверку."""

    field: str = Field(description="Путь до поля, например body.consent.versionId")
    reason: str = Field(description="Причина отказа")


class ErrorBody(ApiModel):
    """Тело ошибки. Форма задана `app/core/errors.py` и одинакова для всего API."""

    code: str = Field(description="Машинный код для ветвления на клиенте")
    message: str = Field(description="Текст для показа пользователю")
    request_id: str | None = Field(
        default=None, description="Идентификатор запроса: по нему поддержка ищет след в логах"
    )
    details: Any = Field(
        default=None,
        description=(
            "Подробности, зависят от кода. Для validation_error — {fields: [{field, reason}]}, "
            "для not_implemented — {endpoint, missing, docs}."
        ),
    )


class ErrorEnvelope(ApiModel):
    """Конверт ошибки: любой ответ с кодом 4xx/5xx выглядит так."""

    error: ErrorBody


class PageMeta(ApiModel):
    """Постраничность списков."""

    total: int = Field(ge=0, description="Сколько всего записей подходит под запрос")
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
