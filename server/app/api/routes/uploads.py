"""Загрузка исходника.

Что здесь работает по-настоящему: ограничения приема, заявка на загрузку,
прием тела файла, чтение фактов о записи, оценка качества, подтверждение и
состояние загрузки. Логика живет в `app/services/uploads.py`, роутер только
переводит ее отказы в коды HTTP.

Файл идет **через приложение**, а не мимо него по подписанной ссылке: развилка
закрыта в `app/storage/base.py`. Поэтому у загрузки два шага и свой адрес для
тела файла — `PUT /api/uploads/{upload_id}/content`. Клиент фронтенда к этому
готов: он отправляет файл туда, куда сказано в `UploadTarget`, и не знает, наш
это адрес или чужой.

Где остается `501` и почему — три разных случая, и каждый называет себя:

1. **Единица работы и авторизация.** Зависимости в `app/api/deps.py` пока
   заглушки (сессия `None`, пользователь `None`). Без них нельзя ни записать
   строку, ни проверить, что проект принадлежит тому, кто просит.
2. **Хранилище не настроено.** Реализация есть (`app/storage`), но если
   настройки заданы неверно, писать чужую фонограмму «куда-нибудь» нельзя.
3. **Загрузка без проекта.** Строка `uploads` требует `project_id`
   (`app/db/models.py`), а создание проекта требует принятой загрузки
   (`ProjectCreateRequest.upload_id`). Круг замкнут в волне 1; расшить его —
   решение владельца, а не молчаливая правка схемы соседнего батча. Пока
   загрузка работает для существующего проекта, а без `projectId` адрес
   честно отвечает `501` и называет обе стороны круга.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import SessionDep, UploadIdPath, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.uploads import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_UPLOAD_EXTENSIONS,
    UploadCompleteRequest,
    UploadConstraints,
    UploadCreateRequest,
    UploadCreateResponse,
    UploadOut,
    UploadTarget,
)
from app.core.errors import error_response
from app.db import models
from app.db.repositories import Repositories
from app.services import uploads as service
from app.storage import ObjectStorage

router = APIRouter(prefix="/uploads", tags=["загрузка"])

#: Тело файла принимается без разбора типа содержимого: формат проверяется по
#: расширению еще на заявке, а браузеры сообщают MIME вразнобой.
CONTENT_MEDIA_TYPE = "application/octet-stream"

WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)

PROJECT_MISSING = (
    "проект для загрузки: uploads.project_id обязателен (app/db/models.py)",
    "обратная связь контракта: ProjectCreateRequest.upload_id тоже обязателен",
    "решение владельца, какую из двух сторон круга расшивать",
)


def object_storage() -> ObjectStorage | None:
    """Хранилище процесса. `None` — настройки заданы неверно.

    Отказ конструктора не превращается в `500`: неверная переменная окружения
    это не поломка запроса, а незаконченная настройка сервиса, и сказать об
    этом надо прямо.
    """
    try:
        from app.storage import get_storage

        return get_storage()
    except Exception:
        # Причина уходит в 501 списком «чего не хватает», а не текстом наружу:
        # сообщения исключений регулярно содержат куски конфигурации.
        return None


StorageDep = Annotated[ObjectStorage | None, Depends(object_storage)]


def _not_wired(endpoint: str, session: Any, user_id: str | None, storage: Any) -> Response | None:
    """Швы, без которых загрузка не может работать честно."""
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Прием файлов не включен: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    if storage is None:
        return not_implemented(
            endpoint=endpoint,
            message="Прием файлов не включен: хранилище настроено неверно.",
            missing=("настройки хранилища (VOKAL_STORAGE_BACKEND, app/storage/config.py)",),
        )
    return None


def _refusal(error: service.UploadRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


def _entity_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        # Идентификаторы в контракте — непрозрачные строки, поэтому чужая форма
        # это «не найдено», а не «неверный запрос»: клиент не обязан знать,
        # что внутри UUID.
        raise service.UploadRefusal(404, "not_found", "Объект не найден.") from error


async def _owned_project(
    repos: Repositories, project_id: uuid.UUID, user_id: str
) -> models.Project:
    project = await repos.projects.get(project_id)
    if project is None:
        raise service.UploadRefusal(404, "not_found", "Песня не найдена или удалена.")
    if str(project.user_id) != str(user_id):
        raise service.UploadRefusal(403, "forbidden", "Доступ к этой песне закрыт.")
    return project


async def _owned_upload(repos: Repositories, upload_id: uuid.UUID, user_id: str) -> models.Upload:
    # Удаленные строки читаются намеренно: отклоненная и удаленная загрузки
    # обязаны отвечать своим состоянием, а не `404`. «Не найдено» на месте
    # «исходник удален» заставило бы клиент гадать, что произошло.
    upload = await repos.uploads.get(upload_id, include_deleted=True)
    if upload is None:
        raise service.UploadRefusal(404, "not_found", "Загрузка не найдена.")
    await _owned_project(repos, upload.project_id, user_id)
    return upload


def _target_for(request: Request, upload: models.Upload) -> UploadTarget:
    return UploadTarget(
        method="PUT",
        url=str(request.url_for("put_upload_content", upload_id=str(upload.id))),
        headers={"Content-Type": CONTENT_MEDIA_TYPE},
        expires_at=service.slot_expires_at(upload),
    )


@router.get(
    "/constraints",
    response_model=UploadConstraints,
    summary="Что сервер примет",
    description=(
        "Ограничения формата и размера. Клиент обязан спросить их до выбора файла: "
        "иначе пользователь узнает о пределе, уже потратив время на отправку."
    ),
)
async def upload_constraints() -> UploadConstraints:
    return UploadConstraints(
        max_size_bytes=MAX_UPLOAD_BYTES,
        allowed_extensions=list(SUPPORTED_UPLOAD_EXTENSIONS),
        allowed_content_types=list(SUPPORTED_CONTENT_TYPES),
        max_duration_seconds=None,
        note=(
            "Проверяется расширение файла, а не MIME: браузеры сообщают тип вразнобой. "
            "Предел длительности не установлен."
        ),
    )


@router.post(
    "",
    response_model=UploadCreateResponse,
    status_code=201,
    summary="Завести загрузку и получить адрес для отправки файла",
    description=(
        "Файл в теле не передается: формат и размер проверяются здесь, до отправки. "
        "Куда отправлять файл, сказано в `target`."
    ),
    responses=errors(401, 403, 404, 409, 413, 415, 422, 501),
)
async def create_upload(
    payload: UploadCreateRequest,
    request: Request,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | UploadCreateResponse:
    blocked = _not_wired("POST /api/uploads", session, user_id, storage)
    if blocked is not None:
        return blocked
    if payload.project_id is None:
        return not_implemented(
            endpoint="POST /api/uploads",
            message=(
                "Загрузку пока некуда положить: строка загрузки требует песни, "
                "а создание песни требует принятой загрузки."
            ),
            missing=PROJECT_MISSING,
        )

    repos = Repositories(session)
    try:
        project = await _owned_project(repos, _entity_id(payload.project_id), str(user_id))
        upload = await service.create_upload(repos, project_id=project.id, request=payload)
    except service.UploadRefusal as error:
        return _refusal(error)

    return UploadCreateResponse(upload=service.to_out(upload), target=_target_for(request, upload))


@router.put(
    "/{upload_id}/content",
    response_model=UploadOut,
    summary="Отправить файл",
    description=(
        "Тело запроса — сам файл, без обертки. Сервер считает контрольную сумму и размер, "
        "кладет объект в хранилище и читает из файла длительность, частоту и каналы. "
        "Повторная отправка того же файла в ту же загрузку дубля не создает."
    ),
    responses=errors(401, 403, 404, 409, 413, 415, 422, 501, 503),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {CONTENT_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def put_upload_content(
    upload_id: UploadIdPath,
    request: Request,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | UploadOut:
    blocked = _not_wired("PUT /api/uploads/{upload_id}/content", session, user_id, storage)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        upload = await _owned_upload(repos, _entity_id(upload_id), str(user_id))
        # Тело читается только после проверки прав: чужой файл не должен даже
        # доехать до памяти процесса.
        data = await request.body()
        stored = await service.store_file(
            repos,
            upload,
            data=data,
            content_type=request.headers.get("content-type"),
            storage=storage,
        )
    except service.UploadRefusal as error:
        return _refusal(error)

    return service.to_out(stored)


@router.post(
    "/{upload_id}/complete",
    response_model=UploadOut,
    summary="Подтвердить, что файл доехал",
    description=(
        "Клиент называет размер и контрольную сумму того, что отправил, сервер сверяет их "
        "с принятым. Оборванная передача видна только здесь."
    ),
    responses=errors(401, 403, 404, 409, 422, 501, 503),
)
async def complete_upload(
    upload_id: UploadIdPath,
    payload: UploadCompleteRequest,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | UploadOut:
    blocked = _not_wired("POST /api/uploads/{upload_id}/complete", session, user_id, storage)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        upload = await _owned_upload(repos, _entity_id(upload_id), str(user_id))
        confirmed = await service.complete_upload(repos, upload, payload, storage=storage)
    except service.UploadRefusal as error:
        return _refusal(error)

    return service.to_out(confirmed)


@router.get(
    "/{upload_id}",
    response_model=UploadOut,
    summary="Состояние загрузки",
    description=(
        "Состояния: `awaiting_file` — заявка есть, файла нет; `stored` — файл принят; "
        "`rejected` — сервер отказался его принять; `purged` — исходник удален."
    ),
    responses=errors(401, 403, 404, 501),
)
async def read_upload(
    upload_id: UploadIdPath,
    session: SessionDep,
    user_id: UserDep,
    storage: StorageDep,
) -> Response | UploadOut:
    blocked = _not_wired("GET /api/uploads/{upload_id}", session, user_id, storage)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        upload = await _owned_upload(repos, _entity_id(upload_id), str(user_id))
    except service.UploadRefusal as error:
        return _refusal(error)

    return service.to_out(upload)
