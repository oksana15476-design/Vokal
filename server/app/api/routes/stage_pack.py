"""Stage Pack: материалы, разбор, места для проверки.

Три вещи возвращаются одним ответом намеренно. Материалы без разбора и без
мест для проверки читаются как проверенный результат, хотя любой автоматический
результат — черновик. Разделить их на три запроса значит разрешить экрану
показать первый и не дождаться остальных.

Скачивание идет через собственный адрес с проверкой прав. Прямая подписанная
ссылка на объект в ответ не попадает: отозвать ее нельзя, и обещание «удалить
результаты» стало бы ложным для всех, кому ссылку уже отправили.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from app.api.deps import SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.artifacts import (
    ArtifactDownloadOut,
    ArtifactListResponse,
    ArtifactOut,
    StagePackResponse,
)
from app.api.schemas.enums import ArtifactAudience, ArtifactType

router = APIRouter(prefix="/projects/{project_id}", tags=["материалы"])

ProjectIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор проекта")]
ArtifactIdPath = Annotated[
    str, Path(min_length=1, max_length=64, description="Идентификатор материала")
]

MATERIALS_MISSING = (
    "обработка звука и сборка материалов",
    "объектное хранилище результатов",
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
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/stage-pack",
        message="Материалы не собираются: обработки звука еще нет.",
        missing=MATERIALS_MISSING,
    )


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
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/artifacts",
        message="Материалов нет: обработки звука еще нет.",
        missing=MATERIALS_MISSING,
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
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/artifacts/{artifact_id}",
        message="Материалов нет: обработки звука еще нет.",
        missing=MATERIALS_MISSING,
    )


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
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/artifacts/{artifact_id}/download",
        message="Скачивать нечего: файлы результатов пока не создаются.",
        missing=MATERIALS_MISSING,
    )
