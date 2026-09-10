"""Схемы материалов и Stage Pack.

Два поля материала существуют ради честности и не должны исчезать при первом
упрощении:

- `confidence` — насколько модель уверена в этом материале. В интерфейсе
  подписывается процентом, потому что цвет не единственный сигнал;
- `is_stale` — материал устарел после правки аранжировки. Без этого признака
  музыкант унесет на репетицию ноты, не соответствующие текущей версии.

Скачивание идет через собственный адрес с проверкой прав, а не подписанной
ссылкой на хранилище напрямую: подписанную ссылку невозможно отозвать, и без
этого «удалить результаты» не исполняется для уже выданных ссылок
(`docs/DELETION_AND_RETENTION_DESIGN.md`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import (
    ArtifactAudience,
    ArtifactFormat,
    ArtifactPreviewKind,
    ArtifactStatus,
    ArtifactType,
)
from app.api.schemas.review import ReviewIssueOut
from app.api.schemas.song import SongAnalysisOut


class ArtifactPreviewOut(ApiModel):
    """Предпросмотр без скачивания файла."""

    kind: ArtifactPreviewKind
    title: str
    lines: list[str]


class ArtifactOut(ApiModel):
    """Материал Stage Pack."""

    id: str
    type: ArtifactType
    name: str
    format: ArtifactFormat
    description: str
    status: ArtifactStatus
    confidence: float = Field(ge=0, le=1, description="Уверенность: 0..1, показывается процентом")
    audience: ArtifactAudience
    is_stale: bool = Field(description="Материал не соответствует текущей версии аранжировки")
    preview: ArtifactPreviewOut | None = None
    updated_at: datetime | None = None


class StagePackOut(ApiModel):
    """Пакет материалов текущей версии."""

    id: str
    version_id: str
    artifacts: list[ArtifactOut]


class StagePackResponse(ApiModel):
    """Ответ экрана Stage Pack: материалы, разбор и места для проверки разом.

    Одним ответом, а не тремя запросами, потому что показывать материалы без
    разбора и без мест для проверки нельзя: пользователь примет черновик за
    проверенный результат.
    """

    stage_pack: StagePackOut
    analysis: SongAnalysisOut
    review_issues: list[ReviewIssueOut]
    warnings: list[str] = Field(
        default_factory=list, description="Предупреждения обработки, показываются над материалами"
    )


class ArtifactListResponse(ApiModel):
    items: list[ArtifactOut]
    total: int = Field(ge=0)


class ArtifactDownloadOut(ApiModel):
    """Ссылка на скачивание одного материала.

    Живет минуты, а не дни, и ведет на наш адрес с проверкой прав.
    """

    artifact_id: str
    url: str
    expires_at: datetime
    file_name: str
    size_bytes: int | None = None
