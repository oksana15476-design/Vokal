"""Модели данных Vokal Director.

Схема повторяет `src/domain/types.ts`. Разбиение на таблицы и JSONB выбрано по
одному признаку: **по чему мы ищем и сортируем — колонка, что читается целиком
и меняется целиком — JSONB**. Разбирать `SongAnalysis` на таблицы секций и
аккордов сейчас рано: настоящая музыкальная модель (`SongGraph`) — отдельный
эпик, и таблицы под нее придется переделывать. Класть в JSONB то, по чему
строится список песен, наоборот, нельзя: индекс по такому полю живет плохо.

`StagePack` отдельной таблицей не заведен намеренно: в `types.ts` это
`{ id, versionId, artifacts }`, то есть срез артефактов по версии.
Отдельная таблица завела бы вторую точку правды о том, какие материалы
относятся к версии.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import enums
from app.db.base import Base, SoftDeleteMixin, TimestampMixin, domain_enum, utcnow, uuid_pk


class User(Base, TimestampMixin, SoftDeleteMixin):
    """Пользователь заведен по минимуму: авторизация — задача другого батча.

    Здесь только то, без чего не существует владения проектом: идентификатор,
    контакт для входа и дата. Пароли, сессии, роли появятся вместе с
    авторизацией, а не заранее пустыми колонками.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    contact: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)


class Project(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    scenario: Mapped[enums.Scenario] = mapped_column(
        domain_enum(enums.Scenario, "scenario"), nullable=False
    )
    processing_goal_id: Mapped[enums.ProcessingGoalId] = mapped_column(
        domain_enum(enums.ProcessingGoalId, "processing_goal_id"), nullable=False
    )

    # Текущая версия аранжировки. Ссылка на versions создается отдельно
    # (use_alter): таблицы ссылаются друг на друга, и без этого порядок
    # создания в миграции неразрешим.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_projects_current_version_versions",
        ),
        nullable=True,
    )

    # Время последнего открытия. NOT NULL с умолчанием: проект, который только
    # что создали, пользователь и открыл. NULL заставил бы каждый запрос списка
    # разбираться, куда девать пустые значения, и портил бы индекс.
    last_opened_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )

    # Настройка, введенная пользователем, и снимок для показа. Разделены так же,
    # как в `types.ts`: из `setup` считается аранжировка, `setup_snapshot` живет
    # только на экране сводки.
    setup: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    setup_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    band_lineup: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    student_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    teacher_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    class_group: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    lesson: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    assignments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_estimate: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Согласие хранится вместе с текстом, а не только с версией: запись должна
    # читаться, даже если модуль версий когда-нибудь потеряют (`types.ts`).
    consent_accepted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    consent_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_accepted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )

    # Две операции удаления из DELETION_AND_RETENTION_DESIGN.md. Состояние, а не
    # флаг: «удаление выполняется» показывается до подтверждения хранилища.
    source_deletion_state: Mapped[enums.DeletionState] = mapped_column(
        domain_enum(enums.DeletionState, "deletion_state"),
        nullable=False,
        default=enums.DeletionState.PRESENT,
        server_default=text("'present'"),
    )
    source_deletion_requested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    source_purged_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    source_purge_receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_purge_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    results_deletion_state: Mapped[enums.DeletionState] = mapped_column(
        domain_enum(enums.DeletionState, "deletion_state"),
        nullable=False,
        default=enums.DeletionState.PRESENT,
        server_default=text("'present'"),
    )
    results_deletion_requested_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    results_purged_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    results_purge_receipt: Mapped[str | None] = mapped_column(Text, nullable=True)
    results_purge_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    retention_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Список песен пользователя по времени последнего открытия. Частичный:
        # удаленные проекты в списке не показываются никогда, и держать их в
        # индексе — платить за строки, которые не читаются.
        Index(
            "ix_projects_user_last_opened",
            "user_id",
            text("last_opened_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Выборка того, что пора снести физически по истечении срока хранения.
        Index(
            "ix_projects_retention_sweep",
            "retention_until",
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
    )


class Upload(Base, TimestampMixin, SoftDeleteMixin):
    """Загруженный файл.

    `storage_key` — ключ объекта в хранилище. В логи он не попадает никогда
    (политика логирования в DELETION_AND_RETENTION_DESIGN.md): по ключу вместе
    с подписанной ссылкой восстанавливается доступ к чужой фонограмме.
    Логируется идентификатор загрузки, не путь.
    """

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(400), nullable=False)
    file_format: Mapped[enums.UploadFormat] = mapped_column(
        domain_enum(enums.UploadFormat, "upload_format"), nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    quality: Mapped[enums.UploadQuality] = mapped_column(
        domain_enum(enums.UploadQuality, "upload_quality"), nullable=False
    )
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channels: Mapped[int | None] = mapped_column(Integer, nullable=True)

    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_uploads_project", "project_id", postgresql_where=text("deleted_at IS NULL")),
    )


class Job(Base, TimestampMixin, SoftDeleteMixin):
    """Тяжелая операция обработки.

    Поля идемпотентности, версии модели и стоимости заведены сразу: в
    `architecture.md` записано, что перезаписывать файлы нельзя и нужно знать,
    какой запуск какой модели создал какой артефакт.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[enums.JobStatus] = mapped_column(
        domain_enum(enums.JobStatus, "job_status"),
        nullable=False,
        default=enums.JobStatus.QUEUED,
        server_default=text("'queued'"),
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cost_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        CheckConstraint("progress_percent BETWEEN 0 AND 100", name="progress_percent_range"),
        Index("ix_jobs_project", "project_id", postgresql_where=text("deleted_at IS NULL")),
    )


class JobStep(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "job_steps"

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[enums.JobStepStatus] = mapped_column(
        domain_enum(enums.JobStepStatus, "job_step_status"),
        nullable=False,
        default=enums.JobStepStatus.QUEUED,
        server_default=text("'queued'"),
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        UniqueConstraint("job_id", "step_key", name="uq_job_steps_job_id_step_key"),
        Index("ix_job_steps_job_position", "job_id", "position"),
    )


class Version(Base, SoftDeleteMixin):
    """Версия аранжировки.

    `created_at` здесь без `TimestampMixin`: время создания версии задает
    доменный код (импорт истории, откат), а не база. Подменять его серверным
    `now()` — терять порядок версий при переносе данных.
    """

    __tablename__ = "versions"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("versions.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[enums.VersionKind] = mapped_column(
        domain_enum(enums.VersionKind, "version_kind"), nullable=False
    )
    status: Mapped[enums.VersionStatus] = mapped_column(
        domain_enum(enums.VersionStatus, "version_status"),
        nullable=False,
        default=enums.VersionStatus.DRAFT,
        server_default=text("'draft'"),
    )
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    changes: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Снимок материалов на момент выхода из версии — то, что позволяет
    # откатиться назад. При удалении результатов очищается: снимок материалов
    # это тоже материалы.
    artifacts_snapshot: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        # Выборка версий проекта: список истории и построение дерева откатов.
        Index(
            "ix_versions_project_created",
            "project_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class Artifact(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("versions.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    artifact_type: Mapped[enums.ArtifactType] = mapped_column(
        domain_enum(enums.ArtifactType, "artifact_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_format: Mapped[enums.ArtifactFormat] = mapped_column(
        domain_enum(enums.ArtifactFormat, "artifact_format"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[enums.ArtifactStatus] = mapped_column(
        domain_enum(enums.ArtifactStatus, "artifact_status"),
        nullable=False,
        default=enums.ArtifactStatus.PENDING,
        server_default=text("'pending'"),
    )
    # Numeric, а не float: уверенность показывается пользователю числом, и
    # 0.8200000000000001 в интерфейсе — брак.
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3, asdecimal=False), nullable=True)
    audience: Mapped[enums.ArtifactAudience] = mapped_column(
        domain_enum(enums.ArtifactAudience, "artifact_audience"),
        nullable=False,
        default=enums.ArtifactAudience.ALL,
        server_default=text("'all'"),
    )
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    preview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        Index(
            "ix_artifacts_project_version",
            "project_id",
            "version_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ReviewIssue(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "review_issues"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("versions.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bar: Mapped[int | None] = mapped_column(Integer, nullable=True)
    part: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[enums.ReviewStatus] = mapped_column(
        domain_enum(enums.ReviewStatus, "review_status"),
        nullable=False,
        default=enums.ReviewStatus.NEEDS_REVIEW,
        server_default=text("'needs_review'"),
    )
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3, asdecimal=False), nullable=True)

    __table_args__ = (
        Index(
            "ix_review_issues_project", "project_id", postgresql_where=text("deleted_at IS NULL")
        ),
    )


class ReviewComment(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "review_comments"

    id: Mapped[uuid.UUID] = uuid_pk()
    issue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("review_issues.id", ondelete="CASCADE"), nullable=False
    )
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    text_body: Mapped[str] = mapped_column("text", Text, nullable=False)

    __table_args__ = (
        Index("ix_review_comments_issue", "issue_id", postgresql_where=text("deleted_at IS NULL")),
    )


class Musician(Base, TimestampMixin, SoftDeleteMixin):
    """Человек в составе.

    Ограничение вынесено в колонку `constraint_note`, а не в свободный текст
    примечания: диапазон вокалиста и число струн басиста — это данные, по
    которым директор принимает решения. `constraint` зарезервировано в SQL,
    отсюда суффикс.
    """

    __tablename__ = "musicians"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[enums.MusicianRole] = mapped_column(
        domain_enum(enums.MusicianRole, "musician_role"), nullable=False
    )
    instrument_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraint_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[enums.MusicianLevel] = mapped_column(
        domain_enum(enums.MusicianLevel, "musician_level"), nullable=False
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (Index("ix_musicians_project_position", "project_id", "position"),)


class ShareRecipient(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "share_recipients"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[enums.ShareRecipientRole] = mapped_column(
        domain_enum(enums.ShareRecipientRole, "share_recipient_role"), nullable=False
    )
    material: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[enums.ShareRecipientStatus] = mapped_column(
        domain_enum(enums.ShareRecipientStatus, "share_recipient_status"),
        nullable=False,
        default=enums.ShareRecipientStatus.NOT_ISSUED,
        server_default=text("'not_issued'"),
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    __table_args__ = (
        Index(
            "ix_share_recipients_project",
            "project_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


#: Таблицы с мягким удалением. Список нужен миграции (триггер необратимости) и
#: каскаду в репозитории: забыть таблицу в одном из мест — значит получить
#: строку, которая переживет удаление проекта.
SOFT_DELETABLE_TABLES: tuple[str, ...] = (
    "users",
    "projects",
    "uploads",
    "jobs",
    "job_steps",
    "artifacts",
    "versions",
    "review_issues",
    "review_comments",
    "musicians",
    "share_recipients",
)
