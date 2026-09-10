"""Обработка: запуск, статус, повтор.

Статус читается поллингом адреса задания. Сервер сам говорит, через сколько
спрашивать снова (`pollAfterMs`), — интервал не должен быть случайной
константой в интерфейсе.

Запуск обработки принимает `Idempotency-Key`, потому что повторный запуск —
это повторное списание стоимости, а не безобидный дубль.

Логика живет в `app/services/jobs.py`, роутер переводит ее отказы в коды HTTP.
Правило, ради которого все это написано, одно: шаг без подключенной реализации
получает статус `skipped` и в прогресс не попадает. Сегодня таких шагов все
восемь, поэтому задание честно сообщает «выполнять нечего» предупреждением, а
не рисует зеленые вехи за несделанную работу.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Response

from app.api.deps import JobIdPath, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.jobs import JobCreateRequest, JobRetryRequest, ProcessingJobOut
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import jobs as service
from app.services import projects as projects_service

router = APIRouter(tags=["обработка"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Обработка не включена: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


@router.post(
    "/projects/{project_id}/jobs",
    response_model=ProcessingJobOut,
    status_code=202,
    summary="Запустить обработку",
    description=(
        "Отвечает `202`: задание принято в очередь. Готовность спрашивается у адреса задания."
    ),
    responses=errors(401, 403, 404, 409, 422, 429, 501),
)
async def start_job(
    project_id: ProjectIdPath,
    payload: JobCreateRequest,
    session: SessionDep,
    user_id: UserDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Ключ повтора. Повторный запрос с тем же ключом возвращает то же задание "
                "и не списывает стоимость дважды."
            ),
        ),
    ] = None,
) -> Response | ProcessingJobOut:
    blocked = _not_wired("POST /api/projects/{project_id}/jobs", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        upload = await projects_service.source_upload(repos, project)
        job, steps = await service.start_job(
            repos,
            project=project,
            upload=upload,
            goal_id=payload.goal_id,
            force_restart=payload.force_restart,
            idempotency_key=idempotency_key,
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.job_out(job, steps)


@router.get(
    "/jobs/{job_id}",
    response_model=ProcessingJobOut,
    summary="Статус задания",
    description=(
        "Шаги со статусами и прогресс. Шаг со статусом `skipped` не будет выполнен вовсе — "
        "это отличается от «сделан» и показывается пользователю отдельно."
    ),
    responses=errors(401, 403, 404, 501),
)
async def read_job(
    job_id: JobIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ProcessingJobOut:
    blocked = _not_wired("GET /api/jobs/{job_id}", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        job = await service.owned_job(repos, job_id, str(user_id))
        steps = await service.steps_of(repos, job)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.job_out(job, steps)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=ProcessingJobOut,
    status_code=202,
    summary="Повторить упавшее задание",
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def retry_job(
    job_id: JobIdPath,
    payload: JobRetryRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ProcessingJobOut:
    blocked = _not_wired("POST /api/jobs/{job_id}/retry", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        job = await service.owned_job(repos, job_id, str(user_id))
        job, steps = await service.retry_job(
            repos,
            job=job,
            steps=await service.steps_of(repos, job),
            from_step_id=payload.from_step_id,
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.job_out(job, steps)
