"""Тесты выдачи материалов: получатели, ссылки, архивы.

Написаны до реализации. Срез разделен надвое по одному признаку — есть ли под
адресом слой данных.

**Получатели есть.** Таблица `share_recipients` заведена (`app/db/models.py`),
поэтому список, добавление и правка получателя обязаны работать по-настоящему
и закрывать чужой проект.

**Ссылок и архивов нет.** Таблицы выданных ссылок в схеме базы нет вовсе:
ни `share_links`, ни `export_bundles`. Без нее нельзя ни задать ссылке срок
жизни, ни отозвать ее, а отзыв — требование
`docs/DELETION_AND_RETENTION_DESIGN.md`, без которого «удалить результаты» не
исполняется для уже выданных ссылок. Поэтому здесь проверяется не выдача, а
честность отказа: адрес обязан назвать недостающую таблицу и не обязан врать
про отсутствующее хранилище — хранилище как раз есть (`app/storage/`).

Тест на «отозванная ссылка перестает работать» появится вместе с таблицей;
описание нужной правки лежит в отчете батча, а не изображается зеленым
прогоном здесь.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.db import enums as db_enums
from app.db import models
from app.db.repositories import ProjectCreate, Repositories, ShareRecipientCreate, UserCreate

pytestmark = pytest.mark.asyncio


# --- фикстуры ---------------------------------------------------------------


async def make_project(
    session: AsyncSession, *, contact: str = "band@example.test"
) -> models.Project:
    repos = Repositories(session)
    user = await repos.users.create(UserCreate(contact=contact))
    return await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Late Train Home",
            scenario=db_enums.Scenario.BAND,
            processing_goal_id=db_enums.ProcessingGoalId.BAND_REHEARSAL,
        )
    )


async def add_recipient(
    session: AsyncSession,
    project: models.Project,
    *,
    name: str = "Аня",
    role: db_enums.ShareRecipientRole = db_enums.ShareRecipientRole.VOCALIST,
    position: int = 0,
) -> models.ShareRecipient:
    repos = Repositories(session)
    return await repos.share_recipients.create(
        ShareRecipientCreate(project_id=project.id, name=name, role=role, position=position)
    )


def build_app(session: AsyncSession, user_id: object):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


# --- честный отказ там, где швов еще нет ------------------------------------


async def test_recipients_are_refused_while_wiring_is_missing() -> None:
    app = build_contract_app()
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{uuid.uuid4()}/recipients")

    assert response.status_code == 501
    assert error_of(response)["details"]["missing"]


# --- получатели: работают по-настоящему -------------------------------------


async def test_recipient_is_created_and_listed(session: AsyncSession) -> None:
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        created = await client.post(
            f"/api/projects/{project.id}/recipients",
            json={"name": "Аня", "role": "vocalist", "material": "Партия вокала и текст"},
        )
        listed = await client.get(f"/api/projects/{project.id}/recipients")

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Аня"
    assert body["role"] == "vocalist"
    assert body["material"] == "Партия вокала и текст"
    # Ссылок выдавать нечем, и статус говорит об этом прямо, а не «выдано».
    assert body["status"] == "not_issued"

    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]


async def test_recipient_is_stored_in_database_not_in_answer(session: AsyncSession) -> None:
    """Добавленный получатель существует в базе, а не только в ответе."""
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        created = await client.post(
            f"/api/projects/{project.id}/recipients",
            json={"name": "Петя", "role": "drummer"},
        )

    assert created.status_code == 201, created.text
    repos = Repositories(session)
    stored = await repos.share_recipients.list_for_project(project.id)
    assert [item.name for item in stored] == ["Петя"]
    assert stored[0].role is db_enums.ShareRecipientRole.DRUMMER


async def test_recipient_update_changes_only_named_fields(session: AsyncSession) -> None:
    project = await make_project(session)
    recipient = await add_recipient(session, project, name="Аня")
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{project.id}/recipients/{recipient.id}",
            json={"material": "Партия вокала, куплет 2"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["material"] == "Партия вокала, куплет 2"
    assert body["name"] == "Аня", "не названное в запросе поле переписано"
    assert body["role"] == "vocalist"


async def test_recipients_are_paginated(session: AsyncSession) -> None:
    project = await make_project(session)
    for index in range(3):
        await add_recipient(session, project, name=f"Музыкант {index}", position=index)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.get(
            f"/api/projects/{project.id}/recipients", params={"limit": 2, "offset": 1}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Музыкант 1", "Музыкант 2"]
    assert body["total"] == 3, "total — это сколько всего, а не сколько влезло на страницу"


# --- чужое закрыто ----------------------------------------------------------


async def test_recipients_of_foreign_project_are_closed(session: AsyncSession) -> None:
    project = await make_project(session)
    await add_recipient(session, project)
    stranger = await make_project(session, contact="stranger@example.test")
    app = build_app(session, stranger.user_id)

    async with client_for(app) as client:
        listed = await client.get(f"/api/projects/{project.id}/recipients")
        created = await client.post(
            f"/api/projects/{project.id}/recipients",
            json={"name": "Чужой", "role": "teacher"},
        )

    assert listed.status_code == 403
    assert created.status_code == 403

    repos = Repositories(session)
    stored = await repos.share_recipients.list_for_project(project.id)
    assert len(stored) == 1, "запись добавлена в чужой проект"


async def test_recipient_of_another_project_is_not_found(session: AsyncSession) -> None:
    """Получатель чужой песни по своему адресу — «не найден», а не правка чужого."""
    mine = await make_project(session)
    other = await make_project(session, contact="other@example.test")
    foreign = await add_recipient(session, other, name="Не мой")
    app = build_app(session, mine.user_id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{mine.id}/recipients/{foreign.id}", json={"name": "Переименован"}
        )

    assert response.status_code == 404
    repos = Repositories(session)
    kept = await repos.share_recipients.get(foreign.id)
    assert kept is not None and kept.name == "Не мой"


async def test_unknown_project_is_not_found(session: AsyncSession) -> None:
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{uuid.uuid4()}/recipients")

    assert response.status_code == 404


# --- ссылки и архивы: отказ обязан называть настоящую причину ---------------

LINK_AND_BUNDLE_CALLS = (
    ("GET", "/share-links", None),
    ("POST", "/share-links", {"recipientId": "00000000-0000-0000-0000-000000000000"}),
    ("DELETE", "/share-links/00000000-0000-0000-0000-000000000000", None),
    ("GET", "/export-bundles", None),
    ("POST", "/export-bundles", {}),
    ("GET", "/export-bundles/00000000-0000-0000-0000-000000000000", None),
)


@pytest.mark.parametrize(("method", "tail", "payload"), LINK_AND_BUNDLE_CALLS)
async def test_links_and_bundles_refuse_and_name_the_missing_table(
    session: AsyncSession, method: str, tail: str, payload: dict | None
) -> None:
    """Отказ называет то, чего действительно нет, — таблицу выданных ссылок."""
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.request(
            method,
            f"/api/projects/{project.id}{tail}",
            json=payload if payload is not None else None,
        )

    assert response.status_code == 501, response.text
    error = error_of(response)
    assert error["code"] == "not_implemented"
    missing = " ".join(error["details"]["missing"]).lower()
    assert "share_links" in missing or "выданных ссылок" in missing, missing


@pytest.mark.parametrize(("method", "tail", "payload"), LINK_AND_BUNDLE_CALLS)
async def test_refusal_does_not_blame_storage_that_already_exists(
    session: AsyncSession, method: str, tail: str, payload: dict | None
) -> None:
    """Хранилище есть (`app/storage/`), и ссылаться на его отсутствие нельзя.

    Список недостающего — не украшение: по нему определяют, чей это батч.
    Названное неверно, оно отправляет работу не туда.
    """
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.request(
            method,
            f"/api/projects/{project.id}{tail}",
            json=payload if payload is not None else None,
        )

    missing = " ".join(error_of(response)["details"]["missing"]).lower()
    assert "объектное хранилище" not in missing, missing


async def test_share_link_refusal_never_returns_a_url(session: AsyncSession) -> None:
    """Отказ — это отказ, а не ссылка, по которой ничего нет."""
    project = await make_project(session)
    app = build_app(session, project.user_id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/share-links",
            json={"recipientId": str(uuid.uuid4()), "expiresInHours": 24},
        )

    assert response.status_code == 501
    assert "url" not in response.text.lower() or "http" not in response.text.lower()
