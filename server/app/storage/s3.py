"""S3-совместимое хранилище (Yandex Object Storage, VK Cloud, Selectel).

Российские провайдеры говорят на протоколе S3, поэтому клиент один на всех —
меняется только адрес эндпоинта. Никакой привязки к AWS в коде нет и быть не
должно: адрес региона и эндпоинта приходят из настроек.

**Класс падает при инициализации, если подключаться некуда.** Это главное
свойство файла. Хранилище без бакета и ключей не может ни положить, ни отдать
файл; объект, который создается «на всякий случай» и падает потом, при первой
загрузке пользователя, — та же ложная заглушка, которую продукт выпалывает из
интерфейса. Проверка настроек идет **до** проверки библиотеки: отсутствующая
конфигурация — более частая и более понятная причина отказа, и сообщение о ней
не должно зависеть от того, поставлен ли необязательный пакет.

Чего здесь честно нет: прогона против живого бакета. Тесты закрывают отказ без
настроек, подпись ссылки (она считается локально) и отбраковку опасных ключей.
Путь «положил — прочитал — удалил» в S3 не проверен ни разу, потому что
эндпоинта в окружении нет. Это записано в отчет батча, а не спрятано.

Про порядок операций стоит знать одно: в S3 нет атомарного «положи, если ключа
нет». Проверка занятости и запись — две операции, и щель между ними закрыта не
протоколом, а схемой ключей: идентификатор объекта — свежий UUID, второй раз
тот же ключ не сгенерируется.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from .base import ObjectStorage, StoredObject
from .config import StorageSettings
from .errors import (
    ChecksumMismatchError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
)
from .keys import validate_key
from .metadata import ObjectMetadata, build_metadata, checksum_of

#: Имена пользовательских метаданных объекта. Провайдер вернет их в нижнем
#: регистре независимо от того, как их записали, — поэтому пишем сразу так.
SHA256_META = "sha256"
CREATED_AT_META = "created-at"
RETENTION_UNTIL_META = "retention-until"

#: Какие настройки обязательны и как называется переменная окружения каждой.
#: Имя переменной попадает в текст отказа: человеку нужно знать, что именно
#: заполнить, а не что «хранилище не настроено».
_REQUIRED_SETTINGS: tuple[tuple[str, str], ...] = (
    ("s3_endpoint_url", "VOKAL_STORAGE_S3_ENDPOINT_URL"),
    ("s3_bucket", "VOKAL_STORAGE_S3_BUCKET"),
    ("s3_access_key_id", "VOKAL_STORAGE_S3_ACCESS_KEY_ID"),
    ("s3_secret_access_key", "VOKAL_STORAGE_S3_SECRET_ACCESS_KEY"),
)


def _require_boto3() -> Any:
    """Возвращает `boto3` или объясняет, чего не хватает.

    Импорт внутри функции, а не наверху файла: модуль обязан импортироваться
    даже там, где S3 не используется вовсе, иначе локальный диск потянет за
    собой зависимость, которая ему не нужна.
    """
    try:
        import boto3
    except ImportError as error:
        raise StorageConfigurationError(
            "Для S3-совместимого хранилища нужен пакет boto3. "
            "Установите зависимости сервера: pip install -e '.[dev]' "
            "или uv sync."
        ) from error
    if boto3 is None:  # pragma: no cover - защита от подмены модуля
        raise StorageConfigurationError("Пакет boto3 недоступен.")
    return boto3


class S3CompatibleStorage(ObjectStorage):
    """`ObjectStorage` поверх S3-совместимого объектного хранилища."""

    def __init__(self, settings: StorageSettings) -> None:
        missing = [
            variable
            for field, variable in _REQUIRED_SETTINGS
            if not (getattr(settings, field, None) or "")
        ]
        if missing:
            raise StorageConfigurationError(
                "S3-совместимое хранилище не настроено. Не заданы переменные: "
                + ", ".join(missing)
                + ". Шаблон — server/.env.example."
            )

        boto3 = _require_boto3()
        from botocore.config import Config

        self._settings = settings
        self._bucket = str(settings.s3_bucket)
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(
                # v4 обязателен: часть российских провайдеров других подписей
                # уже не принимает.
                signature_version="s3v4",
                # Путевая адресация, а не virtual-hosted: ее поддерживают все
                # совместимые провайдеры, а virtual-hosted требует, чтобы имя
                # бакета годилось для DNS.
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    # --- Контракт --------------------------------------------------------

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        validate_key(key)
        metadata = build_metadata(key, data, content_type)
        await asyncio.to_thread(self._put_sync, metadata, data)
        return metadata.as_stored_object()

    async def get(self, key: str) -> bytes:
        validate_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    async def delete(self, key: str) -> bool:
        validate_key(key)
        return await asyncio.to_thread(self._delete_sync, key)

    async def exists(self, key: str) -> bool:
        validate_key(key)
        return await asyncio.to_thread(self._head, key) is not None

    async def signed_url(self, key: str, expires_seconds: int) -> str:
        """Настоящая подписанная ссылка.

        Подпись считается локально, обращения к провайдеру здесь нет — но
        ссылка рабочая ровно настолько, насколько верны ключи доступа.
        """
        validate_key(key)
        return await asyncio.to_thread(self._signed_url_sync, key, expires_seconds)

    # --- Сверх контракта -------------------------------------------------

    async def stat(self, key: str) -> ObjectMetadata:
        validate_key(key)
        head = await asyncio.to_thread(self._head, key)
        if head is None:
            raise ObjectNotFoundError(f"объекта {key!r} нет в бакете {self._bucket!r}")
        return self._metadata_from_head(key, head)

    async def iter_objects(self) -> AsyncIterator[ObjectMetadata]:
        """Перебирает объекты бакета. Нужен уборщику по сроку хранения.

        По запросу на объект — листинг не отдает пользовательские метаданные,
        а срок хранения лежит именно в них. Для уборки, которая ходит раз в
        сутки, это приемлемо; для чего-то более частого понадобится хранить
        сроки рядом, в базе.
        """
        keys = await asyncio.to_thread(self._list_keys)
        for key in keys:
            head = await asyncio.to_thread(self._head, key)
            if head is None:
                # Объект удалили между листингом и запросом — обычная гонка.
                continue
            yield self._metadata_from_head(key, head)

    # --- Синхронная работа с провайдером ---------------------------------

    def _put_sync(self, metadata: ObjectMetadata, data: bytes) -> None:
        if self._head(metadata.key) is not None:
            raise ObjectAlreadyExistsError(
                f"объект {metadata.key!r} уже существует; перезапись запрещена"
            )
        self._client.put_object(
            Bucket=self._bucket,
            Key=metadata.key,
            Body=data,
            ContentType=metadata.content_type,
            Metadata={
                SHA256_META: metadata.checksum_sha256,
                CREATED_AT_META: metadata.created_at.isoformat(),
                RETENTION_UNTIL_META: metadata.retention_until.isoformat(),
            },
        )

    def _get_sync(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        # Не `ClientError`, а `Exception`: класс исключения живет в botocore,
        # а botocore здесь импортируется лениво — вместе с boto3. Ловить по
        # импорту наверху файла значит вернуть обязательную зависимость,
        # которой у локального диска нет. Разбор идет по коду ответа.
        except Exception as error:
            if self._is_missing(error):
                raise ObjectNotFoundError(
                    f"объекта {key!r} нет в бакете {self._bucket!r}"
                ) from error
            raise

        data: bytes = response["Body"].read()
        expected = (response.get("Metadata") or {}).get(SHA256_META)
        if not expected:
            # Объект без записанной суммы положили не мы. Сверять его не с чем,
            # а отдавать несверенное содержимое — ровно та молчаливая порча,
            # против которой сумма и заведена.
            raise StorageError(
                f"у объекта {key!r} нет записанной суммы sha256; "
                "проверить содержимое нечем"
            )

        actual = checksum_of(data)
        if actual != expected:
            raise ChecksumMismatchError(
                f"содержимое объекта {key!r} не совпадает с записанной суммой: "
                f"ожидалось {expected}, получено {actual}"
            )
        return data

    def _delete_sync(self, key: str) -> bool:
        # S3 отвечает успехом и на удаление несуществующего ключа, поэтому
        # «был ли объект» приходится выяснять отдельным запросом. Контракт
        # требует различать эти случаи: `False` — объекта не было.
        existed = self._head(key) is not None
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return existed

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            response: dict[str, Any] = self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as error:  # причина широкого перехвата — в `_get_sync`
            if self._is_missing(error):
                return None
            raise
        return response

    def _list_keys(self) -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket):
            for item in page.get("Contents", []):
                keys.append(str(item["Key"]))
        return keys

    def _signed_url_sync(self, key: str, expires_seconds: int) -> str:
        return str(
            self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_seconds or self._settings.s3_signed_url_ttl_seconds,
            )
        )

    def _metadata_from_head(self, key: str, head: dict[str, Any]) -> ObjectMetadata:
        user_metadata = head.get("Metadata") or {}
        return ObjectMetadata(
            key=key,
            size_bytes=int(head.get("ContentLength", 0)),
            checksum_sha256=str(user_metadata.get(SHA256_META, "")),
            content_type=str(head.get("ContentType", "application/octet-stream")),
            created_at=self._moment(user_metadata.get(CREATED_AT_META)),
            retention_until=self._moment(user_metadata.get(RETENTION_UNTIL_META)),
        )

    @staticmethod
    def _moment(value: str | None) -> datetime:
        """Момент времени из метаданных.

        Отсутствие срока хранения читается как «срок в бесконечности», а не
        как «просрочено»: уборщик, который сметает объекты без записанного
        срока, удалит чужие материалы за отсутствие поля.
        """
        if not value:
            return datetime.max.replace(tzinfo=UTC)
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.max.replace(tzinfo=UTC)

    @staticmethod
    def _is_missing(error: Exception) -> bool:
        """Отличает «объекта нет» от любой другой ошибки провайдера."""
        response = getattr(error, "response", None)
        if not isinstance(response, dict):
            return False
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in {"404", "NoSuchKey", "NotFound"} or status == 404
