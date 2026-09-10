"""Обработка: запуск, статус, повтор.

Статус читается поллингом адреса задания. Сервер сам говорит, через сколько
спрашивать снова (`pollAfterMs`), — интервал не должен быть случайной
константой в интерфейсе.

Запуск обработки принимает `Idempotency-Key`, потому что повторный запуск —
это повторное списание стоимости, а не безобидный дубль.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Response

from app.api.deps import JobIdPath, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.jobs import JobCreateRequest, JobRetryRequest, ProcessingJobOut

router = APIRouter(tags=["обработка"])


PIPELINE_MISSING = (
    "очередь заданий и обработчики",
    "разделение слоев, транскрипция, сборка материалов",
)


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
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/jobs",
        message="Обработка звука не запускается: обработчиков еще нет.",
        missing=PIPELINE_MISSING,
    )


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
) -> Response:
    return not_implemented(
        endpoint="GET /api/jobs/{job_id}",
        message="Заданий обработки пока не существует.",
        missing=PIPELINE_MISSING,
    )


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
) -> Response:
    return not_implemented(
        endpoint="POST /api/jobs/{job_id}/retry",
        message="Повторять нечего: обработка не запускается.",
        missing=PIPELINE_MISSING,
    )
