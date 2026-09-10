"""Проверка: статусы мест и комментарии.

Статус меняет человек, а не система: смысл слоя проверки в том, что
автоматический результат считается черновиком, пока музыкант не сказал иначе.
Поэтому сервер не переводит место в «проверено» сам ни при каких условиях.
"""

from __future__ import annotations

from typing import Annotated

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

router = APIRouter(prefix="/projects/{project_id}/review-issues", tags=["проверка"])


REVIEW_MISSING = (
    "Confidence and Review Engine: места проверки строятся по разбору",
    "слой данных проекта (батч БД)",
)


@router.get(
    "",
    response_model=ReviewIssueListResponse,
    summary="Места, которые стоит проверить",
    responses=errors(401, 403, 404, 422, 501),
)
async def list_issues(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
    status: Annotated[ReviewStatus | None, Query(description="Отбор по статусу проверки")] = None,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/review-issues",
        message="Мест для проверки нет: разбора песни еще нет.",
        missing=REVIEW_MISSING,
    )


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
) -> Response:
    return not_implemented(
        endpoint="PATCH /api/projects/{project_id}/review-issues/{issue_id}",
        message="Менять нечего: мест для проверки на сервере пока нет.",
        missing=REVIEW_MISSING,
    )


@router.post(
    "/{issue_id}/comments",
    response_model=ReviewCommentOut,
    status_code=201,
    summary="Свой комментарий к месту",
    responses=errors(401, 403, 404, 422, 501),
)
async def add_comment(
    project_id: ProjectIdPath,
    issue_id: IssueIdPath,
    payload: ReviewCommentCreate,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/review-issues/{issue_id}/comments",
        message="Комментировать нечего: мест для проверки на сервере пока нет.",
        missing=REVIEW_MISSING,
    )
