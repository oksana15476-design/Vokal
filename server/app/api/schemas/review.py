"""Схемы проверки: сомнительные места и комментарии к ним.

Пять статусов вместо флага «проверено» — не избыточность. Разница между
«исправлено» и «принято для репетиции» продуктовая: во втором случае место
осталось спорным, но группа договорилась играть так. Свести их в булево
значение — потерять договоренность.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import ReviewStatus


class ReviewCommentOut(ApiModel):
    """Комментарий человека к месту проверки."""

    id: str
    issue_id: str
    author: str
    text: str
    created_at: datetime


class ReviewIssueOut(ApiModel):
    """Место, которое стоит проверить руками."""

    id: str
    title: str
    section_id: str
    bar: int = Field(ge=1)
    part: str
    reason: str = Field(description="Почему место попало в проверку")
    status: ReviewStatus
    confidence: float = Field(ge=0, le=1)
    comments: list[ReviewCommentOut] = Field(default_factory=list)


class ReviewIssueListResponse(ApiModel):
    items: list[ReviewIssueOut]
    total: int = Field(ge=0)


class ReviewIssueStatusUpdate(ApiModel):
    """Смена статуса места проверки."""

    status: ReviewStatus
    comment: str | None = Field(
        default=None,
        max_length=2000,
        description="Необязательное пояснение: сохраняется как комментарий к месту",
    )


class ReviewCommentCreate(ApiModel):
    """Свой комментарий к месту проверки."""

    text: str = Field(min_length=1, max_length=2000)
    author: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Подпись автора. Пусто — подставляется владелец запроса; "
            "чужое имя подставить нельзя."
        ),
    )

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # Пробелы — не комментарий. Пустая запись в истории проверки хуже, чем
        # ее отсутствие: место выглядит разобранным, а разбора нет.
        stripped = value.strip()
        if not stripped:
            raise ValueError("Комментарий не может быть пустым.")
        return stripped
