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
from app.api.schemas.consent import ConsentAcceptance
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

    Тело запроса — только сведения о файле. Сам файл уходит вторым запросом по
    адресу из `UploadTarget`: формат и размер должны быть проверены до того,
    как пользователь потратит время на передачу десятков мегабайт.

    Развилка «файл мимо приложения по подписанной ссылке или через него»
    закрыта в `app/storage/base.py` в пользу приема через API: провайдер
    объектного хранения не выбран, и presign против несуществующего провайдера
    снаружи неотличим от рабочего.
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
    project_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Песня, к которой относится исходник. Без него сервер отвечает 501 и называет "
            "причину: строка загрузки в базе требует проекта (`uploads.project_id`), а "
            "создание проекта требует принятой загрузки. Развилка вынесена владельцу."
        ),
    )
    consent: ConsentAcceptance | None = Field(
        default=None,
        description=(
            "Согласие на обработку материала. Обязательно там, где файл действительно "
            "принимается: запись «согласие получено» задним числом не восстанавливается."
        ),
    )

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
    """Куда отправлять файл.

    Это адрес нашего API, а не подписанная ссылка в хранилище: развилка закрыта
    в `app/storage/base.py`. Форма ответа рассчитана на оба режима — когда
    провайдер хранения будет выбран, сюда встанет подписанная ссылка, и клиент
    менять не придется: он и сейчас отправляет файл туда, куда сказано.
    """

    method: str = Field(description="HTTP-метод отправки, например PUT")
    url: str = Field(description="Адрес отправки. В логи не попадает никогда.")
    headers: dict[str, str] = Field(
        default_factory=dict, description="Заголовки, обязательные при отправке"
    )
    expires_at: datetime = Field(
        description="Докуда заявка действительна. После этого срока файл не примут."
    )


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
