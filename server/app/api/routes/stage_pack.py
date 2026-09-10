"""Stage Pack: материалы, разбор, места для проверки.

Три вещи возвращаются одним ответом намеренно. Материалы без разбора и без
мест для проверки читаются как проверенный результат, хотя любой автоматический
результат — черновик. Разделить их на три запроса значит разрешить экрану
показать первый и не дождаться остальных.

Скачивание идет через собственный адрес с проверкой прав. Прямая подписанная
ссылка на объект в ответ не попадает никогда — даже когда хранилище ее умеет:
отозвать ее нельзя, и обещание «удалить результаты» стало бы ложным для всех,
кому ссылку уже отправили.

Адрес выдачи файла один и отвечает двумя разными вещами: без параметров —
описанием (куда идти, как будет называться файл), с `content=true` — самим
файлом. Второго адреса не заведено намеренно: он был бы новым путем в
контракте, а контракт фронтенда уже описывает выдачу описанием со ссылкой.

Что здесь работает по-настоящему: Stage Pack, список материалов, карточка
материала и выдача файла. Разбор при этом отдается таким, какой есть: у демо он
подготовлен заранее (`analysisSource = demo`), у загруженного файла его нет
вовсе (`analysisSource = none`) — и это пустой разбор, а не разбор чужой песни.

Логика живет в `app/services/stage_pack.py`, роутер переводит ее отказы в коды
HTTP.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.deps import ArtifactIdPath, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.artifacts import (
    ArtifactDownloadOut,
    ArtifactListResponse,
    ArtifactOut,
    StagePackResponse,
)
from app.api.schemas.enums import ArtifactAudience, ArtifactType
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import projects as projects_service
from app.services import stage_pack as service
from app.storage import ObjectStorage

router = APIRouter(prefix="/projects/{project_id}", tags=["материалы"])


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
            message="Материалы не отдаются: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _no_storage(endpoint: str, storage: Any) -> Response | None:
    if storage is None:
        return not_implemented(
            endpoint=endpoint,
            message="Файл не отдается: хранилище настроено неверно.",
            missing=STORAGE_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


@router.get(
    "/stage-pack",
    response_model=StagePackResponse,
    summary="Stage Pack целиком",
    description=(
        "Материалы текущей версии, разбор песни и места, которые стоит проверить. "
        "Материал без собранного файла готовым не показывается, а `warnings` называет, "
        "чего именно в пакете не хватает."
    ),
    responses=errors(401, 403, 404, 409, 501),
)
async def read_stage_pack(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
    version_id: Annotated[
        str | None,
        Query(description="Версия аранжировки. Пусто — текущая версия проекта."),
    ] = None,
) -> Response | StagePackResponse:
    blocked = _not_wired("GET /api/projects/{project_id}/stage-pack", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        return await service.read_pack(repos, project, version_id)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)


@router.get(
    "/artifacts",
    response_model=ArtifactListResponse,
    summary="Список материалов",
    responses=errors(401, 403, 404, 422, 501),
)
async def list_artifacts(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
    artifact_type: Annotated[
        ArtifactType | None, Query(alias="type", description="Отбор по типу материала")
    ] = None,
    audience: Annotated[
        ArtifactAudience | None, Query(description="Отбор по тому, кому материал предназначен")
    ] = None,
) -> Response | ArtifactListResponse:
    blocked = _not_wired("GET /api/projects/{project_id}/artifacts", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        artifacts = await repos.artifacts.list_for_project(project.id)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    selected = service.filter_artifacts(
        artifacts,
        artifact_type=artifact_type.value if artifact_type else None,
        audience=audience.value if audience else None,
    )
    return ArtifactListResponse(
        items=[service.artifact_out(artifact) for artifact in selected], total=len(selected)
    )


@router.get(
    "/artifacts/{artifact_id}",
    response_model=ArtifactOut,
    summary="Один материал",
    responses=errors(401, 403, 404, 501),
)
async def read_artifact(
    project_id: ProjectIdPath,
    artifact_id: ArtifactIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ArtifactOut:
    blocked = _not_wired("GET /api/projects/{project_id}/artifacts/{artifact_id}", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        artifact = await service.owned_artifact(repos, project, artifact_id)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.artifact_out(artifact)


@router.get(
    "/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadOut,
    summary="Файл материала",
    description=(
        "Без параметров отвечает описанием: наш адрес, по которому придет файл, и как "
        "файл будет называться. С `content=true` отдает сам файл. Прямая подписанная "
        "ссылка на объект хранилища клиенту не отдается никогда: ее нельзя отозвать."
    ),
    responses=errors(401, 403, 404, 409, 410, 501),
)
async def download_artifact(
    project_id: ProjectIdPath,
    artifact_id: ArtifactIdPath,
    request: Request,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
    content: Annotated[
        bool,
        Query(description="Отдать сам файл, а не описание выдачи."),
    ] = False,
) -> Response | ArtifactDownloadOut:
    endpoint = "GET /api/projects/{project_id}/artifacts/{artifact_id}/download"
    blocked = _not_wired(endpoint, session, user_id) or _no_storage(endpoint, storage)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        # Удаленные результаты проверяются до поиска материала: иначе ответом
        # было бы «не найдено», и пользователь пошел бы искать ошибку в ссылке
        # вместо того, что произошло на самом деле.
        service.refuse_if_results_deleted(project)
        artifact = await service.owned_artifact(repos, project, artifact_id)

        if not content:
            service.require_file(artifact)
            # Адрес строится по имени обработчика, а не из текущего запроса:
            # иначе в выданную ссылку уехали бы случайные параметры клиента.
            target = request.url_for(
                "download_artifact", project_id=project_id, artifact_id=artifact_id
            )
            return service.download_out(
                artifact, url=str(target.include_query_params(content="true"))
            )

        data = await service.artifact_file(artifact, storage=storage)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return Response(
        content=data,
        media_type=service.media_type_for(artifact),
        headers={"Content-Disposition": service.content_disposition(artifact)},
    )
