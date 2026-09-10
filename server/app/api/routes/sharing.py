"""Выдача материалов: получатели, ссылки, архивы.

Ссылка ведет на наш адрес и отзывается. Это требование
`docs/DELETION_AND_RETENTION_DESIGN.md`, а не удобство: без отзыва кнопка
«удалить результаты» не закрывает доступ, который уже выдан музыкантам и
ученикам, и обещание становится ложным.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import PageDep, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.sharing import (
    ExportBundleCreate,
    ExportBundleListResponse,
    ExportBundleOut,
    ShareLinkCreate,
    ShareLinkListResponse,
    ShareLinkOut,
    ShareRecipientCreate,
    ShareRecipientListResponse,
    ShareRecipientOut,
    ShareRecipientUpdate,
)

router = APIRouter(prefix="/projects/{project_id}", tags=["выдача"])

ProjectIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор проекта")]
RecipientIdPath = Annotated[
    str, Path(min_length=1, max_length=64, description="Идентификатор получателя")
]
LinkIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор ссылки")]
BundleIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор архива")]

SHARING_MISSING = (
    "выдача ссылок с отзываемым токеном",
    "объектное хранилище результатов",
)


@router.get(
    "/recipients",
    response_model=ShareRecipientListResponse,
    summary="Получатели материалов",
    responses=errors(401, 403, 404, 501),
)
async def list_recipients(
    project_id: ProjectIdPath,
    page: PageDep,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/recipients",
        message="Получателей нет: проекты пока не сохраняются на сервере.",
        missing=SHARING_MISSING,
    )


@router.post(
    "/recipients",
    response_model=ShareRecipientOut,
    status_code=201,
    summary="Добавить получателя",
    description="Разным ролям выдается разное: у преподавателя и ученика материалы не совпадают.",
    responses=errors(401, 403, 404, 422, 501),
)
async def create_recipient(
    project_id: ProjectIdPath,
    payload: ShareRecipientCreate,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/recipients",
        message="Добавлять получателя некуда: проекты пока не сохраняются на сервере.",
        missing=SHARING_MISSING,
    )


@router.patch(
    "/recipients/{recipient_id}",
    response_model=ShareRecipientOut,
    summary="Изменить получателя",
    responses=errors(401, 403, 404, 422, 501),
)
async def update_recipient(
    project_id: ProjectIdPath,
    recipient_id: RecipientIdPath,
    payload: ShareRecipientUpdate,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="PATCH /api/projects/{project_id}/recipients/{recipient_id}",
        message="Менять некого: получателей на сервере пока нет.",
        missing=SHARING_MISSING,
    )


@router.get(
    "/share-links",
    response_model=ShareLinkListResponse,
    summary="Выданные ссылки",
    responses=errors(401, 403, 404, 501),
)
async def list_share_links(
    project_id: ProjectIdPath,
    page: PageDep,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/share-links",
        message="Ссылок нет: выдача материалов пока не работает.",
        missing=SHARING_MISSING,
    )


@router.post(
    "/share-links",
    response_model=ShareLinkOut,
    status_code=201,
    summary="Выдать ссылку получателю",
    description=(
        "Ссылка ведет на наш адрес и содержит отзываемый токен. Подписанная ссылка на "
        "объект хранилища наружу не выдается: ее нельзя отозвать."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def create_share_link(
    project_id: ProjectIdPath,
    payload: ShareLinkCreate,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/share-links",
        message="Выдавать нечего: материалов и хранилища для них пока нет.",
        missing=SHARING_MISSING,
    )


@router.delete(
    "/share-links/{link_id}",
    status_code=204,
    summary="Отозвать ссылку",
    description="Идемпотентно: повторный отзыв уже отозванной ссылки завершается успехом.",
    responses=errors(401, 403, 404, 501),
)
async def revoke_share_link(
    project_id: ProjectIdPath,
    link_id: LinkIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="DELETE /api/projects/{project_id}/share-links/{link_id}",
        message="Отзывать нечего: ссылки пока не выдаются.",
        missing=SHARING_MISSING,
    )


@router.get(
    "/export-bundles",
    response_model=ExportBundleListResponse,
    summary="Архивы материалов",
    responses=errors(401, 403, 404, 501),
)
async def list_export_bundles(
    project_id: ProjectIdPath,
    page: PageDep,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/export-bundles",
        message="Архивов нет: материалы пока не собираются.",
        missing=SHARING_MISSING,
    )


@router.post(
    "/export-bundles",
    response_model=ExportBundleOut,
    status_code=202,
    summary="Собрать архив материалов",
    description="Отвечает `202`: сборка идет заданием, готовность видна по статусу архива.",
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def create_export_bundle(
    project_id: ProjectIdPath,
    payload: ExportBundleCreate,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/export-bundles",
        message="Собирать нечего: материалы пока не создаются.",
        missing=SHARING_MISSING,
    )


@router.get(
    "/export-bundles/{bundle_id}",
    response_model=ExportBundleOut,
    summary="Состояние архива",
    responses=errors(401, 403, 404, 501),
)
async def read_export_bundle(
    project_id: ProjectIdPath,
    bundle_id: BundleIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/export-bundles/{bundle_id}",
        message="Архивов нет: материалы пока не собираются.",
        missing=SHARING_MISSING,
    )
