"""Метаданные объекта: сумма, размер, тип, срок хранения.

Зачем отдельная запись рядом с файлом. Контрольную сумму нужно где-то держать,
и вариантов ровно два: считать при каждом чтении «от файла» (тогда сравнивать
не с чем и порча пройдет незамеченной) или записать при укладке и сверять при
выдаче. Работает только второй.

Срок хранения тоже лежит здесь, а не только в базе. Уборщик по сроку обязан
уметь пройти по хранилищу и назвать просроченные объекты, даже если строка в
базе потерялась: осиротевший файл — это чужая фонограмма, которую никто не
удалит, потому что про нее забыли.

Формат — JSON, читаемый человеком. В инциденте в файл будут смотреть глазами.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from . import retention
from .base import StoredObject
from .errors import StorageError
from .keys import key_kind, validate_key

#: Версия формата записи. Читатель обязан узнать чужой формат и отказаться,
#: а не разобрать его наполовину.
METADATA_VERSION = 1


@dataclass(frozen=True)
class ObjectMetadata:
    """Все, что хранилище знает об объекте помимо его содержимого."""

    key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str
    created_at: datetime
    retention_until: datetime

    def as_stored_object(self) -> StoredObject:
        return StoredObject(
            key=self.key,
            size_bytes=self.size_bytes,
            checksum_sha256=self.checksum_sha256,
            content_type=self.content_type,
        )


def checksum_of(data: bytes) -> str:
    """sha256 в шестнадцатеричном виде.

    Именно sha256, а не crc32 и не md5: сумма защищает не только от сбоя диска,
    но и от подмены содержимого, а от подмены короткая контрольная сумма не
    защищает вовсе.
    """
    return hashlib.sha256(data).hexdigest()


def build_metadata(
    key: str,
    data: bytes,
    content_type: str,
    *,
    now: datetime | None = None,
) -> ObjectMetadata:
    """Метаданные для укладываемого объекта. Срок хранения — из рода в ключе."""
    validate_key(key)
    moment = now or datetime.now(UTC)
    return ObjectMetadata(
        key=key,
        size_bytes=len(data),
        checksum_sha256=checksum_of(data),
        content_type=content_type,
        created_at=moment,
        retention_until=retention.retention_until(key_kind(key).value, moment),
    )


def dumps(metadata: ObjectMetadata) -> str:
    payload = {
        "version": METADATA_VERSION,
        "key": metadata.key,
        "size_bytes": metadata.size_bytes,
        "checksum_sha256": metadata.checksum_sha256,
        "content_type": metadata.content_type,
        "created_at": metadata.created_at.isoformat(),
        "retention_until": metadata.retention_until.isoformat(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def loads(key: str, raw: str) -> ObjectMetadata:
    """Разбирает запись метаданных.

    Строгость намеренная: испорченная запись — это отказ, а не «сумму сверить
    не удалось, отдадим как есть». Второе и есть молчаливая порча.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise StorageError(f"метаданные объекта {key!r} испорчены: {error}") from error
    if not isinstance(payload, dict):
        raise StorageError(f"метаданные объекта {key!r} не являются объектом JSON")

    version = payload.get("version")
    if version != METADATA_VERSION:
        raise StorageError(
            f"метаданные объекта {key!r} записаны версией {version!r}, "
            f"а читатель умеет версию {METADATA_VERSION}"
        )

    try:
        return ObjectMetadata(
            key=str(payload["key"]),
            size_bytes=int(payload["size_bytes"]),
            checksum_sha256=str(payload["checksum_sha256"]),
            content_type=str(payload["content_type"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            retention_until=datetime.fromisoformat(str(payload["retention_until"])),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StorageError(f"метаданные объекта {key!r} неполные: {error}") from error
