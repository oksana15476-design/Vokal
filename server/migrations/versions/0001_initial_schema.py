"""Первая миграция: схема Vokal Director с нуля.

Поднимает пустую базу до рабочего состояния: перечисления домена, одиннадцать
таблиц, индексы под список песен и версии, триггер необратимости мягкого
удаления.

Списки таблиц и значений перечислений здесь **продублированы намеренно**, а не
взяты из `app.db.models`. Миграция описывает состояние базы на конкретный
момент. Если она читает текущие модели, то завтрашняя правка модели задним
числом меняет вчерашнюю миграцию, и накат на чистую базу перестает совпадать с
накатом на существующую.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Перечисления домена. Значения повторяют литеральные типы `src/domain/types.ts`.
ENUM_TYPES: dict[str, tuple[str, ...]] = {
    "scenario": ("band", "education"),
    "processing_goal_id": (
        "band-analysis",
        "band-rehearsal",
        "band-performance",
        "band-minus",
        "band-parts",
        "band-transpose",
        "band-adapt-lineup",
        "band-boost",
        "lesson-analysis",
        "lesson-easy",
        "lesson-original",
        "lesson-advanced",
        "lesson-concert",
        "lesson-ensemble",
        "lesson-homework",
        "lesson-practice-tracks",
    ),
    "upload_format": ("MP3", "WAV", "FLAC", "M4A", "DEMO"),
    "upload_quality": ("good", "medium", "low"),
    "job_status": ("queued", "running", "ready", "warning", "error"),
    "job_step_status": ("queued", "running", "done", "warning", "error", "skipped"),
    "version_kind": (
        "original",
        "band",
        "easy",
        "original-like",
        "advanced",
        "concert",
        "ensemble",
        "after-rehearsal",
        "after-lesson",
    ),
    "version_status": ("draft", "needs_review", "approved", "distributed"),
    "artifact_type": (
        "score",
        "part",
        "tab",
        "chords",
        "lyrics",
        "midi",
        "stem",
        "minus",
        "click",
        "practice",
        "teacher",
        "student",
        "zip",
    ),
    "artifact_format": ("PDF", "MIDI", "WAV", "ZIP", "MusicXML", "VIEW"),
    "artifact_status": ("ready", "draft", "needs_review", "rebuild_required", "pending"),
    "artifact_audience": ("all", "band", "teacher", "student", "instrument"),
    "review_status": ("needs_review", "checked", "fixed", "uncertain", "accepted_for_rehearsal"),
    "musician_role": ("vocal", "guitar", "bass", "keys", "drums", "backing_vocal"),
    "musician_level": ("beginner", "middle", "advanced"),
    "share_recipient_role": (
        "vocalist",
        "guitarist",
        "bassist",
        "keys",
        "drummer",
        "teacher",
        "student",
        "parent",
    ),
    "share_recipient_status": ("not_issued", "issued", "opened", "needs_fix"),
    "deletion_state": ("present", "purge_requested", "purged", "purge_failed"),
}

#: Таблицы с мягким удалением: на каждую вешается триггер необратимости.
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


def _enum(name: str) -> postgresql.ENUM:
    """Ссылка на уже созданный тип: создаем типы отдельно и один раз."""
    return postgresql.ENUM(*ENUM_TYPES[name], name=name, create_type=False)


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def _ts() -> sa.TIMESTAMP:
    return sa.TIMESTAMP(timezone=True)


def _soft_delete_columns() -> list[sa.Column]:
    return [
        sa.Column("deleted_at", _ts(), nullable=True),
        sa.Column("retention_until", _ts(), nullable=True),
    ]


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", _ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", _ts(), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUM_TYPES.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)

    op.create_table(
        "users",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("contact", sa.String(length=320), nullable=False),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("contact", name="uq_users_contact"),
    )

    op.create_table(
        "projects",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("scenario", _enum("scenario"), nullable=False),
        sa.Column("processing_goal_id", _enum("processing_goal_id"), nullable=False),
        # Ссылка на versions добавляется ниже: таблицы ссылаются друг на друга.
        sa.Column("current_version_id", _uuid(), nullable=True),
        sa.Column("last_opened_at", _ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("setup", postgresql.JSONB(), nullable=True),
        sa.Column("setup_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("band_lineup", postgresql.JSONB(), nullable=True),
        sa.Column("student_profile", postgresql.JSONB(), nullable=True),
        sa.Column("teacher_profile", postgresql.JSONB(), nullable=True),
        sa.Column("class_group", postgresql.JSONB(), nullable=True),
        sa.Column("lesson", postgresql.JSONB(), nullable=True),
        sa.Column("assignments", postgresql.JSONB(), nullable=True),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("cost_estimate", postgresql.JSONB(), nullable=True),
        sa.Column("consent_accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("consent_version_id", sa.String(length=64), nullable=True),
        sa.Column("consent_text", sa.Text(), nullable=True),
        sa.Column("consent_accepted_at", _ts(), nullable=True),
        sa.Column(
            "source_deletion_state",
            _enum("deletion_state"),
            nullable=False,
            server_default=sa.text("'present'"),
        ),
        sa.Column("source_deletion_requested_at", _ts(), nullable=True),
        sa.Column("source_purged_at", _ts(), nullable=True),
        sa.Column("source_purge_receipt", sa.Text(), nullable=True),
        sa.Column("source_purge_error", sa.Text(), nullable=True),
        sa.Column(
            "results_deletion_state",
            _enum("deletion_state"),
            nullable=False,
            server_default=sa.text("'present'"),
        ),
        sa.Column("results_deletion_requested_at", _ts(), nullable=True),
        sa.Column("results_purged_at", _ts(), nullable=True),
        sa.Column("results_purge_receipt", sa.Text(), nullable=True),
        sa.Column("results_purge_error", sa.Text(), nullable=True),
        sa.Column("retention_note", sa.Text(), nullable=True),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_projects_user_id_users", ondelete="CASCADE"
        ),
    )

    op.create_table(
        "versions",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("parent_version_id", _uuid(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("kind", _enum("version_kind"), nullable=False),
        sa.Column(
            "status", _enum("version_status"), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", _ts(), nullable=False, server_default=sa.func.now()),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("artifacts_snapshot", postgresql.JSONB(), nullable=True),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_versions"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_versions_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["versions.id"],
            name="fk_versions_parent_version_id_versions",
            ondelete="SET NULL",
        ),
    )

    op.create_foreign_key(
        "fk_projects_current_version_versions",
        "projects",
        "versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "uploads",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=400), nullable=False),
        sa.Column("file_format", _enum("upload_format"), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("quality", _enum("upload_quality"), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("normalized_storage_key", sa.Text(), nullable=True),
        sa.Column("preview_storage_key", sa.Text(), nullable=True),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_uploads"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_uploads_project_id_projects",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "jobs",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column(
            "status", _enum("job_status"), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("warnings", postgresql.JSONB(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("cost_credits", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_jobs_project_id_projects", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        sa.CheckConstraint(
            "progress_percent BETWEEN 0 AND 100", name="ck_jobs_progress_percent_range"
        ),
    )

    op.create_table(
        "job_steps",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("job_id", _uuid(), nullable=False),
        sa.Column("step_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "status", _enum("job_step_status"), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_job_steps"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_job_steps_job_id_jobs", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("job_id", "step_key", name="uq_job_steps_job_id_step_key"),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("version_id", _uuid(), nullable=True),
        sa.Column("job_id", _uuid(), nullable=True),
        sa.Column("artifact_type", _enum("artifact_type"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("artifact_format", _enum("artifact_format"), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status", _enum("artifact_status"), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "audience", _enum("artifact_audience"), nullable=False, server_default=sa.text("'all'")
        ),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("preview", postgresql.JSONB(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_artifacts"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_artifacts_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["versions.id"],
            name="fk_artifacts_version_id_versions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name="fk_artifacts_job_id_jobs", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_artifacts_confidence_range",
        ),
    )

    op.create_table(
        "review_issues",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("version_id", _uuid(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("section_id", sa.String(length=64), nullable=True),
        sa.Column("bar", sa.Integer(), nullable=True),
        sa.Column("part", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum("review_status"),
            nullable=False,
            server_default=sa.text("'needs_review'"),
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_review_issues"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_review_issues_project_id_projects",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["versions.id"],
            name="fk_review_issues_version_id_versions",
            ondelete="SET NULL",
        ),
    )

    op.create_table(
        "review_comments",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("issue_id", _uuid(), nullable=False),
        sa.Column("author", sa.String(length=200), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_review_comments"),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["review_issues.id"],
            name="fk_review_comments_issue_id_review_issues",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "musicians",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", _enum("musician_role"), nullable=False),
        sa.Column("instrument_note", sa.Text(), nullable=True),
        sa.Column("constraint_note", sa.Text(), nullable=True),
        sa.Column("level", _enum("musician_level"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_musicians"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_musicians_project_id_projects",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "share_recipients",
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", _enum("share_recipient_role"), nullable=False),
        sa.Column("material", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum("share_recipient_status"),
            nullable=False,
            server_default=sa.text("'not_issued'"),
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_timestamp_columns(),
        *_soft_delete_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_share_recipients"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_share_recipients_project_id_projects",
            ondelete="CASCADE",
        ),
    )

    # Индексы. Частичные по `deleted_at IS NULL`: удаленные строки не попадают
    # ни в один пользовательский список, и место в индексе им ни к чему.
    op.create_index(
        "ix_projects_user_last_opened",
        "projects",
        ["user_id", sa.text("last_opened_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_projects_retention_sweep",
        "projects",
        ["retention_until"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.create_index(
        "ix_versions_project_created",
        "versions",
        ["project_id", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_uploads_project",
        "uploads",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_jobs_project", "jobs", ["project_id"], postgresql_where=sa.text("deleted_at IS NULL")
    )
    op.create_index("ix_job_steps_job_position", "job_steps", ["job_id", "position"])
    op.create_index(
        "ix_artifacts_project_version",
        "artifacts",
        ["project_id", "version_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_review_issues_project",
        "review_issues",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_review_comments_issue",
        "review_comments",
        ["issue_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_musicians_project_position", "musicians", ["project_id", "position"])
    op.create_index(
        "ix_share_recipients_project",
        "share_recipients",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Необратимость удаления держит база, а не дисциплина вызывающего кода.
    # Пользователю показано «удалено безвозвратно»; если строку можно вернуть
    # одним UPDATE, обещание ложное. Репозиторий не дает метода восстановления,
    # но репозиторий — не единственный путь к базе.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION vokal_forbid_undelete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL THEN
                RAISE EXCEPTION
                    'Удаление необратимо: deleted_at нельзя обнулить (таблица %)',
                    TG_TABLE_NAME
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        """
    )
    for table in SOFT_DELETABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_forbid_undelete
            BEFORE UPDATE OF deleted_at ON {table}
            FOR EACH ROW EXECUTE FUNCTION vokal_forbid_undelete();
            """
        )


def downgrade() -> None:
    for table in reversed(SOFT_DELETABLE_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_undelete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS vokal_forbid_undelete()")

    op.drop_table("share_recipients")
    op.drop_table("musicians")
    op.drop_table("review_comments")
    op.drop_table("review_issues")
    op.drop_table("artifacts")
    op.drop_table("job_steps")
    op.drop_table("jobs")
    op.drop_table("uploads")
    op.drop_constraint("fk_projects_current_version_versions", "projects", type_="foreignkey")
    op.drop_table("versions")
    op.drop_table("projects")
    op.drop_table("users")

    bind = op.get_bind()
    for name in reversed(list(ENUM_TYPES)):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
