"""Удаление исходника и результатов.

Два раздельных адреса и никакого общего «удалить» с параметром: у операций
разный смысл и разные последствия, и слитый адрес однажды выполнит не ту.

Ответ на запуск — `202`. Код означает «задача принята», а не «уже удалено»:
что именно с ней стало, сказано полем `state`. Пока хранилище не подтвердило
удаление, там стоит `purge_requested`, и интерфейс показывает «удаление
выполняется». Здесь удаление выполняется тем же запросом и подтверждается им
же, поэтому в обычном случае в ответе уже `purged` — но это факт, а не
умолчание: состояние ставится только после проверки, что объекта в хранилище
не стало (`app/services/deletion.py`).

Обе операции необратимы и идемпотентны: повторный запуск на уже удаленном
проекте завершается успехом, не ходит в хранилище второй раз и называет тот же
момент удаления, что и первый.

Где остается `501`: сессия базы и вход в аккаунт — заглушки в
`app/api/deps.py`. Без них нельзя ни найти, что удалять, ни проверить, чье оно.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.deletion import DeletionAcceptedOut, DeletionRequest, DeletionStatusOut
from app.core.errors import error_response
from app.db.repositories import DeletionScope, Repositories
from app.services import deletion as service
from app.services import projects as projects_service
from app.storage import ObjectStorage

router = APIRouter(prefix="/projects/{project_id}", tags=["удаление"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)

STORAGE_MISSING = ("настройки хранилища (VOKAL_STORAGE_BACKEND, app/storage/config.py)",)


def object_storage() -> ObjectStorage | None:
    """Хранилище процесса. `None` — настройки заданы неверно.

    Копия провайдера из `app/api/routes/uploads.py`: общее место для него —
    `app/api/deps.py`, но зона этого батча туда не заходит. Отказ конструктора
    не превращается в `500`: неверная переменная окружения — это незаконченная
    настройка сервиса, а не поломка запроса.
    """
    try:
        from app.storage import get_storage

        return get_storage()
    except Exception:
        # Причина уходит списком «чего не хватает», а не текстом наружу:
        # сообщения исключений регулярно содержат куски конфигурации.
        return None


StorageDep = Annotated[ObjectStorage | None, Depends(object_storage)]


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Удаление не включено: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _no_storage(endpoint: str, storage: Any) -> Response | None:
    """Без хранилища удалять нельзя.

    Не из осторожности: подтвердить, что объекта не стало, можно только у
    хранилища, а неподтвержденное удаление показывать удаленным запрещено.
    """
    if storage is None:
        return not_implemented(
            endpoint=endpoint,
            message="Удаление не включено: хранилище настроено неверно.",
            missing=STORAGE_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


def _status_url(request: Request, project_id: str) -> str:
    return str(request.url_for("deletion_status", project_id=project_id))


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
    responses=errors(401, 403, 404, 422, 501, 503),
)
async def delete_source(
    project_id: ProjectIdPath,
    payload: DeletionRequest,
    request: Request,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | DeletionAcceptedOut:
    endpoint = "POST /api/projects/{project_id}/delete-source"
    blocked = _not_wired(endpoint, session, user_id) or _no_storage(endpoint, storage)
    if blocked is not None:
        return blocked

    # `payload.confirm` уже проверен схемой: без подтверждения запрос не
    # доходит сюда вовсе (`app/api/schemas/deletion.py`).
    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        deleted = await service.delete_source(repos, project, storage=storage)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.accepted_out(
        deleted, scope=DeletionScope.SOURCE, status_url=_status_url(request, project_id)
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
    responses=errors(401, 403, 404, 422, 501, 503),
)
async def delete_results(
    project_id: ProjectIdPath,
    payload: DeletionRequest,
    request: Request,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | DeletionAcceptedOut:
    endpoint = "POST /api/projects/{project_id}/delete-results"
    blocked = _not_wired(endpoint, session, user_id) or _no_storage(endpoint, storage)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        deleted = await service.delete_results(repos, project, storage=storage)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.accepted_out(
        deleted,
        scope=DeletionScope.RESULTS,
        status_url=_status_url(request, project_id),
        # Ноль здесь — факт, а не заглушка: выдать ссылку сейчас невозможно
        # вовсе (`app/api/routes/sharing.py` отказывает), значит и гасить
        # нечего. Когда ссылки появятся, число станет их количеством.
        revoked_links_count=0,
    )


@router.get(
    "/deletion-status",
    response_model=DeletionStatusOut,
    summary="Состояние удаления",
    description=(
        "Статус обеих операций. Пока хранилище не подтвердило удаление, состояние "
        "остается `purge_requested`, и интерфейс показывает «удаление выполняется». "
        "Просроченный срок удаления виден полем `error`: неисполненное обещание "
        "удаления — инцидент, а не строка в логе."
    ),
    responses=errors(401, 403, 404, 501),
)
async def deletion_status(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response | DeletionStatusOut:
    blocked = _not_wired("GET /api/projects/{project_id}/deletion-status", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.status_out(project)
