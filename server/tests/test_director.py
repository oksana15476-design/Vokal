"""Тесты действий AI-директора.

Написаны до реализации. Проверяются три обещания продукта.

1. **Команда, которой нет, не подменяется похожей.** Незнакомый код действия —
   отказ, который называет поддерживаемые коды. Правило проекта: музыкальные
   изменения применяет детерминированный слой, и «угадать намерение» здесь
   означает молча сделать с песней не то, о чем просили.
2. **Действие создает версию.** Не правит текущую: иначе по истории не понять,
   откуда взялись изменения и куда откатываться.
3. **Пакет действий дает одну версию.** Пять правок пакетом — один шаг истории
   и один откат, а не пять.

Чего здесь намеренно нет: проверок «предложения директора» и «разговор». За
ними стоят разбор песни и LLM-адаптер, которых в продукте нет, — и тесты
удерживают именно отказ, а не выдуманный ответ.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.api.schemas.enums import DirectorActionId
from app.db import enums, models
from app.db.repositories import (
    ArtifactCreate,
    ProjectCreate,
    ProjectPatch,
    Repositories,
    UserCreate,
    VersionCreate,
)
from app.services import director as director_service

pytestmark = pytest.mark.asyncio

SAMPLE_ID = "00000000-0000-0000-0000-000000000000"


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


async def make_song(session: AsyncSession) -> dict[str, Any]:
    """Песня с текущей версией и четырьмя материалами разных типов."""
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

    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Для группы",
            kind=enums.VersionKind.BAND,
            created_by="AI-директор",
            status=enums.VersionStatus.NEEDS_REVIEW,
            created_at=datetime.now(UTC) - timedelta(minutes=30),
            changes=["Партии разложены на состав."],
            artifacts_snapshot=[],
        )
    )
    await session.flush()

    artifacts: dict[str, models.Artifact] = {}
    plan = (
        ("score", enums.ArtifactType.SCORE, enums.ArtifactFormat.PDF, "Партитура"),
        ("practice", enums.ArtifactType.PRACTICE, enums.ArtifactFormat.WAV, "Репетиционный трек"),
        ("zip", enums.ArtifactType.ZIP, enums.ArtifactFormat.ZIP, "Пакет к репетиции"),
        ("stem", enums.ArtifactType.STEM, enums.ArtifactFormat.WAV, "Аудиослои"),
    )
    for key, artifact_type, artifact_format, name in plan:
        artifacts[key] = await repos.artifacts.create(
            ArtifactCreate(
                project_id=project.id,
                version_id=version.id,
                artifact_type=artifact_type,
                name=name,
                artifact_format=artifact_format,
                status=enums.ArtifactStatus.READY,
                confidence=0.9,
                audience=enums.ArtifactAudience.BAND,
            )
        )
    await repos.projects.update(project.id, ProjectPatch(current_version_id=version.id))
    await session.flush()

    return {"user": user, "project": project, "version": version, "artifacts": artifacts}


# --- закрытый список действий ------------------------------------------------


async def test_every_action_of_the_contract_has_a_rule() -> None:
    """Список закрыт с двух сторон: код без правила — это обещание без исполнения."""
    assert set(director_service.ACTIONS) == set(DirectorActionId)


async def test_rule_lookup_of_unknown_action_names_the_supported_ones() -> None:
    """Даже если код действия однажды разойдется со списком правил, отказ назовет свои."""
    with pytest.raises(director_service.ProjectRefusal) as raised:
        director_service.rule_for("сделай красиво")  # type: ignore[arg-type]

    refusal = raised.value
    assert refusal.status_code == 422
    assert refusal.code == "unknown_director_action"
    assert set(refusal.details["supported"]) == {item.value for item in DirectorActionId}


async def test_unknown_action_is_refused_with_the_supported_list(session: AsyncSession) -> None:
    """Отказ обязан перечислить поддерживаемое, а не просто сказать «нельзя»."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "make-it-better", "baseVersionId": str(song["version"].id)},
        )

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert [item["field"] for item in error["details"]["fields"]] == ["body.actionId"]
    reasons = " ".join(item["reason"] for item in error["details"]["fields"])
    # Отказ на русском и с перечнем: сообщение генератора схемы сказало бы то же
    # самое по-английски и другими словами, а тексты ошибок в продукте русские.
    assert "Такого действия нет" in reasons
    assert "transpose-down-2" in reasons and "merge-guitars" in reasons

    repos = Repositories(session)
    versions = await repos.versions.list_for_project(song["project"].id)
    assert len(versions) == 1, "непонятая команда не должна создавать версию"


async def test_unknown_action_in_a_batch_stops_the_whole_batch(session: AsyncSession) -> None:
    """Половина пакета — хуже отказа: пользователь не узнает, что применилось."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions/batch",
            json={
                "actionIds": ["merge-guitars", "сделай мощнее"],
                "baseVersionId": str(song["version"].id),
            },
        )

    assert response.status_code == 422
    reasons = " ".join(item["reason"] for item in error_of(response)["details"]["fields"])
    assert "Такого действия нет" in reasons

    repos = Repositories(session)
    assert len(await repos.versions.list_for_project(song["project"].id)) == 1


async def test_repeated_action_in_one_batch_is_refused(session: AsyncSession) -> None:
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions/batch",
            json={
                "actionIds": ["merge-guitars", "merge-guitars"],
                "baseVersionId": str(song["version"].id),
            },
        )

    assert response.status_code == 422


# --- одно действие -----------------------------------------------------------


async def test_action_creates_a_new_version_and_keeps_the_base(session: AsyncSession) -> None:
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(song["version"].id)},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["appliedActionIds"] == ["merge-guitars"]
    assert body["version"]["label"] == "Одна гитара"
    assert body["version"]["kind"] == "band"
    assert body["version"]["parentVersionId"] == str(song["version"].id)
    assert body["version"]["isCurrent"] is True
    assert body["result"]["historyTitle"] == "Гитарные партии объединены для одного гитариста"
    assert body["version"]["changes"] == body["result"]["changes"]

    repos = Repositories(session)
    versions = await repos.versions.list_for_project(song["project"].id)
    assert len(versions) == 2
    base = await repos.versions.get(song["version"].id)
    assert base is not None
    assert base.label == "Для группы"
    assert base.changes == ["Партии разложены на состав."]

    project = await repos.projects.get(song["project"].id)
    assert project is not None
    assert str(project.current_version_id) == body["version"]["id"]


async def test_action_marks_only_the_materials_it_touches(session: AsyncSession) -> None:
    """`merge-guitars` не трогает аудиослои: помечать их устаревшими — врать."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(song["version"].id)},
        )

    assert response.status_code == 201, response.text
    assert set(response.json()["result"]["staleArtifactTypes"]) == {
        "score",
        "part",
        "tab",
        "midi",
        "zip",
    }

    repos = Repositories(session)
    score = await repos.artifacts.get(song["artifacts"]["score"].id)
    bundle = await repos.artifacts.get(song["artifacts"]["zip"].id)
    stem = await repos.artifacts.get(song["artifacts"]["stem"].id)
    assert score is not None and bundle is not None and stem is not None
    assert (score.is_stale, score.status) == (True, enums.ArtifactStatus.NEEDS_REVIEW)
    assert (bundle.is_stale, bundle.status) == (True, enums.ArtifactStatus.REBUILD_REQUIRED)
    assert (stem.is_stale, stem.status) == (False, enums.ArtifactStatus.READY)


async def test_materials_move_to_the_new_version(session: AsyncSession) -> None:
    """Материалы принадлежат версии: иначе пакет к репетиции показывает чужой набор."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(song["version"].id)},
        )

    created = uuid.UUID(response.json()["version"]["id"])
    repos = Repositories(session)
    assert len(await repos.artifacts.list_for_version(created)) == 4
    assert await repos.artifacts.list_for_version(song["version"].id) == []


async def test_new_version_keeps_the_snapshot_of_its_materials(session: AsyncSession) -> None:
    """Без снимка откат вернул бы структуру песни без материалов той версии."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(song["version"].id)},
        )

    snapshot = response.json()["version"]["artifactsSnapshot"]
    assert snapshot is not None
    assert len(snapshot) == 4
    by_id = {item["id"]: item for item in snapshot}
    assert by_id[str(song["artifacts"]["score"].id)]["status"] == "needs_review"
    assert by_id[str(song["artifacts"]["stem"].id)]["isStale"] is False


async def test_action_on_a_version_that_is_not_current_is_refused(session: AsyncSession) -> None:
    """Правка легла бы на версию, которую пользователь уже не видит на экране."""
    song = await make_song(session)
    repos = Repositories(session)
    stale_base = await repos.versions.create(
        VersionCreate(
            project_id=song["project"].id,
            label="Старая",
            kind=enums.VersionKind.BAND,
            created_by="AI-директор",
            created_at=datetime.now(UTC) - timedelta(hours=3),
        )
    )
    await session.flush()
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(stale_base.id)},
        )

    assert response.status_code == 409
    error = error_of(response)
    assert error["code"] == "version_conflict"
    assert error["details"]["currentVersionId"] == str(song["version"].id)


async def test_user_comment_stays_in_the_version_history(session: AsyncSession) -> None:
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={
                "actionId": "merge-guitars",
                "baseVersionId": str(song["version"].id),
                "comment": "второй гитарист не придет на концерт",
            },
        )

    assert response.status_code == 201, response.text
    assert any(
        "второй гитарист не придет на концерт" in line
        for line in response.json()["version"]["changes"]
    )


async def test_action_on_an_unanalysed_song_is_refused(session: AsyncSession) -> None:
    """Аранжировать нечего: ни разбора, ни материалов.

    Запись «гитарные партии объединены» в истории песни, которую никто не
    разбирал, — утверждение о песне, за которым ничего нет. Отказ честнее.
    """
    repos = Repositories(session)
    user = await repos.users.create(UserCreate(contact=f"solo-{uuid.uuid4().hex[:8]}@example.test"))
    project = await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Файл еще не разобран",
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
        )
    )
    await session.flush()
    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Черновик",
            kind=enums.VersionKind.BAND,
            created_by="Пользователь",
            created_at=datetime.now(UTC),
            changes=["Песня заведена. Файл еще не загружен."],
        )
    )
    await session.flush()
    await repos.projects.update(project.id, ProjectPatch(current_version_id=version.id))
    await session.flush()
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(version.id)},
        )

    assert response.status_code == 409
    assert error_of(response)["code"] == "nothing_to_arrange"
    assert len(await repos.versions.list_for_project(project.id)) == 1


async def test_action_is_allowed_when_there_are_materials_without_analysis(
    session: AsyncSession,
) -> None:
    """Материалы есть — есть что помечать, и действие работает."""
    song = await make_song(session)
    repos = Repositories(session)
    await repos.projects.update(song["project"].id, ProjectPatch(analysis=None))
    await session.flush()
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": str(song["version"].id)},
        )

    assert response.status_code == 201, response.text


# --- пакет действий ----------------------------------------------------------


async def test_batch_builds_one_version_not_a_chain(session: AsyncSession) -> None:
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions/batch",
            json={
                "actionIds": ["merge-guitars", "simplify-drums"],
                "baseVersionId": str(song["version"].id),
                "label": "Версия для репетиции",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["appliedActionIds"] == ["merge-guitars", "simplify-drums"]
    assert body["version"]["label"] == "Версия для репетиции"
    assert body["result"]["historyTitle"] == "Собрана версия из 2 предложений"
    assert len(body["result"]["changes"]) == 4
    assert "practice" in body["result"]["staleArtifactTypes"]

    repos = Repositories(session)
    versions = await repos.versions.list_for_project(song["project"].id)
    assert len(versions) == 2, "пакет обязан дать одну версию, а не цепочку"


async def test_batch_of_one_action_behaves_like_a_single_action(session: AsyncSession) -> None:
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/actions/batch",
            json={
                "actionIds": ["simplify-drums"],
                "baseVersionId": str(song["version"].id),
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"]["label"] == "Барабаны проще"
    assert body["result"]["historyTitle"] == "Барабаны упрощены"


# --- то, чего нет ------------------------------------------------------------


async def test_suggestions_are_refused_instead_of_invented(session: AsyncSession) -> None:
    """Предложение — утверждение о конкретной песне. Без разбора его брать неоткуда."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{song['project'].id}/director/suggestions")

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert any("SongGraph" in item for item in error["details"]["missing"])


async def test_chat_is_refused_instead_of_guessing(session: AsyncSession) -> None:
    """Разбора языка в продукте нет: похожая команда вместо непонятой — обман."""
    song = await make_song(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/director/chat",
            json={"text": "сделай припев мощнее"},
        )

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert any("LLM" in item for item in error["details"]["missing"])


async def test_actions_answer_not_implemented_without_wiring() -> None:
    app = build_contract_app()

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{SAMPLE_ID}/director/actions",
            json={"actionId": "merge-guitars", "baseVersionId": SAMPLE_ID},
        )

    assert response.status_code == 501
    assert error_of(response)["details"]["missing"]
