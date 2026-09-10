"""Удаление исходника и результатов.

Два раздельных адреса и никакого общего «удалить» с параметром: у операций
разный смысл и разные последствия, и слитый адрес однажды выполнит не ту.

Ответ на запуск — `202`, а не `200`. Пока объектное хранилище не подтвердило
удаление, «удалено» показывать нельзя: правильное состояние в этот момент —
«удаление выполняется». Статус спрашивается отдельным адресом.

Обе операции необратимы и идемпотентны: повторный запуск на уже удаленном
проекте завершается успехом, а не ошибкой.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.deletion import DeletionAcceptedOut, DeletionRequest, DeletionStatusOut

router = APIRouter(prefix="/projects/{project_id}", tags=["удаление"])


DELETION_MISSING = (
    "объектное хранилище: удалять пока нечего и нечем",
    "фоновая задача удаления с подтверждением от хранилища",
    "аудит-лог факта удаления",
)


@router.post(
    "/delete-source",
    response_model=DeletionAcceptedOut,
    status_code=202,
    summary="Удалить исходник",
    description=(
        "Удаляются исходный файл, нормализованная копия, превью и копии у внешних "
        "провайдеров обработки. Сохраняются метаданные проекта, разбор песни, "
        "результаты обработки, аудит-лог и события биллинга. "
        "Разбор остается, и по нему можно восстановить содержание произведения — "
        "об этом пользователю говорится дословно."
    ),
    responses=errors(401, 403, 404, 422, 501),
)
async def delete_source(
    project_id: ProjectIdPath,
    payload: DeletionRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/delete-source",
        message="Удалять нечего: файлы на сервере пока не хранятся.",
        missing=DELETION_MISSING,
    )


@router.post(
    "/delete-results",
    response_model=DeletionAcceptedOut,
    status_code=202,
    summary="Удалить результаты",
    description=(
        "Удаляются все материалы и их версии, кэш превью, копии у провайдеров. "
        "Все выданные ссылки на материалы проекта немедленно перестают работать. "
        "Сохраняются метаданные проекта, история версий как перечень изменений без "
        "файлов, аудит-лог и события биллинга."
    ),
    responses=errors(401, 403, 404, 422, 501),
)
async def delete_results(
    project_id: ProjectIdPath,
    payload: DeletionRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/delete-results",
        message="Удалять нечего: результаты на сервере пока не хранятся.",
        missing=DELETION_MISSING,
    )


@router.get(
    "/deletion-status",
    response_model=DeletionStatusOut,
    summary="Состояние удаления",
    description=(
        "Статус обеих операций. Пока хранилище не подтвердило удаление, состояние "
        "остается `purge_requested`, и интерфейс показывает «удаление выполняется»."
    ),
    responses=errors(401, 403, 404, 501),
)
async def deletion_status(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/deletion-status",
        message="Состояния удаления нет: файлы на сервере пока не хранятся.",
        missing=DELETION_MISSING,
    )
