"""Тесты Version Engine: история версий, снимок материалов, откат.

Написаны до реализации. Каждый проверяет обещание продукта, а не вызов функции.

1. **Версия неизменяема.** Ее держит база, а не дисциплина вызывающего кода:
   по списку версий нельзя понять, почему материалы стали прежними, если
   вчерашнюю версию можно переписать одним `UPDATE`. Единственное послабление —
   снимок материалов можно **стереть**: удаление результатов уносит и его
   (`docs/DELETION_AND_RETENTION_DESIGN.md`), но заменить снимок другим нельзя.
2. **Откат создает новую версию.** Не переписывает целевую и не стирает те,
   что были между ними: откат — такое же событие истории, как правка.
3. **Снимка нет — так и сказано.** Материалы, для которых снимка не было, не
   выдаются за восстановленные, а помечаются к пересборке.

База настоящая: проверяется то, что доедет до сервера.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.db import enums, models
from app.db.repositories import (
    ArtifactCreate,
    ProjectCreate,
    ProjectPatch,
    Repositories,
    UserCreate,
    VersionCreate,
)

pytestmark = pytest.mark.asyncio


# --- вспомогательное ---------------------------------------------------------


def build_app(session: AsyncSession, user_id: Any) -> FastAPI:
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


def snapshot_entry(artifact_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    """Одна запись снимка материалов.

    Литералом, а не вызовом сервиса: снимок лежит в базе и читается клиентом,
    поэтому его форма — часть контракта, и тест обязан ее удерживать сам.
    """
    entry: dict[str, Any] = {
        "id": str(artifact_id),
        "type": "score",
        "name": "Партитура",
        "format": "PDF",
        "description": "Полная партитура версии",
        "status": "ready",
        "confidence": 0.9,
        "audience": "all",
        "isStale": False,
        "preview": None,
        "updatedAt": None,
    }
    entry.update(overrides)
    return entry


async def make_project(session: AsyncSession) -> tuple[models.User, models.Project]:
    repos = Repositories(session)
    user = await repos.users.create(UserCreate(contact=f"band-{uuid.uuid4().hex[:8]}@example.test"))
    project = await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Late Train Home",
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
            analysis={"key": "Gm", "bpm": 92},
        )
    )
    await session.flush()
    return user, project


async def make_history(session: AsyncSession) -> dict[str, Any]:
    """Песня с двумя версиями и материалами на текущей.

    Первая версия несет снимок: по нему проверяется восстановление. Вторая
    держит живые строки материалов — то, что видит пользователь сейчас.
    """
    repos = Repositories(session)
    user, project = await make_project(session)
    moment = datetime.now(UTC) - timedelta(hours=1)

    score = await repos.artifacts.create(
        ArtifactCreate(
            project_id=project.id,
            artifact_type=enums.ArtifactType.SCORE,
            name="Партитура",
            artifact_format=enums.ArtifactFormat.PDF,
            description="Полная партитура версии",
            status=enums.ArtifactStatus.NEEDS_REVIEW,
            confidence=0.9,
            audience=enums.ArtifactAudience.ALL,
            is_stale=True,
        )
    )
    practice = await repos.artifacts.create(
        ArtifactCreate(
            project_id=project.id,
            artifact_type=enums.ArtifactType.PRACTICE,
            name="Трек для репетиции",
            artifact_format=enums.ArtifactFormat.WAV,
            status=enums.ArtifactStatus.READY,
            confidence=0.8,
            audience=enums.ArtifactAudience.BAND,
        )
    )
    await session.flush()

    original = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Оригинал",
            kind=enums.VersionKind.ORIGINAL,
            created_by="AI-директор",
            status=enums.VersionStatus.APPROVED,
            created_at=moment,
            changes=["Разбор песни готов."],
            artifacts_snapshot=[snapshot_entry(score.id)],
        )
    )
    band = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Для группы",
            kind=enums.VersionKind.BAND,
            created_by="AI-директор",
            parent_version_id=original.id,
            status=enums.VersionStatus.NEEDS_REVIEW,
            created_at=moment + timedelta(minutes=5),
            changes=["Партии разложены на состав."],
        )
    )
    await session.flush()
    for artifact in (score, practice):
        artifact.version_id = band.id
    await repos.projects.update(project.id, ProjectPatch(current_version_id=band.id))
    await session.flush()

    return {
        "user": user,
        "project": project,
        "original": original,
        "band": band,
        "score": score,
        "practice": practice,
    }


# --- неизменяемость версии ---------------------------------------------------


async def test_version_content_cannot_be_rewritten(session: AsyncSession) -> None:
    """Подпись версии нельзя переписать: историю держит база, а не договоренность."""
    history = await make_history(session)

    with pytest.raises(DBAPIError):
        await session.execute(
            sa.update(models.Version)
            .where(models.Version.id == history["original"].id)
            .values(label="Другая подпись")
            .execution_options(synchronize_session=False)
        )


async def test_version_changes_cannot_be_rewritten(session: AsyncSession) -> None:
    """Перечень изменений — то, ради чего история и ведется."""
    history = await make_history(session)

    with pytest.raises(DBAPIError):
        await session.execute(
            sa.update(models.Version)
            .where(models.Version.id == history["original"].id)
            .values(changes=["Здесь ничего не было."])
            .execution_options(synchronize_session=False)
        )


async def test_snapshot_can_only_be_cleared_never_replaced(session: AsyncSession) -> None:
    """Снимок стирается удалением результатов, но не подменяется другим."""
    history = await make_history(session)

    with pytest.raises(DBAPIError):
        await session.execute(
            sa.update(models.Version)
            .where(models.Version.id == history["original"].id)
            .values(artifacts_snapshot=[])
            .execution_options(synchronize_session=False)
        )


async def test_snapshot_is_cleared_by_results_deletion(session: AsyncSession) -> None:
    """Удаление результатов уносит снимок: снимок материалов — тоже материалы."""
    history = await make_history(session)
    repos = Repositories(session)

    await repos.projects.request_results_deletion(history["project"].id)

    version = await repos.versions.get(history["original"].id)
    assert version is not None
    assert version.artifacts_snapshot is None


async def test_soft_delete_of_version_still_works(session: AsyncSession) -> None:
    """Неизменяемость не должна ломать удаление: пометка удаления не правка истории."""
    history = await make_history(session)
    repos = Repositories(session)

    await repos.projects.soft_delete(history["project"].id)

    assert await repos.versions.get(history["original"].id) is None


# --- список и карточка версии ------------------------------------------------


async def test_history_is_listed_from_first_to_last(session: AsyncSession) -> None:
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{history['project'].id}/versions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["label"] for item in body["items"]] == ["Оригинал", "Для группы"]
    assert body["currentVersionId"] == str(history["band"].id)
    assert [item["isCurrent"] for item in body["items"]] == [False, True]


async def test_single_version_returns_its_snapshot(session: AsyncSession) -> None:
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.get(
            f"/api/projects/{history['project'].id}/versions/{history['original'].id}"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["parentVersionId"] is None
    assert body["changes"] == ["Разбор песни готов."]
    assert [item["id"] for item in body["artifactsSnapshot"]] == [str(history["score"].id)]


async def test_version_of_another_song_is_not_found(session: AsyncSession) -> None:
    history = await make_history(session)
    other = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.get(
            f"/api/projects/{history['project'].id}/versions/{other['band'].id}"
        )

    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


async def test_versions_of_a_stranger_are_closed(session: AsyncSession) -> None:
    history = await make_history(session)
    stranger = await make_history(session)
    app = build_app(session, stranger["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{history['project'].id}/versions")

    assert response.status_code == 403
    assert error_of(response)["code"] == "forbidden"


# --- откат -------------------------------------------------------------------


async def test_rollback_creates_new_version_and_leaves_the_target_alone(
    session: AsyncSession,
) -> None:
    """Главное правило: откат — новая запись истории, а не правка старой."""
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{history['original'].id}/rollback",
            json={"comment": "вернуться к оригиналу"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["restoredFromVersionId"] == str(history["original"].id)

    repos = Repositories(session)
    versions = await repos.versions.list_for_project(history["project"].id)
    assert len(versions) == 3, "откат обязан добавить версию, а не заменить существующую"

    target = await repos.versions.get(history["original"].id)
    assert target is not None
    assert target.label == "Оригинал"
    assert target.changes == ["Разбор песни готов."]
    assert target.artifacts_snapshot == [snapshot_entry(history["score"].id)]

    created = versions[-1]
    assert str(created.id) == body["version"]["id"]
    assert created.parent_version_id == history["band"].id
    assert created.created_by == "Пользователь"
    project = await repos.projects.get(history["project"].id)
    assert project is not None
    assert project.current_version_id == created.id


async def test_rollback_keeps_the_user_comment_in_history(session: AsyncSession) -> None:
    """Пояснение человека не теряется: иначе по истории не понять, почему откатились."""
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{history['original'].id}/rollback",
            json={"comment": "тональность не подошла вокалисту"},
        )

    assert response.status_code == 201, response.text
    assert any(
        "тональность не подошла вокалисту" in line for line in response.json()["version"]["changes"]
    )


async def test_rollback_restores_materials_of_the_target_version(session: AsyncSession) -> None:
    """Снимок для того и хранится: материалы возвращаются в состояние той версии."""
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{history['original'].id}/rollback",
            json={},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    restored = body["restoredArtifacts"]
    assert [item["id"] for item in restored] == [str(history["score"].id)]
    assert restored[0]["status"] == "ready"
    assert restored[0]["isStale"] is False
    assert body["staleArtifactIds"] == []

    repos = Repositories(session)
    score = await repos.artifacts.get(history["score"].id)
    assert score is not None
    assert score.status is enums.ArtifactStatus.READY
    assert score.is_stale is False
    assert score.version_id == uuid.UUID(body["version"]["id"])


async def test_rollback_without_snapshot_marks_materials_for_rebuild(
    session: AsyncSession,
) -> None:
    """Снимка не было — материалы не выдаются за восстановленные."""
    history = await make_history(session)
    repos = Repositories(session)
    empty = await repos.versions.create(
        VersionCreate(
            project_id=history["project"].id,
            label="Черновик",
            kind=enums.VersionKind.BAND,
            created_by="Пользователь",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await session.flush()
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{empty.id}/rollback",
            json={},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body["staleArtifactIds"]) == {
        str(history["score"].id),
        str(history["practice"].id),
    }
    assert all(item["isStale"] for item in body["restoredArtifacts"])
    assert all(item["status"] == "rebuild_required" for item in body["restoredArtifacts"])
    assert any("снимок" in line.lower() for line in body["version"]["changes"])


async def test_rollback_to_the_current_version_is_refused(session: AsyncSession) -> None:
    """Откатываться некуда: версия уже текущая. Пустая запись истории не нужна."""
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{history['band'].id}/rollback",
            json={},
        )

    assert response.status_code == 409
    assert error_of(response)["code"] == "version_already_current"


async def test_rollback_to_a_foreign_version_is_not_found(session: AsyncSession) -> None:
    history = await make_history(session)
    other = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{history['project'].id}/versions/{other['original'].id}/rollback",
            json={},
        )

    assert response.status_code == 404


# --- переключение текущей версии ---------------------------------------------


async def test_select_switches_current_version_without_new_record(
    session: AsyncSession,
) -> None:
    """Переключение не создает версию: история от него не меняется."""
    history = await make_history(session)
    repos = Repositories(session)
    sibling = await repos.versions.create(
        VersionCreate(
            project_id=history["project"].id,
            label="Учебная версия",
            kind=enums.VersionKind.EASY,
            created_by="AI-директор",
            parent_version_id=history["original"].id,
            created_at=datetime.now(UTC),
            changes=["Ритм упрощен до восьмых."],
            artifacts_snapshot=[],
        )
    )
    await session.flush()
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{history['project'].id}/versions/{sibling.id}/select",
            json={},
        )

    assert response.status_code == 200, response.text
    assert response.json()["isCurrent"] is True

    versions = await repos.versions.list_for_project(history["project"].id)
    assert len(versions) == 3, "переключение не должно добавлять версию"
    project = await repos.projects.get(history["project"].id)
    assert project is not None
    assert project.current_version_id == sibling.id


async def test_select_refuses_when_materials_are_held_by_another_version(
    session: AsyncSession,
) -> None:
    """У версии есть снимок, но материалы сейчас не у нее.

    Молча переключиться — показать пустой пакет там, где список версий обещает
    материалы. Возвращать их без записи в историю тоже нельзя: тогда по истории
    не понять, почему материалы стали прежними. Поэтому отказ с указанием на
    откат.
    """
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{history['project'].id}/versions/{history['original'].id}/select",
            json={},
        )

    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "materials_moved"
    assert "откат" in error["message"].lower()


async def test_select_of_the_current_version_is_not_an_error(session: AsyncSession) -> None:
    history = await make_history(session)
    app = build_app(session, history["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{history['project'].id}/versions/{history['band'].id}/select",
            json={},
        )

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(history["band"].id)


# --- честный отказ без швов --------------------------------------------------


async def test_versions_answer_not_implemented_without_wiring() -> None:
    """Без единицы работы базы и входа в аккаунт адрес отвечает отказом, а не выдумкой."""
    app = build_contract_app()
    sample = "00000000-0000-0000-0000-000000000000"

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{sample}/versions")

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert error["details"]["missing"]
