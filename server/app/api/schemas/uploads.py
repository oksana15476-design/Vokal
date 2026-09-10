"""Схемы загрузки исходника.

Ограничения приема — часть контракта, а не тайна сервера: клиент обязан уметь
спросить их до выбора файла, иначе пользователь узнает о пределе, потеряв
время на отправку. Отсюда отдельный адрес `GET /api/uploads/constraints`.

Числа здесь те же, что на фронтенде (`src/services/mockServices.ts`), и это
проверяется тестом: если фронтенд принимает файл, который отвергнет сервер,
интерфейс обещает прием там, где его нет.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import UploadFormat, UploadQuality, UploadState

#: Столько же принимает фронтенд и столько же пропускает каркас
#: (`max_request_body_bytes` в `app/core/config.py`).
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: Расширения, а не MIME: браузеры сообщают тип файла вразнобой, и отказ по
#: MIME отсекал бы нормальные файлы. Тот же выбор сделан на фронтенде.
SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = ("mp3", "wav", "flac", "m4a")

#: Подсказка клиенту для атрибута `accept` у поля выбора файла. Не проверяется.
SUPPORTED_CONTENT_TYPES: tuple[str, ...] = (
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/vnd.wave",
    "audio/flac",
    "audio/x-flac",
    "audio/mp4",
    "audio/x-m4a",
)

FORMAT_BY_EXTENSION: dict[str, UploadFormat] = {
    "mp3": UploadFormat.MP3,
    "wav": UploadFormat.WAV,
    "flac": UploadFormat.FLAC,
    "m4a": UploadFormat.M4A,
}


def extension_of(file_name: str) -> str:
    _, _, extension = file_name.rpartition(".")
    return extension.lower()


class UploadConstraints(ApiModel):
    """Что сервер примет. Возвращается клиенту явно, до выбора файла."""

    max_size_bytes: int = Field(description="Предел размера файла в байтах")
    allowed_extensions: list[str] = Field(description="Расширения в нижнем регистре, без точки")
    allowed_content_types: list[str] = Field(
        description="Подсказка для атрибута accept. Сервер проверяет расширение, не MIME."
    )
    max_duration_seconds: int | None = Field(
        default=None,
        description=(
            "Предел длительности. Сейчас не установлен: подобрать его можно только "
            "по себестоимости настоящей обработки, а обработки еще нет. "
            "Выдуманное число здесь стало бы обещанием продукта."
        ),
    )
    note: str = Field(description="Пояснение для интерфейса")


class UploadCreateRequest(ApiModel):
    """Заявка на загрузку. Файл в теле не передается.

    Тело запроса — только сведения о файле: сам файл уходит прямо в хранилище
    по выданной ссылке, минуя приложение. Иначе каждая песня проходила бы через
    процесс API, занимая его на все время передачи.
    """

    file_name: str = Field(min_length=1, max_length=400, description="Имя файла с расширением")
    size_bytes: int = Field(gt=0, description="Размер файла в байтах")
    content_type: str | None = Field(
        default=None, max_length=100, description="MIME по данным браузера. Не проверяется."
    )
    duration_seconds: int | None = Field(
        default=None, ge=0, description="Длительность, если браузер сумел декодировать файл"
    )
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0, le=32)

    @field_validator("file_name")
    @classmethod
    def _supported_extension(cls, value: str) -> str:
        extension = extension_of(value)
        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            raise ValueError(
                f"Формат .{extension or '?'} не поддерживается. Подойдут MP3, WAV, FLAC или M4A."
            )
        return value

    @field_validator("size_bytes")
    @classmethod
    def _within_limit(cls, value: int) -> int:
        if value > MAX_UPLOAD_BYTES:
            megabytes = MAX_UPLOAD_BYTES // 1024 // 1024
            raise ValueError(f"Файл больше {megabytes} МБ.")
        return value


class UploadTarget(ApiModel):
    """Куда класть файл: подписанная ссылка в хранилище."""

    method: str = Field(description="HTTP-метод запроса в хранилище, например PUT")
    url: str = Field(description="Подписанная ссылка. В логи не попадает никогда.")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Заголовки, обязательные при отправке"
    )
    expires_at: datetime = Field(description="Когда ссылка перестанет действовать")


class UploadOut(ApiModel):
    """Загрузка. Повторяет `Upload` из `src/domain/types.ts` и добавляет состояние."""

    id: str
    file_name: str
    format: UploadFormat
    state: UploadState
    duration_seconds: int = Field(ge=0, description="0, пока длительность неизвестна")
    quality: UploadQuality
    source_note: str = Field(description="Пояснение о происхождении файла для интерфейса")
    size_bytes: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    created_at: datetime


class UploadCreateResponse(ApiModel):
    upload: UploadOut
    target: UploadTarget


class UploadCompleteRequest(ApiModel):
    """Подтверждение, что файл доехал в хранилище."""

    size_bytes: int = Field(gt=0, description="Размер, фактически принятый хранилищем")
    checksum: str | None = Field(
        default=None, max_length=128, description="Контрольная сумма, если хранилище ее вернуло"
    )
