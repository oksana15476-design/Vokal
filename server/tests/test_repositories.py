"""Тесты слоя данных: репозитории, мягкое удаление, каскад, индексы, миграция.

Тесты написаны до реализации. Каждый пункт задачи батча закрыт проверкой,
которая может упасть: схема (миграция поднимает то же, что объявляют модели),
репозитории (создать/прочитать/список/обновить/удалить), единица работы
(откат при ошибке), индексы, мягкое удаление с каскадом и необратимостью,
демо-данные.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import enums, models
from app.db.base import Base
from app.db.repositories import (
    ArtifactCreate,
    DeletionScope,
    DeletionStateError,
    EntityNotFound,
    JobCreate,
    JobStepCreate,
    MusicianCreate,
    ProjectCreate,
    ProjectPatch,
    Repositories,
    ReviewCommentCreate,
    ReviewIssueCreate,
    ShareRecipientCreate,
    UploadCreate,
    UserCreate,
    VersionCreate,
)
from app.db.retention import purge_objects, resolve_retention_until
from app.db.seed import DEMO_PROJECT_KEYS, seed_demo_projects
from app.db.session import session_scope
from app.storage.retention import retention_until

pytestmark = pytest.mark.asyncio


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def _make_user(repos: Repositories, contact: str = "band@example.test") -> models.User:
    return await repos.users.create(UserCreate(contact=contact))


async def _make_project(
    repos: Repositories,
    user: models.User,
    *,
    name: str = "Late Train Home",
    last_opened_at: datetime | None = None,
) -> models.Project:
    return await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name=name,
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
            last_opened_at=last_opened_at,
        )
    )


# --- Задача 1 и 3: схема и миграция ------------------------------------------


async def test_migration_creates_every_table_declared_by_models(engine: AsyncEngine) -> None:
    """Миграция поднимает схему с нуля и покрывает все модели.

    Расхождение между `Base.metadata` и тем, что реально накатилось, — самая
    дорогая ошибка этого слоя: она вскрывается на деплое, а не в тестах.
    """
    async with engine.connect() as connection:
        tables = await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names())

    declared = set(Base.metadata.tables)
    assert declared, "Модели не объявили ни одной таблицы."
    assert declared <= set(tables), f"Миграция не создала: {sorted(declared - set(tables))}"


async def test_schema_covers_domain_entities(engine: AsyncEngine) -> None:
    """Все сущности из ТЗ батча существуют в базе под ожидаемыми именами."""
    async with engine.connect() as connection:
        tables = set(await connection.run_sync(lambda sync: sa.inspect(sync).get_table_names()))

    expected = {
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
    }
    assert expected <= tables, f"Не хватает таблиц: {sorted(expected - tables)}"


# --- Задача 4: репозитории ---------------------------------------------------


async def test_create_and_get_project(session: AsyncSession) -> None:
    repos = Repositories(session)
    user = await _make_user(repos)
    created = await _make_project(repos, user)
    await session.flush()

    found = await repos.projects.get(created.id)

    assert found is not None
    assert isinstance(found, models.Project)
    assert found.name == "Late Train Home"
    assert found.scenario is enums.Scenario.BAND
    assert found.user_id == user.id


async def test_get_returns_none_for_unknown_id(session: AsyncSession) -> None:
    repos = Repositories(session)
    assert await repos.projects.get(uuid.uuid4()) is None


async def test_update_changes_only_named_fields(session: AsyncSession) -> None:
    repos = Repositories(session)
    user = await _make_user(repos)
    project = await _make_project(repos, user)
    await session.flush()

    updated = await repos.projects.update(project.id, ProjectPatch(name="Новое название"))

    assert updated.name == "Новое название"
    assert updated.scenario is enums.Scenario.BAND
    assert updated.processing_goal_id is enums.ProcessingGoalId.BAND_REHEARSAL


async def test_update_unknown_id_raises(session: AsyncSession) -> None:
    repos = Repositories(session)
    with pytest.raises(EntityNotFound):
        await repos.projects.update(uuid.uuid4(), ProjectPatch(name="нет такого"))


async def test_repositories_return_models_not_dicts(session: AsyncSession) -> None:
    """Наружу уходят типизированные объекты, а не словари."""
    repos = Repositories(session)
    user = await _make_user(repos)
    project = await _make_project(repos, user)
    await session.flush()

    listed = await repos.projects.list_for_user(user.id)

    assert [type(item) for item in listed] == [models.Project]
    assert not isinstance(listed[0], dict)
    assert listed[0].id == project.id


# --- Задача 6: индексы и сортировки ------------------------------------------


async def test_list_for_user_sorted_by_last_opened_desc(session: AsyncSession) -> None:
    repos = Repositories(session)
    user = await _make_user(repos)
    base = _now()
    await _make_project(repos, user, name="Старая", last_opened_at=base - timedelta(days=3))
    await _make_project(repos, user, name="Свежая", last_opened_at=base)
    await _make_project(repos, user, name="Средняя", last_opened_at=base - timedelta(hours=5))
    await session.flush()

    listed = await repos.projects.list_for_user(user.id)

    assert [item.name for item in listed] == ["Свежая", "Средняя", "Старая"]


async def test_list_for_user_is_scoped_and_hides_deleted(session: AsyncSession) -> None:
    repos = Repositories(session)
    mine = await _make_user(repos, "mine@example.test")
    other = await _make_user(repos, "other@example.test")
    keep = await _make_project(repos, mine, name="Моя")
    gone = await _make_project(repos, mine, name="Удаленная")
    await _make_project(repos, other, name="Чужая")
    await session.flush()

    await repos.projects.soft_delete(gone.id)

    listed = await repos.projects.list_for_user(mine.id)
    assert [item.id for item in listed] == [keep.id]


async def test_touch_opened_moves_project_to_top(session: AsyncSession) -> None:
    repos = Repositories(session)
    user = await _make_user(repos)
    base = _now()
    first = await _make_project(repos, user, name="Первая", last_opened_at=base)
    second = await _make_project(
        repos, user, name="Вторая", last_opened_at=base - timedelta(days=1)
    )
    await session.flush()

    await repos.projects.touch_opened(second.id, at=base + timedelta(minutes=1))

    listed = await repos.projects.list_for_user(user.id)
    assert [item.id for item in listed] == [second.id, first.id]


async def test_versions_of_project_are_listed_in_order(session: AsyncSession) -> None:
    repos = Repositories(session)
    user = await _make_user(repos)
    project = await _make_project(repos, user)
    await session.flush()
    base = _now()
    original = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Оригинал",
            kind=enums.VersionKind.ORIGINAL,
            created_by="AI-директор",
            created_at=base - timedelta(minutes=10),
        )
    )
    band = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Для группы",
            kind=enums.VersionKind.BAND,
            created_by="AI-директор",
            parent_version_id=original.id,
            created_at=base,
        )
    )
    await session.flush()

    listed = await repos.versions.list_for_project(project.id)

    assert [item.id for item in listed] == [original.id, band.id]
    assert listed[1].parent_version_id == original.id


async def test_required_indexes_exist(engine: AsyncEngine) -> None:
    """Индексы под список песен и под выборку версий заведены явно."""
    async with engine.connect() as connection:
        rows = await connection.execute(
            sa.text("select indexname from pg_indexes where schemaname = current_schema()")
        )
        names = {row[0] for row in rows}

    assert "ix_projects_user_last_opened" in names
    assert "ix_versions_project_created" in names


# --- Задача 5: единица работы ------------------------------------------------


async def test_session_scope_commits_on_success(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    async with session_scope(factory=session_factory) as scoped:
        repos = Repositories(scoped)
        user = await _make_user(repos, "commit@example.test")
        user_id = user.id

    found = await session.get(models.User, user_id)
    assert found is not None


async def test_session_scope_rolls_back_on_error(
    session_factory: async_sessionmaker[AsyncSession], session: AsyncSession
) -> None:
    captured: list[uuid.UUID] = []

    with pytest.raises(RuntimeError, match="сорвал"):
        async with session_scope(factory=session_factory) as scoped:
            repos = Repositories(scoped)
            user = await _make_user(repos, "rollback@example.test")
            await scoped.flush()
            captured.append(user.id)
            raise RuntimeError("запрос сорвался")

    assert captured, "Пользователь не был создан, тест ничего не проверяет."
    assert await session.get(models.User, captured[0]) is None


# --- Задача 7 и 9: мягкое удаление, каскад, необратимость --------------------


async def _project_with_full_tree(
    repos: Repositories, session: AsyncSession
) -> tuple[models.Project, dict[str, uuid.UUID]]:
    user = await _make_user(repos, f"tree-{uuid.uuid4().hex[:8]}@example.test")
    project = await _make_project(repos, user)
    await session.flush()

    upload = await repos.uploads.create(
        UploadCreate(
            project_id=project.id,
            file_name="late-train-home-demo.mp3",
            file_format=enums.UploadFormat.MP3,
            duration_seconds=222,
            quality=enums.UploadQuality.MEDIUM,
            source_note="Демо",
            storage_key="uploads/late-train-home.mp3",
        )
    )
    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Для группы",
            kind=enums.VersionKind.BAND,
            created_by="AI-директор",
            artifacts_snapshot=[{"id": "full-score", "type": "score"}],
        )
    )
    await session.flush()
    job = await repos.jobs.create(
        JobCreate(project_id=project.id, idempotency_key=uuid.uuid4().hex)
    )
    await session.flush()
    step = await repos.job_steps.create(
        JobStepCreate(job_id=job.id, step_key="normalize", label="Нормализация аудио", position=0)
    )
    artifact = await repos.artifacts.create(
        ArtifactCreate(
            project_id=project.id,
            version_id=version.id,
            artifact_type=enums.ArtifactType.SCORE,
            name="Общая партитура",
            artifact_format=enums.ArtifactFormat.PDF,
            confidence=0.82,
            audience=enums.ArtifactAudience.ALL,
            storage_key="artifacts/full-score.pdf",
        )
    )
    issue = await repos.review_issues.create(
        ReviewIssueCreate(
            project_id=project.id,
            title="Проверить гитарный акцент",
            section_id="chorus-1",
            bar=21,
            part="Гитара",
            reason="Аудиослой содержит две гитары.",
            confidence=0.62,
        )
    )
    await session.flush()
    comment = await repos.review_comments.create(
        ReviewCommentCreate(issue_id=issue.id, author="Илья", text="Сыграю одной партией.")
    )
    musician = await repos.musicians.create(
        MusicianCreate(
            project_id=project.id,
            name="Илья",
            role=enums.MusicianRole.GUITAR,
            instrument_note="электрогитара, строй E",
            constraint_note="играет один за две партии",
            level=enums.MusicianLevel.MIDDLE,
        )
    )
    recipient = await repos.share_recipients.create(
        ShareRecipientCreate(
            project_id=project.id,
            name="Илья",
            role=enums.ShareRecipientRole.GUITARIST,
            material="Гитара + TAB",
        )
    )
    await session.flush()

    return project, {
        "upload": upload.id,
        "version": version.id,
        "job": job.id,
        "job_step": step.id,
        "artifact": artifact.id,
        "issue": issue.id,
        "comment": comment.id,
        "musician": musician.id,
        "recipient": recipient.id,
    }


async def test_soft_delete_project_reaches_every_derivative(session: AsyncSession) -> None:
    """Удаление проекта доходит до всех производных, а не только до строки проекта."""
    repos = Repositories(session)
    project, ids = await _project_with_full_tree(repos, session)

    await repos.projects.soft_delete(project.id)

    assert await repos.projects.get(project.id) is None
    assert await repos.uploads.get(ids["upload"]) is None
    assert await repos.versions.get(ids["version"]) is None
    assert await repos.jobs.get(ids["job"]) is None
    assert await repos.job_steps.get(ids["job_step"]) is None
    assert await repos.artifacts.get(ids["artifact"]) is None
    assert await repos.review_issues.get(ids["issue"]) is None
    assert await repos.review_comments.get(ids["comment"]) is None
    assert await repos.musicians.get(ids["musician"]) is None
    assert await repos.share_recipients.get(ids["recipient"]) is None

    still_there = await repos.projects.get(project.id, include_deleted=True)
    assert still_there is not None and still_there.deleted_at is not None


async def test_soft_delete_sets_retention_until_on_derivatives(session: AsyncSession) -> None:
    repos = Repositories(session)
    project, ids = await _project_with_full_tree(repos, session)
    until = _now() + timedelta(days=30)

    await repos.projects.soft_delete(project.id, retention_until=until)

    artifact = await repos.artifacts.get(ids["artifact"], include_deleted=True)
    assert artifact is not None
    assert artifact.retention_until is not None
    assert abs((artifact.retention_until - until).total_seconds()) < 1


async def test_soft_delete_is_idempotent(session: AsyncSession) -> None:
    """Повторный запуск на уже удаленном проекте завершается успехом.

    Требование `DELETION_AND_RETENTION_DESIGN.md`: удаление идемпотентно.
    """
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)

    first = await repos.projects.soft_delete(project.id)
    second = await repos.projects.soft_delete(project.id)

    assert first.deleted_at == second.deleted_at


async def test_soft_delete_cannot_be_undone_at_database_level(session: AsyncSession) -> None:
    """Необратимость проверяется базой, а не вежливостью вызывающего кода.

    Репозиторий не дает метода восстановления, но одного этого мало: прямой
    UPDATE обошел бы обещание. Триггер запрещает обнулять `deleted_at`.
    """
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)
    await repos.projects.soft_delete(project.id)
    await session.flush()

    with pytest.raises(DBAPIError):
        await session.execute(
            sa.update(models.Project)
            .where(models.Project.id == project.id)
            .values(deleted_at=None)
            .execution_options(synchronize_session=False)
        )


async def test_repository_exposes_no_restore(session: AsyncSession) -> None:
    repos = Repositories(session)
    for name in ("restore", "undelete", "revive"):
        assert not hasattr(repos.projects, name), f"Метод {name} нарушает необратимость удаления."


async def test_review_comment_dies_with_its_issue(session: AsyncSession) -> None:
    repos = Repositories(session)
    project, ids = await _project_with_full_tree(repos, session)

    await repos.review_issues.soft_delete(ids["issue"])

    assert await repos.review_comments.get(ids["comment"]) is None
    assert await repos.projects.get(project.id) is not None


# --- Задача 7: две операции удаления из дизайн-дока ---------------------------


async def test_delete_source_keeps_results_and_metadata(session: AsyncSession) -> None:
    """`delete-source`: исходник уходит, разбор и материалы остаются."""
    repos = Repositories(session)
    project, ids = await _project_with_full_tree(repos, session)

    updated = await repos.projects.request_source_deletion(project.id)

    assert await repos.uploads.get(ids["upload"]) is None
    assert await repos.artifacts.get(ids["artifact"]) is not None
    assert await repos.projects.get(project.id) is not None
    assert updated.name == "Late Train Home"

    upload = await repos.uploads.get(ids["upload"], include_deleted=True)
    assert upload is not None and upload.storage_key is None


async def test_delete_results_keeps_version_history_without_files(session: AsyncSession) -> None:
    """`delete-results`: артефакты уходят, история версий остается перечнем изменений.

    Снимок материалов внутри версии — это тоже материалы. Если его не очистить,
    «результаты удалены» становится неправдой.
    """
    repos = Repositories(session)
    project, ids = await _project_with_full_tree(repos, session)

    await repos.projects.request_results_deletion(project.id)

    assert await repos.artifacts.get(ids["artifact"]) is None
    version = await repos.versions.get(ids["version"])
    assert version is not None
    assert version.artifacts_snapshot is None
    assert await repos.uploads.get(ids["upload"]) is not None


async def test_deletion_state_stays_pending_until_storage_confirms(session: AsyncSession) -> None:
    """Пока хранилище не подтвердило удаление, статус не «удалено».

    Объектного хранилища еще нет, и писать `purged` было бы ложным обещанием.
    """
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)

    updated = await repos.projects.request_results_deletion(project.id)

    assert updated.results_deletion_state is enums.DeletionState.PURGE_REQUESTED
    assert updated.results_purged_at is None


async def test_confirm_purge_requires_receipt_and_finishes_deletion(session: AsyncSession) -> None:
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)
    await repos.projects.request_source_deletion(project.id)

    confirmed = await repos.projects.confirm_purged(
        project.id, scope=DeletionScope.SOURCE, receipt="s3://bucket/audit/2026-09-10"
    )

    assert confirmed.source_deletion_state is enums.DeletionState.PURGED
    assert confirmed.source_purged_at is not None
    assert confirmed.source_purge_receipt == "s3://bucket/audit/2026-09-10"


async def test_confirm_purge_without_request_is_refused(session: AsyncSession) -> None:
    """Нельзя объявить удаленным то, удаление чего никто не запрашивал."""
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)

    with pytest.raises(DeletionStateError):
        await repos.projects.confirm_purged(
            project.id, scope=DeletionScope.SOURCE, receipt="подтверждение"
        )


async def test_purge_failure_is_recorded_for_alerting(session: AsyncSession) -> None:
    """Исчерпание попыток — инцидент, значит состояние должно быть видно в базе."""
    repos = Repositories(session)
    project, _ = await _project_with_full_tree(repos, session)
    await repos.projects.request_results_deletion(project.id)

    failed = await repos.projects.mark_purge_failed(
        project.id, scope=DeletionScope.RESULTS, reason="провайдер не ответил"
    )

    assert failed.results_deletion_state is enums.DeletionState.PURGE_FAILED
    assert failed.results_purge_error == "провайдер не ответил"


async def test_physical_purge_is_honestly_not_implemented() -> None:
    """Заглушка обязана называть себя заглушкой, а не возвращать «успех»."""
    with pytest.raises(NotImplementedError) as error:
        purge_objects(["uploads/late-train-home.mp3"])
    assert "хранилищ" in str(error.value).lower()


async def test_retention_period_is_not_invented_here() -> None:
    """Срок не выдуман на месте: он взят из единственного источника.

    Посылка прежней проверки умерла. Она требовала `None` и ссылалась на
    незаполненный дизайн-док; сроки с тех пор решены и лежат в
    `app/storage/retention.py` с обоснованием по каждому. Требовать `None`
    дальше — значит охранять отсутствие решения, которого уже нет.

    Охраняемая ценность та же: величина не заводится здесь. Проверяем это
    прямо — совпадением с источником, а не повторением числа. Число,
    переписанное в тест руками, разойдется с источником ровно так же молча,
    как разошлись когда-то два модуля сроков.
    """
    moment = _now()

    assert resolve_retention_until(moment) == retention_until("results", moment)


async def test_unknown_retention_kind_is_refused() -> None:
    """Незнакомый род падает, а не берет срок наугад.

    Молчаливое умолчание тут стоит дороже падения: срок, взятый наугад, либо
    стирает оплаченный результат раньше разрешенного, либо хранит чужую
    фонограмму дольше обещанного.
    """
    with pytest.raises(ValueError):
        resolve_retention_until(_now(), kind="выдуманный-род")


# --- Задача 10: демо-данные --------------------------------------------------


async def test_seed_creates_three_demo_projects(session: AsyncSession) -> None:
    seeded = await seed_demo_projects(session)

    assert len(seeded) == 3
    assert {item.name for item in seeded} == {
        "Late Train Home: подготовка к репетиции",
        "Warm Lights: урок гитары",
        "School Hall: ансамбль учеников",
    }
    assert len(DEMO_PROJECT_KEYS) == 3


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    first = await seed_demo_projects(session)
    second = await seed_demo_projects(session)

    assert [item.id for item in first] == [item.id for item in second]

    total = await session.scalar(sa.select(sa.func.count()).select_from(models.Project))
    assert total == 3


async def test_seed_fills_derivatives_of_demo_projects(session: AsyncSession) -> None:
    """Демо-проект без материалов и версий не демо, а пустая строка в таблице."""
    seeded = await seed_demo_projects(session)
    repos = Repositories(session)
    band = next(item for item in seeded if item.name.startswith("Late Train Home"))

    versions = await repos.versions.list_for_project(band.id)
    artifacts = await repos.artifacts.list_for_project(band.id)
    issues = await repos.review_issues.list_for_project(band.id)
    musicians = await repos.musicians.list_for_project(band.id)
    recipients = await repos.share_recipients.list_for_project(band.id)

    assert len(versions) == 2
    assert len(artifacts) >= 10
    assert len(issues) == 2
    assert len(musicians) == 5
    assert len(recipients) == 5
    assert band.current_version_id is not None
