"""Репозитории слоя данных.

Правило слоя: **наружу уходят модели, а не словари**. Словарь не проверяется
типами, переживает переименование колонки и всплывает опечаткой ключа в другом
конце приложения. Внутрь тоже идут не словари, а объявленные наборы полей
(`*Create` и `*Patch`).

Разница между `Create` и `Patch` не косметическая:

- в `Create` значение `None` означает «не задано» — колонка получает свое
  умолчание. Отдельного способа записать NULL при создании не нужно: у всех
  необязательных колонок умолчание и есть NULL;
- в `Patch` значение `None` означает «записать NULL», а «не трогать» — это
  `UNSET`. Без такого разделения частичное обновление невозможно отличить от
  очистки поля, и правка названия молча стирала бы согласие.

Восстановления после удаления здесь нет ни в каком виде. Это не упущение:
`docs/DELETION_AND_RETENTION_DESIGN.md` требует необратимости, и метод
`restore()` сделал бы обещание в интерфейсе ложным.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import enums, models
from app.db.base import utcnow


class EntityNotFound(LookupError):
    """Записи нет или она уже удалена."""


class DeletionStateError(RuntimeError):
    """Переход состояния удаления недопустим.

    Например, попытка объявить исходник удаленным, когда удаления никто не
    запрашивал: тогда «удалено» было бы записано без основания.
    """


class _Unset:
    """Отсутствие значения в патче. Отличается от `None` («записать NULL»)."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - только для отладки
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


class DeletionScope(str, Enum):
    """Что именно удаляем: две операции из дизайн-дока."""

    SOURCE = "source"
    RESULTS = "results"


# --- наборы полей ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UserCreate:
    contact: str


@dataclass(frozen=True, slots=True)
class UserPatch:
    contact: str | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ProjectCreate:
    user_id: uuid.UUID
    name: str
    scenario: enums.Scenario
    processing_goal_id: enums.ProcessingGoalId
    last_opened_at: datetime | None = None
    setup: dict[str, Any] | None = None
    setup_snapshot: dict[str, Any] | None = None
    band_lineup: dict[str, Any] | None = None
    student_profile: dict[str, Any] | None = None
    teacher_profile: dict[str, Any] | None = None
    class_group: dict[str, Any] | None = None
    lesson: dict[str, Any] | None = None
    assignments: list[Any] | None = None
    analysis: dict[str, Any] | None = None
    cost_estimate: dict[str, Any] | None = None
    consent_accepted: bool | None = None
    consent_version_id: str | None = None
    consent_text: str | None = None
    consent_accepted_at: datetime | None = None
    retention_note: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectPatch:
    name: str | _Unset = UNSET
    scenario: enums.Scenario | _Unset = UNSET
    processing_goal_id: enums.ProcessingGoalId | _Unset = UNSET
    current_version_id: uuid.UUID | None | _Unset = UNSET
    last_opened_at: datetime | _Unset = UNSET
    setup: dict[str, Any] | None | _Unset = UNSET
    setup_snapshot: dict[str, Any] | None | _Unset = UNSET
    band_lineup: dict[str, Any] | None | _Unset = UNSET
    student_profile: dict[str, Any] | None | _Unset = UNSET
    teacher_profile: dict[str, Any] | None | _Unset = UNSET
    class_group: dict[str, Any] | None | _Unset = UNSET
    lesson: dict[str, Any] | None | _Unset = UNSET
    assignments: list[Any] | None | _Unset = UNSET
    analysis: dict[str, Any] | None | _Unset = UNSET
    cost_estimate: dict[str, Any] | None | _Unset = UNSET
    retention_note: str | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class UploadCreate:
    project_id: uuid.UUID
    file_name: str
    file_format: enums.UploadFormat
    duration_seconds: int
    quality: enums.UploadQuality
    source_note: str | None = None
    size_bytes: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    storage_key: str | None = None
    normalized_storage_key: str | None = None
    preview_storage_key: str | None = None


@dataclass(frozen=True, slots=True)
class UploadPatch:
    file_name: str | _Unset = UNSET
    quality: enums.UploadQuality | _Unset = UNSET
    source_note: str | None | _Unset = UNSET
    size_bytes: int | None | _Unset = UNSET
    sample_rate: int | None | _Unset = UNSET
    channels: int | None | _Unset = UNSET
    storage_key: str | None | _Unset = UNSET
    normalized_storage_key: str | None | _Unset = UNSET
    preview_storage_key: str | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class JobCreate:
    project_id: uuid.UUID
    idempotency_key: str
    status: enums.JobStatus | None = None
    progress_percent: int | None = None
    warnings: list[str] | None = None
    model_version: str | None = None
    cost_credits: int | None = None


@dataclass(frozen=True, slots=True)
class JobPatch:
    status: enums.JobStatus | _Unset = UNSET
    progress_percent: int | _Unset = UNSET
    warnings: list[str] | None | _Unset = UNSET
    model_version: str | None | _Unset = UNSET
    cost_credits: int | None | _Unset = UNSET
    retry_count: int | _Unset = UNSET
    error_code: str | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class JobStepCreate:
    job_id: uuid.UUID
    step_key: str
    label: str
    status: enums.JobStepStatus | None = None
    detail: str | None = None
    position: int | None = None


@dataclass(frozen=True, slots=True)
class JobStepPatch:
    label: str | _Unset = UNSET
    status: enums.JobStepStatus | _Unset = UNSET
    detail: str | None | _Unset = UNSET
    position: int | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class VersionCreate:
    project_id: uuid.UUID
    label: str
    kind: enums.VersionKind
    created_by: str
    parent_version_id: uuid.UUID | None = None
    status: enums.VersionStatus | None = None
    created_at: datetime | None = None
    changes: list[str] | None = None
    artifacts_snapshot: list[Any] | None = None


@dataclass(frozen=True, slots=True)
class VersionPatch:
    label: str | _Unset = UNSET
    kind: enums.VersionKind | _Unset = UNSET
    status: enums.VersionStatus | _Unset = UNSET
    parent_version_id: uuid.UUID | None | _Unset = UNSET
    changes: list[str] | None | _Unset = UNSET
    artifacts_snapshot: list[Any] | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ArtifactCreate:
    project_id: uuid.UUID
    artifact_type: enums.ArtifactType
    name: str
    artifact_format: enums.ArtifactFormat
    version_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    description: str | None = None
    status: enums.ArtifactStatus | None = None
    confidence: float | None = None
    audience: enums.ArtifactAudience | None = None
    is_stale: bool | None = None
    preview: dict[str, Any] | None = None
    storage_key: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactPatch:
    name: str | _Unset = UNSET
    description: str | None | _Unset = UNSET
    status: enums.ArtifactStatus | _Unset = UNSET
    confidence: float | None | _Unset = UNSET
    audience: enums.ArtifactAudience | _Unset = UNSET
    is_stale: bool | _Unset = UNSET
    preview: dict[str, Any] | None | _Unset = UNSET
    storage_key: str | None | _Unset = UNSET
    version_id: uuid.UUID | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ReviewIssueCreate:
    project_id: uuid.UUID
    title: str
    version_id: uuid.UUID | None = None
    section_id: str | None = None
    bar: int | None = None
    part: str | None = None
    reason: str | None = None
    status: enums.ReviewStatus | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ReviewIssuePatch:
    title: str | _Unset = UNSET
    section_id: str | None | _Unset = UNSET
    bar: int | None | _Unset = UNSET
    part: str | None | _Unset = UNSET
    reason: str | None | _Unset = UNSET
    status: enums.ReviewStatus | _Unset = UNSET
    confidence: float | None | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ReviewCommentCreate:
    issue_id: uuid.UUID
    author: str
    text: str


@dataclass(frozen=True, slots=True)
class ReviewCommentPatch:
    text: str | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class MusicianCreate:
    project_id: uuid.UUID
    name: str
    role: enums.MusicianRole
    level: enums.MusicianLevel
    instrument_note: str | None = None
    constraint_note: str | None = None
    position: int | None = None


@dataclass(frozen=True, slots=True)
class MusicianPatch:
    name: str | _Unset = UNSET
    role: enums.MusicianRole | _Unset = UNSET
    level: enums.MusicianLevel | _Unset = UNSET
    instrument_note: str | None | _Unset = UNSET
    constraint_note: str | None | _Unset = UNSET
    position: int | _Unset = UNSET


@dataclass(frozen=True, slots=True)
class ShareRecipientCreate:
    project_id: uuid.UUID
    name: str
    role: enums.ShareRecipientRole
    material: str | None = None
    status: enums.ShareRecipientStatus | None = None
    position: int | None = None


@dataclass(frozen=True, slots=True)
class ShareRecipientPatch:
    name: str | _Unset = UNSET
    role: enums.ShareRecipientRole | _Unset = UNSET
    material: str | None | _Unset = UNSET
    status: enums.ShareRecipientStatus | _Unset = UNSET
    position: int | _Unset = UNSET


# --- базовый репозиторий -----------------------------------------------------

ModelT = TypeVar("ModelT")
CreateT = TypeVar("CreateT")
PatchT = TypeVar("PatchT")


class BaseRepository(Generic[ModelT, CreateT, PatchT]):
    """Общее поведение: создать, прочитать, обновить, мягко удалить.

    Список у каждой сущности свой: «все проекты подряд» никому не нужно, нужен
    список конкретного пользователя или конкретного проекта.
    """

    model: ClassVar[Any]
    #: Поля набора, чьи имена отличаются от имен атрибутов модели.
    aliases: ClassVar[Mapping[str, str]] = {}

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def get(self, entity_id: uuid.UUID, *, include_deleted: bool = False) -> ModelT | None:
        statement = select(self.model).where(self.model.id == entity_id)
        statement = self._visible(statement, include_deleted=include_deleted)
        result = await self._fetch(statement)
        return result.scalar_one_or_none()

    async def create(self, data: CreateT, *, entity_id: uuid.UUID | None = None) -> ModelT:
        """Создает запись; `entity_id` задается только там, где он должен быть
        воспроизводимым, — демо-данные и перенос из внешнего источника. В обычной
        работе идентификатор выдает база."""
        values = self._creation_values(data)
        if entity_id is not None:
            values["id"] = entity_id
        entity = self.model(**values)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update(self, entity_id: uuid.UUID, patch: PatchT) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise EntityNotFound(f"{self.model.__name__} {entity_id} не найден или удален.")
        for field, value in self._patch_values(patch).items():
            setattr(entity, field, value)
        await self._session.flush()
        return entity

    async def soft_delete(
        self,
        entity_id: uuid.UUID,
        *,
        retention_until: datetime | None = None,
        at: datetime | None = None,
    ) -> ModelT:
        """Помечает запись удаленной. Повторный вызов не ошибка.

        Идемпотентность — требование дизайн-дока: повторный запуск удаления на
        уже удаленном объекте завершается успехом.
        """
        entity = await self.get(entity_id, include_deleted=True)
        if entity is None:
            raise EntityNotFound(f"{self.model.__name__} {entity_id} не найден.")
        if entity.deleted_at is not None:
            return entity
        moment = at or utcnow()
        entity.deleted_at = moment
        entity.retention_until = retention_until
        await self._session.flush()
        return entity

    # --- служебное -----------------------------------------------------------

    async def _fetch(self, statement: Select[Any]) -> Any:
        """Любое чтение перечитывает строку из базы (`populate_existing`).

        В асинхронной сессии просроченный атрибут дозагрузить нельзя: обращение
        к нему падает с MissingGreenlet. Значит, объект в памяти не должен
        отставать от базы вообще — иначе массовое обновление (каскад удаления)
        оставило бы в сессии запись, которая считает себя живой.
        """
        return await self._session.execute(statement.execution_options(populate_existing=True))

    def _visible(self, statement: Select[Any], *, include_deleted: bool) -> Select[Any]:
        if include_deleted:
            return statement
        return statement.where(self.model.deleted_at.is_(None))

    def _creation_values(self, data: CreateT) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in dataclasses.fields(data):  # type: ignore[arg-type]
            value = getattr(data, field.name)
            if value is None or isinstance(value, _Unset):
                continue
            values[self.aliases.get(field.name, field.name)] = value
        return values

    def _patch_values(self, patch: PatchT) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for field in dataclasses.fields(patch):  # type: ignore[arg-type]
            value = getattr(patch, field.name)
            if isinstance(value, _Unset):
                continue
            values[self.aliases.get(field.name, field.name)] = value
        return values

    async def _soft_delete_where(
        self,
        model: Any,
        condition: Any,
        *,
        moment: datetime,
        retention_until: datetime | None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Массовое мягкое удаление одной таблицы.

        Массовым запросом, а не перебором объектов: у проекта могут быть сотни
        артефактов, и удаление не должно зависеть от их количества.
        """
        values: dict[str, Any] = {"deleted_at": moment, "retention_until": retention_until}
        if extra:
            values.update(extra)
        await self._session.execute(
            update(model)
            .where(condition, model.deleted_at.is_(None))
            .values(**values)
            .execution_options(synchronize_session=False)
        )


class _ProjectScoped:
    """Список записей одного проекта."""

    model: ClassVar[Any]
    order_by: ClassVar[tuple[str, ...]] = ("created_at",)

    async def list_for_project(
        self, project_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Sequence[Any]:
        statement = select(self.model).where(self.model.project_id == project_id)
        if not include_deleted:
            statement = statement.where(self.model.deleted_at.is_(None))
        statement = statement.order_by(
            *[getattr(self.model, name) for name in self.order_by], self.model.id
        )
        result = await self._fetch(statement)  # type: ignore[attr-defined]
        return result.scalars().all()


# --- репозитории сущностей ---------------------------------------------------


class UserRepository(BaseRepository[models.User, UserCreate, UserPatch]):
    model = models.User

    async def get_by_contact(self, contact: str) -> models.User | None:
        statement = select(models.User).where(
            models.User.contact == contact, models.User.deleted_at.is_(None)
        )
        result = await self._fetch(statement)
        return result.scalar_one_or_none()

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> Sequence[models.User]:
        statement = (
            select(models.User)
            .where(models.User.deleted_at.is_(None))
            .order_by(models.User.created_at, models.User.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._fetch(statement)
        return result.scalars().all()


class UploadRepository(_ProjectScoped, BaseRepository[models.Upload, UploadCreate, UploadPatch]):
    model = models.Upload


class JobRepository(_ProjectScoped, BaseRepository[models.Job, JobCreate, JobPatch]):
    model = models.Job

    async def get_by_idempotency_key(self, key: str) -> models.Job | None:
        statement = select(models.Job).where(models.Job.idempotency_key == key)
        result = await self._fetch(statement)
        return result.scalar_one_or_none()


class JobStepRepository(BaseRepository[models.JobStep, JobStepCreate, JobStepPatch]):
    model = models.JobStep

    async def list_for_job(
        self, job_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Sequence[models.JobStep]:
        statement = select(models.JobStep).where(models.JobStep.job_id == job_id)
        if not include_deleted:
            statement = statement.where(models.JobStep.deleted_at.is_(None))
        statement = statement.order_by(models.JobStep.position, models.JobStep.id)
        result = await self._fetch(statement)
        return result.scalars().all()


class VersionRepository(_ProjectScoped, BaseRepository[models.Version, VersionCreate, VersionPatch]):
    model = models.Version
    order_by = ("created_at",)


class ArtifactRepository(
    _ProjectScoped, BaseRepository[models.Artifact, ArtifactCreate, ArtifactPatch]
):
    model = models.Artifact

    async def list_for_version(
        self, version_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Sequence[models.Artifact]:
        """Материалы одной версии — это и есть `StagePack` из `types.ts`."""
        statement = select(models.Artifact).where(models.Artifact.version_id == version_id)
        if not include_deleted:
            statement = statement.where(models.Artifact.deleted_at.is_(None))
        statement = statement.order_by(models.Artifact.created_at, models.Artifact.id)
        result = await self._fetch(statement)
        return result.scalars().all()


class ReviewIssueRepository(
    _ProjectScoped, BaseRepository[models.ReviewIssue, ReviewIssueCreate, ReviewIssuePatch]
):
    model = models.ReviewIssue

    async def soft_delete(
        self,
        entity_id: uuid.UUID,
        *,
        retention_until: datetime | None = None,
        at: datetime | None = None,
    ) -> models.ReviewIssue:
        """Удаление места для проверки уносит и комментарии к нему.

        Комментарий к исчезнувшему месту — висящая запись: показать ее не к
        чему, а удалить некому.
        """
        issue = await super().soft_delete(entity_id, retention_until=retention_until, at=at)
        await self._soft_delete_where(
            models.ReviewComment,
            models.ReviewComment.issue_id == entity_id,
            moment=issue.deleted_at or utcnow(),
            retention_until=retention_until,
        )
        await self._session.flush()
        return issue


class ReviewCommentRepository(
    BaseRepository[models.ReviewComment, ReviewCommentCreate, ReviewCommentPatch]
):
    model = models.ReviewComment
    aliases = {"text": "text_body"}

    async def list_for_issue(
        self, issue_id: uuid.UUID, *, include_deleted: bool = False
    ) -> Sequence[models.ReviewComment]:
        statement = select(models.ReviewComment).where(models.ReviewComment.issue_id == issue_id)
        if not include_deleted:
            statement = statement.where(models.ReviewComment.deleted_at.is_(None))
        statement = statement.order_by(models.ReviewComment.created_at, models.ReviewComment.id)
        result = await self._fetch(statement)
        return result.scalars().all()


class MusicianRepository(
    _ProjectScoped, BaseRepository[models.Musician, MusicianCreate, MusicianPatch]
):
    model = models.Musician
    order_by = ("position", "created_at")


class ShareRecipientRepository(
    _ProjectScoped,
    BaseRepository[models.ShareRecipient, ShareRecipientCreate, ShareRecipientPatch],
):
    model = models.ShareRecipient
    order_by = ("position", "created_at")


class ProjectRepository(BaseRepository[models.Project, ProjectCreate, ProjectPatch]):
    model = models.Project

    async def list_for_user(
        self, user_id: uuid.UUID, *, limit: int = 50, offset: int = 0
    ) -> Sequence[models.Project]:
        """Список песен пользователя: сверху то, что открывали последним.

        Ровно под этот запрос заведен `ix_projects_user_last_opened`.
        """
        statement = (
            select(models.Project)
            .where(models.Project.user_id == user_id, models.Project.deleted_at.is_(None))
            .order_by(models.Project.last_opened_at.desc(), models.Project.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._fetch(statement)
        return result.scalars().all()

    async def touch_opened(
        self, project_id: uuid.UUID, *, at: datetime | None = None
    ) -> models.Project:
        return await self.update(project_id, ProjectPatch(last_opened_at=at or utcnow()))

    async def soft_delete(
        self,
        project_id: uuid.UUID,
        *,
        retention_until: datetime | None = None,
        at: datetime | None = None,
    ) -> models.Project:
        """Удаление проекта доходит до всех производных.

        Пометить удаленным только проект — значит оставить в базе его загрузки,
        материалы, комментарии и получателей. Любой запрос, который ходит не
        через проект (выдача по ссылке, разбор джобы, отчет), продолжит их
        видеть, и «удалено» окажется неправдой.
        """
        project = await self.get(project_id, include_deleted=True)
        if project is None:
            raise EntityNotFound(f"Проект {project_id} не найден.")
        if project.deleted_at is not None:
            return project

        moment = at or utcnow()
        project.deleted_at = moment
        project.retention_until = retention_until
        await self._session.flush()

        for model in (
            models.Upload,
            models.Version,
            models.Job,
            models.Artifact,
            models.ReviewIssue,
            models.Musician,
            models.ShareRecipient,
        ):
            await self._soft_delete_where(
                model,
                model.project_id == project_id,
                moment=moment,
                retention_until=retention_until,
            )

        # Шаги джоб и комментарии висят не на проекте, а на своих родителях.
        await self._soft_delete_where(
            models.JobStep,
            models.JobStep.job_id.in_(
                select(models.Job.id).where(models.Job.project_id == project_id)
            ),
            moment=moment,
            retention_until=retention_until,
        )
        await self._soft_delete_where(
            models.ReviewComment,
            models.ReviewComment.issue_id.in_(
                select(models.ReviewIssue.id).where(models.ReviewIssue.project_id == project_id)
            ),
            moment=moment,
            retention_until=retention_until,
        )

        await self._session.flush()
        return project

    # --- две операции удаления из дизайн-дока --------------------------------

    async def request_source_deletion(self, project_id: uuid.UUID) -> models.Project:
        """`delete-source`: убрать исходную запись, оставить разбор и материалы.

        Ключи объектов обнуляются сразу: пока ключ лежит в базе, его можно
        подписать и выдать. Само тело файла удаляет фоновая задача, которой
        еще нет, поэтому состояние — «удаление запрошено», а не «удалено».
        """
        project = await self._require(project_id)
        if project.source_deletion_state in (
            enums.DeletionState.PURGE_REQUESTED,
            enums.DeletionState.PURGED,
        ):
            return project

        moment = utcnow()
        await self._soft_delete_where(
            models.Upload,
            models.Upload.project_id == project_id,
            moment=moment,
            retention_until=None,
            extra={
                "storage_key": None,
                "normalized_storage_key": None,
                "preview_storage_key": None,
            },
        )
        project.source_deletion_state = enums.DeletionState.PURGE_REQUESTED
        project.source_deletion_requested_at = moment
        project.source_purge_error = None
        await self._session.flush()
        return project

    async def request_results_deletion(self, project_id: uuid.UUID) -> models.Project:
        """`delete-results`: убрать материалы, оставить историю версий.

        Снимок материалов внутри версии очищается тоже. Дизайн-док разрешает
        сохранить «историю версий как перечень изменений без самих файлов» —
        снимок это файлы и есть.
        """
        project = await self._require(project_id)
        if project.results_deletion_state in (
            enums.DeletionState.PURGE_REQUESTED,
            enums.DeletionState.PURGED,
        ):
            return project

        moment = utcnow()
        await self._soft_delete_where(
            models.Artifact,
            models.Artifact.project_id == project_id,
            moment=moment,
            retention_until=None,
            extra={"storage_key": None},
        )
        await self._session.execute(
            update(models.Version)
            .where(models.Version.project_id == project_id)
            .values(artifacts_snapshot=None)
            .execution_options(synchronize_session=False)
        )
        project.results_deletion_state = enums.DeletionState.PURGE_REQUESTED
        project.results_deletion_requested_at = moment
        project.results_purge_error = None
        await self._session.flush()
        return project

    async def confirm_purged(
        self, project_id: uuid.UUID, *, scope: DeletionScope, receipt: str
    ) -> models.Project:
        """Отметить, что хранилище подтвердило удаление.

        `receipt` обязателен и не может быть пустым: «удалено» без следа
        подтверждения — это утверждение, которое некому проверить.
        """
        if not receipt.strip():
            raise ValueError("Подтверждение удаления без следа не принимается.")
        project = await self._require(project_id)
        state_field = f"{scope.value}_deletion_state"
        current: enums.DeletionState = getattr(project, state_field)
        if current is enums.DeletionState.PURGED:
            return project
        if current not in (enums.DeletionState.PURGE_REQUESTED, enums.DeletionState.PURGE_FAILED):
            raise DeletionStateError(
                f"Удаление ({scope.value}) не запрашивалось, текущее состояние: {current.value}."
            )
        setattr(project, state_field, enums.DeletionState.PURGED)
        setattr(project, f"{scope.value}_purged_at", utcnow())
        setattr(project, f"{scope.value}_purge_receipt", receipt)
        setattr(project, f"{scope.value}_purge_error", None)
        await self._session.flush()
        return project

    async def mark_purge_failed(
        self, project_id: uuid.UUID, *, scope: DeletionScope, reason: str
    ) -> models.Project:
        """Зафиксировать неисполненное удаление.

        Дизайн-док называет исчерпание попыток инцидентом. Инцидент должен
        быть виден в данных, а не только в логе, иначе алерт не на чем строить.
        """
        project = await self._require(project_id)
        state_field = f"{scope.value}_deletion_state"
        current: enums.DeletionState = getattr(project, state_field)
        if current is not enums.DeletionState.PURGE_REQUESTED:
            raise DeletionStateError(
                f"Нельзя пометить неудачей то, что не выполнялось: {current.value}."
            )
        setattr(project, state_field, enums.DeletionState.PURGE_FAILED)
        setattr(project, f"{scope.value}_purge_error", reason)
        await self._session.flush()
        return project

    async def _require(self, project_id: uuid.UUID) -> models.Project:
        project = await self.get(project_id)
        if project is None:
            raise EntityNotFound(f"Проект {project_id} не найден или удален.")
        return project


class Repositories:
    """Все репозитории одной сессии.

    Собраны вместе, чтобы вызывающий код не создавал их по одному и не завел
    случайно репозиторий на другой сессии — тогда часть записи ушла бы в чужую
    транзакцию.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.projects = ProjectRepository(session)
        self.uploads = UploadRepository(session)
        self.jobs = JobRepository(session)
        self.job_steps = JobStepRepository(session)
        self.artifacts = ArtifactRepository(session)
        self.versions = VersionRepository(session)
        self.review_issues = ReviewIssueRepository(session)
        self.review_comments = ReviewCommentRepository(session)
        self.musicians = MusicianRepository(session)
        self.share_recipients = ShareRecipientRepository(session)
