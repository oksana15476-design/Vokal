"""Версии аранжировки и откат.

Откат возможен на любую глубину: целью служит любая версия проекта, поэтому
цель стоит в адресе, а не выражается «шагом назад». Сам откат создает новую
версию, а не переписывает историю: иначе по списку версий нельзя понять,
почему материалы вдруг стали прежними.

Логика живет в `app/services/versions.py`, роутер только переводит ее отказы в
коды HTTP. Неизменяемость версии держит триггер базы, а не этот файл.

`501` остается там, где нет швов, а не там, где не дописан код: сессия базы и
владелец запроса в `app/api/deps.py` пока заглушки (`None`). Без них нельзя ни
прочитать историю, ни проверить, чья это песня.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import ProjectIdPath, SessionDep, UserDep, VersionIdPath
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.versions import (
    ArrangementVersionOut,
    VersionListResponse,
    VersionRollbackRequest,
    VersionRollbackResponse,
    VersionSelectRequest,
)
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import projects as projects_service
from app.services import versions as service

router = APIRouter(prefix="/projects/{project_id}/versions", tags=["версии"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="История версий не включена: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


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
) -> Response | VersionListResponse:
    blocked = _not_wired("GET /api/projects/{project_id}/versions", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        items = await service.list_versions(repos, project)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return VersionListResponse(
        items=[
            projects_service.version_out(item, current_version_id=project.current_version_id)
            for item in items
        ],
        current_version_id=(
            str(project.current_version_id) if project.current_version_id is not None else None
        ),
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
) -> Response | ArrangementVersionOut:
    blocked = _not_wired("GET /api/projects/{project_id}/versions/{version_id}", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        version = await service.version_of_project(repos, project, version_id)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return projects_service.version_out(version, current_version_id=project.current_version_id)


@router.patch(
    "/{version_id}/select",
    response_model=ArrangementVersionOut,
    summary="Сделать версию текущей",
    description=(
        "Переключение без создания новой версии: история при этом не меняется. Если "
        "материалы версии сейчас в работе у более поздней, переключение отвечает `409` и "
        "указывает на откат — он остается в истории."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def select_version(
    project_id: ProjectIdPath,
    version_id: VersionIdPath,
    payload: VersionSelectRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ArrangementVersionOut:
    blocked = _not_wired(
        "PATCH /api/projects/{project_id}/versions/{version_id}/select", session, user_id
    )
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        version = await service.version_of_project(repos, project, version_id)
        selected = await service.select(repos, project, version)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return projects_service.version_out(selected, current_version_id=selected.id)


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
) -> Response | VersionRollbackResponse:
    blocked = _not_wired(
        "POST /api/projects/{project_id}/versions/{version_id}/rollback", session, user_id
    )
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        target = await service.version_of_project(repos, project, version_id)
        outcome = await service.rollback(
            repos,
            project,
            target,
            label=payload.label,
            comment=payload.comment,
            now=datetime.now(UTC),
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return VersionRollbackResponse(
        version=projects_service.version_out(
            outcome.version, current_version_id=outcome.version.id
        ),
        restored_from_version_id=str(outcome.restored_from),
        restored_artifacts=[
            projects_service.artifact_out(artifact) for artifact in outcome.restored
        ],
        stale_artifact_ids=outcome.stale_artifact_ids,
    )
