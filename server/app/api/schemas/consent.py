"""Схемы согласия.

Версия согласия обязана дойти до сервера. Без нее запись «согласие получено»
остается без предмета: текст на экране меняется, а по чему читать старое
согласие — неизвестно. Восстановить это задним числом нельзя, поэтому версия
здесь обязательное поле, а неизвестная версия — отказ, а не предупреждение.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator, model_validator

from app.api.consent_versions import consent_text_by_id
from app.api.schemas.common import ApiModel


class ConsentVersionOut(ApiModel):
    """Версия формулировки согласия."""

    id: str = Field(description="Идентификатор версии, например consent-2026-09-10")
    effective_from: str = Field(description="Дата, с которой формулировка действует")
    text: str = Field(description="Точный текст, который видит пользователь")
    fingerprint: int = Field(
        description="Контрольная сумма текста: защищает от правки без смены версии"
    )


class ConsentVersionListResponse(ApiModel):
    """Все версии, от старых к новым. По ним читаются старые записи."""

    items: list[ConsentVersionOut]
    current_id: str


class ConsentAcceptance(ApiModel):
    """Согласие, полученное на экране. Приходит вместе с созданием проекта."""

    accepted: bool = Field(description="Отметка пользователя. Значение false — отказ создать проект")
    version_id: str = Field(
        min_length=1,
        max_length=64,
        description="Версия формулировки, которую человек принял",
    )

    @field_validator("version_id")
    @classmethod
    def _known_version(cls, value: str) -> str:
        if consent_text_by_id(value) is None:
            raise ValueError(
                "Неизвестная версия согласия. Запросите действующую версию "
                "у GET /api/consent/current и покажите ее пользователю."
            )
        return value

    @model_validator(mode="after")
    def _must_be_accepted(self) -> ConsentAcceptance:
        if not self.accepted:
            raise ValueError("Без согласия проект не создается.")
        return self


class LegalConsentOut(ApiModel):
    """Согласие, записанное в проекте.

    Текст хранится рядом с версией намеренно: запись должна читаться, даже если
    реестр версий когда-нибудь потеряют.
    """

    accepted: bool
    version_id: str
    text: str
    accepted_at: datetime | None = None
