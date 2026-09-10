"""Выдача материалов: получатели, ссылки, архивы.

Половина адресов здесь работает, половина честно отказывает, и граница проходит
не по удобству, а по тому, есть ли под адресом слой данных.

**Получатели работают.** Таблица `share_recipients` заведена, поэтому список,
добавление и правка получателя ходят в базу и закрывают чужую песню.

**Ссылки и архивы отвечают `501`.** Ссылка обязана иметь срок жизни и отзыв —
это требование `docs/DELETION_AND_RETENTION_DESIGN.md`, а не удобство: без
отзыва кнопка «удалить результаты» не закрывает доступ, который уже выдан
музыкантам и ученикам, и обещание становится ложным. И срок, и отзыв — это
состояние, а хранить его негде: таблиц `share_links` и `export_bundles` в схеме
базы нет. Выдать ссылку «пока без отзыва» нельзя тем более: отзывать ее потом
будет нечем, а материалы по ней уже разойдутся.

Разбор недостающего — в `app/services/sharing.py`. Хранилище там не упомянуто
намеренно: оно есть (`app/storage/`), и списывать отсутствие выдачи на него
значит отправить работу не туда.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import (
    BundleIdPath,
    LinkIdPath,
    PageDep,
    ProjectIdPath,
    RecipientIdPath,
    SessionDep,
    UserDep,
)
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
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import projects as projects_service
from app.services import sharing as service

router = APIRouter(prefix="/projects/{project_id}", tags=["выдача"])


WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Выдача не включена: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


async def _owned(repos: Repositories, project_id: str, user_id: str | None):
    return await projects_service.owned_project(
        repos, projects_service.entity_id(project_id), str(user_id)
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
) -> Response | ShareRecipientListResponse:
    blocked = _not_wired("GET /api/projects/{project_id}/recipients", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await _owned(repos, project_id, user_id)
        return await service.list_recipients(repos, project, limit=page.limit, offset=page.offset)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)


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
) -> Response | ShareRecipientOut:
    blocked = _not_wired("POST /api/projects/{project_id}/recipients", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await _owned(repos, project_id, user_id)
        created = await service.create_recipient(repos, project, payload)
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.recipient_out(created)


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
) -> Response | ShareRecipientOut:
    blocked = _not_wired(
        "PATCH /api/projects/{project_id}/recipients/{recipient_id}", session, user_id
    )
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await _owned(repos, project_id, user_id)
        updated = await service.update_recipient(
            repos, project, projects_service.entity_id(recipient_id), payload
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return service.recipient_out(updated)


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
        message="Ссылок нет: выдавать их пока нечем — хранить срок жизни и отзыв негде.",
        missing=service.LINKS_MISSING,
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
    # Отказ, а не ссылка «пока без отзыва». Выданное однажды нельзя догнать:
    # материалы разойдутся, а отзывать их будет нечем.
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/share-links",
        message=(
            "Ссылку выдать нельзя: у нее не может быть ни срока жизни, ни отзыва — "
            "хранить их негде."
        ),
        missing=service.LINKS_MISSING,
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
        message="Отзывать нечего: ссылки не выдаются, потому что хранить их негде.",
        missing=service.LINKS_MISSING,
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
        message="Архивов нет: собирать их не из чего и хранить негде.",
        missing=service.BUNDLES_MISSING,
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
        message="Собирать нечего: файлов материалов пока не создается.",
        missing=service.BUNDLES_MISSING,
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
        message="Архивов нет: собирать их не из чего и хранить негде.",
        missing=service.BUNDLES_MISSING,
    )
