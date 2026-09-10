"""Проверка: статусы мест и комментарии.

Статус меняет человек, а не система: смысл слоя проверки в том, что
автоматический результат считается черновиком, пока музыкант не сказал иначе.
Поэтому сервер не переводит место в «проверено» сам ни при каких условиях.

Логика живет в `app/services/review.py`, роутер только переводит ее отказы в
коды HTTP. Отдельно стоит `501` у списка: он приходит не от отсутствия швов, а
от отсутствия разбора песни — пустой список у неразобранной песни читался бы
как «все в порядке».

Уверенность уходит наружу вместе с числом в процентах и, если числа нет, с
причиной — правило бренда держит схема (`app/api/schemas/review.py`).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.api.deps import IssueIdPath, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.enums import ReviewStatus
from app.api.schemas.review import (
    ReviewCommentCreate,
    ReviewCommentOut,
    ReviewIssueListResponse,
    ReviewIssueOut,
    ReviewIssueStatusUpdate,
)
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import projects as projects_service
from app.services import review as service

router = APIRouter(prefix="/projects/{project_id}/review-issues", tags=["проверка"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Проверка не включена: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(endpoint: str, error: projects_service.ProjectRefusal) -> Response:
    """Отказ сервиса в общем конверте.

    `501` собирается тем же помощником, что и заглушки: у отказа «этого еще
    нет» одна форма на весь API, и по `details.missing` видно, чего не хватает.
    """
    if error.status_code == 501:
        missing = tuple((error.details or {}).get("missing", ()))
        return not_implemented(endpoint=endpoint, message=error.message, missing=missing)
    return error_response(error.status_code, error.code, error.message, details=error.details)


@router.get(
    "",
    response_model=ReviewIssueListResponse,
    summary="Места, которые стоит проверить",
    description=(
        "Отбор по статусу необязателен. У песни без разбора список отвечает `501`: пустой "
        "список читался бы как «все в порядке»."
    ),
    responses=errors(401, 403, 404, 422, 501),
)
async def list_issues(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
    status: Annotated[ReviewStatus | None, Query(description="Отбор по статусу проверки")] = None,
) -> Response | ReviewIssueListResponse:
    endpoint = "GET /api/projects/{project_id}/review-issues"
    blocked = _not_wired(endpoint, session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        bundles = await service.list_issues(repos, project, status=status)
    except projects_service.ProjectRefusal as error:
        return _refusal(endpoint, error)

    items = [service.bundle_out(bundle) for bundle in bundles]
    return ReviewIssueListResponse(items=items, total=len(items))


@router.patch(
    "/{issue_id}",
    response_model=ReviewIssueOut,
    summary="Сменить статус места",
    description=(
        "Пять статусов различают «исправлено» и «принято для репетиции»: во втором случае "
        "место осталось спорным, но играть договорились так."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def update_issue_status(
    project_id: ProjectIdPath,
    issue_id: IssueIdPath,
    payload: ReviewIssueStatusUpdate,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ReviewIssueOut:
    endpoint = "PATCH /api/projects/{project_id}/review-issues/{issue_id}"
    blocked = _not_wired(endpoint, session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        issue = await service.issue_of_project(repos, project, issue_id)
        bundle = await service.set_status(
            repos,
            project,
            issue,
            status=payload.status,
            comment=payload.comment,
            author=await service.signature_of(repos, project, str(user_id)),
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(endpoint, error)

    return service.bundle_out(bundle)


@router.post(
    "/{issue_id}/comments",
    response_model=ReviewCommentOut,
    status_code=201,
    summary="Свой комментарий к месту",
    description="Статус места при этом не меняется: комментарий — не проверка.",
    responses=errors(401, 403, 404, 422, 501),
)
async def add_comment(
    project_id: ProjectIdPath,
    issue_id: IssueIdPath,
    payload: ReviewCommentCreate,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ReviewCommentOut:
    endpoint = "POST /api/projects/{project_id}/review-issues/{issue_id}/comments"
    blocked = _not_wired(endpoint, session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        issue = await service.issue_of_project(repos, project, issue_id)
        comment = await service.add_comment(
            repos,
            issue,
            text=payload.text,
            requested_author=payload.author,
            signature=await service.signature_of(repos, project, str(user_id)),
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(endpoint, error)

    return service.comment_out(comment)
