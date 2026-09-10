"""Проекты.

Проект создается из уже принятой загрузки, а не вместе с файлом: файл идет в
хранилище отдельным запросом, и связывать две долгие операции в одну — значит
терять обе при обрыве.

Согласие приходит здесь же и вместе с версией формулировки. Это не
формальность: без версии запись «согласие получено» остается без предмета, и
восстановить ее задним числом нечем.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import PageDep, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.enums import Scenario
from app.api.schemas.projects import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectOut,
    ProjectPatchRequest,
)

router = APIRouter(prefix="/projects", tags=["проекты"])

PROJECT_STORE_MISSING = (
    "слой данных проекта (батч БД)",
    "авторизация: у проекта должен быть владелец",
)


@router.post(
    "",
    response_model=ProjectOut,
    status_code=201,
    summary="Создать проект из загрузки",
    description=(
        "Сценарий, цель и типизированная настройка обязаны сойтись между собой. "
        "Согласие принимается только с известной сервером версией формулировки."
    ),
    responses=errors(401, 404, 409, 422, 501),
)
async def create_project(
    payload: ProjectCreateRequest,
    session: SessionDep,
    user_id: UserDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Ключ повтора. Повторный запрос с тем же ключом не создает второй проект: "
                "обрыв связи на ответе не должен превращаться в дубль."
            ),
        ),
    ] = None,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects",
        message="Проекты пока не сохраняются на сервере.",
        missing=PROJECT_STORE_MISSING,
    )


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="Список проектов",
    responses=errors(401, 422, 501),
)
async def list_projects(
    page: PageDep,
    session: SessionDep,
    user_id: UserDep,
    scenario: Annotated[Scenario | None, Query(description="Отбор по сценарию")] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="Поиск по названию проекта")
    ] = None,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects",
        message="Список проектов пока не ведется на сервере.",
        missing=PROJECT_STORE_MISSING,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Проект целиком",
    description="Карточка со всем, что показывает экран: разбор, материалы, версии, выдача.",
    responses=errors(401, 403, 404, 501),
)
async def read_project(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}",
        message="Проекты пока не сохраняются на сервере.",
        missing=PROJECT_STORE_MISSING,
    )


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Переименовать проект",
    responses=errors(401, 403, 404, 422, 501),
)
async def patch_project(
    project_id: ProjectIdPath,
    payload: ProjectPatchRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="PATCH /api/projects/{project_id}",
        message="Проекты пока не сохраняются на сервере.",
        missing=PROJECT_STORE_MISSING,
    )
