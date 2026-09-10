"""Схемы проверки: сомнительные места и комментарии к ним.

Пять статусов вместо флага «проверено» — не избыточность. Разница между
«исправлено» и «принято для репетиции» продуктовая: во втором случае место
осталось спорным, но группа договорилась играть так. Свести их в булево
значение — потерять договоренность.

**Уверенность всегда идет с числом в процентах.** Это правило бренда, а не
украшение (`README.md`, `docs/design/HANDOFF.md`): цвет — не единственный
сигнал. Процент считает сервер и отдает готовым — `confidencePercent` объявлен
вычисляемым полем, поэтому разойтись с самой уверенностью он не может в
принципе.

**Уверенность, которой нет, не заменяется нулем.** Ноль на экране читается не
как «не считали», а как «уверены, что все плохо» — это разные утверждения, и
пользователь принимает по ним разные решения. Поэтому число пустое, а рядом
стоит `confidenceNote` с причиной. Схема требует их парности: без числа обязана
быть причина, с числом причины быть не должно.
"""

from __future__ import annotations

import math
from datetime import datetime

from pydantic import Field, computed_field, field_validator, model_validator

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
    confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Уверенность: 0..1. Пусто — рассчитать ее нечем, причина в confidenceNote.",
    )
    confidence_note: str | None = Field(
        default=None,
        description="Почему уверенности нет. Заполнено ровно тогда, когда пусто число.",
    )
    comments: list[ReviewCommentOut] = Field(default_factory=list)

    @computed_field(  # type: ignore[prop-decorator]
        alias="confidencePercent",
        description="Уверенность в процентах: то же число, что и рядом с полосой на экране",
        return_type=int | None,
    )
    @property
    def confidence_percent(self) -> int | None:
        """Процент рядом с уверенностью.

        Округление половин вверх, как `Math.round` на экране: 0.825 — это 83%.
        Встроенный `round` округляет половину к четному и дал бы 82 — расхождение
        сервера и экрана на один процент пользователь увидит первым.
        """
        if self.confidence is None:
            return None
        return math.floor(self.confidence * 100 + 0.5)

    @model_validator(mode="after")
    def _confidence_is_either_counted_or_explained(self) -> ReviewIssueOut:
        if self.confidence is None and not self.confidence_note:
            raise ValueError("Уверенности нет — обязана быть причина в confidenceNote.")
        if self.confidence is not None and self.confidence_note:
            raise ValueError("Уверенность посчитана — объяснять ее отсутствие нечем.")
        return self


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
            "Подпись автора. Пусто — подставляется владелец запроса; чужое имя подставить нельзя."
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
