"""Stage Pack: материалы, разбор, места для проверки.

Три вещи возвращаются одним ответом намеренно. Материалы без разбора и без
мест для проверки читаются как проверенный результат, хотя любой автоматический
результат — черновик. Разделить их на три запроса значит разрешить экрану
показать первый и не дождаться остальных.

Скачивание идет через собственный адрес с проверкой прав. Прямая подписанная
ссылка на объект в ответ не попадает: отозвать ее нельзя, и обещание «удалить
результаты» стало бы ложным для всех, кому ссылку уже отправили.

Что здесь работает по-настоящему: сам Stage Pack, список материалов и карточка
одного материала. Разбор при этом отдается таким, какой есть: у демо он
подготовлен заранее (`analysisSource = demo`), у загруженного файла его нет
вовсе (`analysisSource = none`) — и это пустой разбор, а не разбор чужой песни.

Что осталось `501` и почему — сказано у самого адреса выдачи файла.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

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
from app.db import enums, models
from app.db.repositories import Repositories
from app.services import jobs as jobs_service
from app.services import projects as service

router = APIRouter(prefix="/projects/{project_id}", tags=["материалы"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)

DOWNLOAD_MISSING = (
    "сборка материалов: файлов результатов пока не создается",
    "адрес выдачи файла с проверкой прав и коротким сроком жизни ссылки",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Материалы не отдаются: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


async def _pack_version(
    repos: Repositories, project: models.Project, version_id: str | None
) -> uuid.UUID:
    """Версия, чьи материалы показываем.

    Явно названная версия проверяется на принадлежность песне: иначе по
    идентификатору чужой версии можно было бы вытащить чужие материалы.
    """
    versions = await repos.versions.list_for_project(project.id)
    if not versions:
        raise service.ProjectRefusal(
            409,
            "no_version_yet",
            "У песни еще нет версии аранжировки: показывать нечего.",
        )
    if version_id is None:
        return project.current_version_id or versions[-1].id

    wanted = service.entity_id(version_id)
    if wanted not in {version.id for version in versions}:
        raise service.ProjectRefusal(404, "not_found", "Версия не найдена.")
    return wanted


async def _refuse_while_processing(repos: Repositories, project: models.Project) -> None:
    """Пока обработка идет, Stage Pack не отдается.

    Показать половину собранного пакета хуже, чем не показать ничего:
    музыкант унесет на репетицию то, что через минуту пересоберут.
    """
    job = await jobs_service.latest_job(repos, project.id)
    if job is not None and job.status in jobs_service.LIVE_STATUSES:
        raise service.ProjectRefusal(
            409,
            "processing_in_progress",
            "Обработка еще идет. Материалы будут готовы, когда задание завершится.",
            details={"jobId": str(job.id), "status": job.status.value},
        )


@router.get(
    "/stage-pack",
    response_model=StagePackResponse,
    summary="Stage Pack целиком",
    description="Материалы текущей версии, разбор песни и места, которые стоит проверить.",
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
        project = await service.owned_project(repos, service.entity_id(project_id), str(user_id))
        await _refuse_while_processing(repos, project)
        version = await _pack_version(repos, project, version_id)

        artifacts = await repos.artifacts.list_for_version(version)
        upload = await service.source_upload(repos, project)
        issues = await repos.review_issues.list_for_project(project.id)
        comments: list[models.ReviewComment] = []
        for issue in issues:
            comments.extend(await repos.review_comments.list_for_issue(issue.id))

        job = await jobs_service.latest_job(repos, project.id)
        warnings = list(job.warnings or []) if job is not None else []
        if project.results_deletion_state is not enums.DeletionState.PRESENT:
            # Материалы удалены. Молчать об этом нельзя: пустой пакет иначе
            # читается как «обработка ничего не дала».
            warnings.insert(0, "Результаты этой песни удалены и не восстанавливаются.")

        return StagePackResponse(
            stage_pack=service.stage_pack_out(version, artifacts),
            analysis=service.analysis_out(project, upload),
            review_issues=[service.review_issue_out(issue, comments) for issue in issues],
            warnings=warnings,
        )
    except service.ProjectRefusal as error:
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
        project = await service.owned_project(repos, service.entity_id(project_id), str(user_id))
        artifacts = await repos.artifacts.list_for_project(project.id)
    except service.ProjectRefusal as error:
        return _refusal(error)

    selected = [
        artifact
        for artifact in artifacts
        if (artifact_type is None or artifact.artifact_type.value == artifact_type.value)
        and (audience is None or artifact.audience.value == audience.value)
    ]
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
        project = await service.owned_project(repos, service.entity_id(project_id), str(user_id))
        artifact = await repos.artifacts.get(service.entity_id(artifact_id))
        if artifact is None or artifact.project_id != project.id:
            # Материал чужой песни отвечает «не найден», а не «закрыт»:
            # адрес вложен в песню, и подтверждать существование чужой
            # строки по чужому идентификатору незачем.
            raise service.ProjectRefusal(404, "not_found", "Материал не найден.")
    except service.ProjectRefusal as error:
        return _refusal(error)

    return service.artifact_out(artifact)


@router.get(
    "/artifacts/{artifact_id}/download",
    response_model=ArtifactDownloadOut,
    summary="Ссылка на скачивание материала",
    description=(
        "Ссылка ведет на наш адрес и живет минуты, а не дни. Прямая подписанная ссылка "
        "на объект хранилища клиенту не отдается: ее нельзя отозвать."
    ),
    responses=errors(401, 403, 404, 410, 501),
)
async def download_artifact(
    project_id: ProjectIdPath,
    artifact_id: ArtifactIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    # Здесь `501` стоит по существу, а не из-за незаведенных швов. Файлов
    # результатов не создается вовсе: обработки звука нет, у материалов пуст
    # `storage_key`. Выдать ссылку значило бы пообещать файл, которого нет, —
    # и обещание сломалось бы на первом же переходе по ней.
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/artifacts/{artifact_id}/download",
        message="Скачивать нечего: файлы результатов пока не создаются.",
        missing=DOWNLOAD_MISSING,
    )
