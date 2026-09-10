"""Версии аранжировки и откат.

Откат возможен на любую глубину: целью служит любая версия проекта, поэтому
цель стоит в адресе, а не выражается «шагом назад». Сам откат создает новую
версию, а не переписывает историю: иначе по списку версий нельзя понять,
почему материалы вдруг стали прежними.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.versions import (
    ArrangementVersionOut,
    VersionListResponse,
    VersionRollbackRequest,
    VersionRollbackResponse,
    VersionSelectRequest,
)

router = APIRouter(prefix="/projects/{project_id}/versions", tags=["версии"])

ProjectIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор проекта")]
VersionIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор версии")]

VERSION_ENGINE_MISSING = (
    "Version Engine: история версий и снимки материалов",
    "слой данных проекта (батч БД)",
)


@router.get(
    "",
    response_model=VersionListResponse,
    summary="Версии аранжировки",
    description="От исходной к последней, вместе с родителями и перечнем изменений.",
    responses=errors(401, 403, 404, 501),
)
async def list_versions(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/versions",
        message="Версий нет: аранжировка пока не ведется на сервере.",
        missing=VERSION_ENGINE_MISSING,
    )


@router.get(
    "/{version_id}",
    response_model=ArrangementVersionOut,
    summary="Одна версия",
    responses=errors(401, 403, 404, 501),
)
async def read_version(
    project_id: ProjectIdPath,
    version_id: VersionIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/versions/{version_id}",
        message="Версий нет: аранжировка пока не ведется на сервере.",
        missing=VERSION_ENGINE_MISSING,
    )


@router.patch(
    "/{version_id}/select",
    response_model=ArrangementVersionOut,
    summary="Сделать версию текущей",
    description="Переключение без создания новой версии: история при этом не меняется.",
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def select_version(
    project_id: ProjectIdPath,
    version_id: VersionIdPath,
    payload: VersionSelectRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="PATCH /api/projects/{project_id}/versions/{version_id}/select",
        message="Переключать нечего: версий на сервере пока нет.",
        missing=VERSION_ENGINE_MISSING,
    )


@router.post(
    "/{version_id}/rollback",
    response_model=VersionRollbackResponse,
    status_code=201,
    summary="Откатиться на указанную версию",
    description=(
        "Цель — любая версия проекта, глубина не ограничена. Создается новая версия со "
        "снимком материалов целевой; материалы, снимка которых не было, помечаются к пересборке."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def rollback_version(
    project_id: ProjectIdPath,
    version_id: VersionIdPath,
    payload: VersionRollbackRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/versions/{version_id}/rollback",
        message="Откатываться некуда: версий на сервере пока нет.",
        missing=VERSION_ENGINE_MISSING,
    )
