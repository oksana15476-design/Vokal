"""Загрузка исходника.

Ограничения приема отдаются отдельным адресом и работают по-настоящему: это
чистая конфигурация, для нее не нужны ни база, ни хранилище. Все остальное
здесь отвечает `501` — выдать ссылку на загрузку некуда, пока не выбрано
объектное хранилище (`docs/DATA_MAP.md`: провайдера выбирают после ответов
по трансграничной передаче).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import SessionDep, UserDep
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
)

router = APIRouter(prefix="/uploads", tags=["загрузка"])

UploadIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор загрузки")]

STORAGE_MISSING = (
    "объектное хранилище (провайдер не выбран, docs/DATA_MAP.md)",
    "выдача подписанных ссылок",
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
    summary="Завести загрузку и получить ссылку для отправки файла",
    description=(
        "Файл в теле не передается: он уходит прямо в хранилище по выданной ссылке. "
        "Формат и размер проверяются здесь, до отправки."
    ),
    responses=errors(401, 413, 422, 501),
)
async def create_upload(
    payload: UploadCreateRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/uploads",
        message="Прием файлов не включен: хранилище для исходников еще не подключено.",
        missing=STORAGE_MISSING,
    )


@router.post(
    "/{upload_id}/complete",
    response_model=UploadOut,
    summary="Подтвердить, что файл доехал",
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def complete_upload(
    upload_id: UploadIdPath,
    payload: UploadCompleteRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="POST /api/uploads/{upload_id}/complete",
        message="Подтверждать нечего: файлы пока не принимаются.",
        missing=STORAGE_MISSING,
    )


@router.get(
    "/{upload_id}",
    response_model=UploadOut,
    summary="Состояние загрузки",
    responses=errors(401, 403, 404, 501),
)
async def read_upload(
    upload_id: UploadIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    return not_implemented(
        endpoint="GET /api/uploads/{upload_id}",
        message="Сведений о загрузке нет: файлы пока не принимаются.",
        missing=STORAGE_MISSING,
    )
