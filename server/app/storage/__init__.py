"""Хранилище объектов.

Контракт — `base.py` (аудио идет через API, подписанная ссылка необязательна).
Сроки хранения — `retention.py`. Оба файла написаны до этого батча и здесь не
меняются.

Что добавлено сверху: схема ключей (`keys`), метаданные с контрольной суммой
(`metadata`), две реализации (`local`, `s3`), выбор реализации по настройкам
(`config`, `factory`) и поиск просроченного (`sweep`).

Импортировать в прикладном коде стоит `ObjectStorage` и `get_storage()`, а не
конкретный класс: на локальном диске и в S3 у кода один и тот же вызывающий
путь, и это единственная причина, по которой переезд в облако не станет
переписыванием.
"""

from .base import ObjectStorage, StoredObject
from .config import (
    DEFAULT_LOCAL_ROOT,
    DEFAULT_SIGNED_URL_TTL_SECONDS,
    KNOWN_BACKENDS,
    LOCAL_BACKEND,
    S3_BACKEND,
    StorageSettings,
    get_storage_settings,
)
from .errors import (
    ChecksumMismatchError,
    InvalidKeyError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    StorageConfigurationError,
    StorageError,
)
from .factory import create_storage, get_storage
from .keys import (
    MAX_KEY_LENGTH,
    ObjectKind,
    ParsedKey,
    build_key,
    extension_of,
    key_kind,
    normalize_project_id,
    parse_key,
    validate_key,
)
from .local import LocalDiskStorage
from .metadata import ObjectMetadata, build_metadata, checksum_of
from .retention import (
    AUDIT_LOG_DAYS,
    DELETION_SLA_HOURS,
    RESULTS_DAYS,
    SOURCE_DAYS,
    TECH_LOG_DAYS,
    deletion_deadline,
    retention_until,
)
from .s3 import S3CompatibleStorage
from .sweep import SupportsScan, find_expired

__all__ = [
    "AUDIT_LOG_DAYS",
    "DEFAULT_LOCAL_ROOT",
    "DEFAULT_SIGNED_URL_TTL_SECONDS",
    "DELETION_SLA_HOURS",
    "KNOWN_BACKENDS",
    "LOCAL_BACKEND",
    "MAX_KEY_LENGTH",
    "RESULTS_DAYS",
    "S3_BACKEND",
    "SOURCE_DAYS",
    "TECH_LOG_DAYS",
    "ChecksumMismatchError",
    "InvalidKeyError",
    "LocalDiskStorage",
    "ObjectAlreadyExistsError",
    "ObjectKind",
    "ObjectMetadata",
    "ObjectNotFoundError",
    "ObjectStorage",
    "ParsedKey",
    "S3CompatibleStorage",
    "StorageConfigurationError",
    "StorageError",
    "StorageSettings",
    "StoredObject",
    "SupportsScan",
    "build_key",
    "build_metadata",
    "checksum_of",
    "create_storage",
    "deletion_deadline",
    "extension_of",
    "find_expired",
    "get_storage",
    "get_storage_settings",
    "key_kind",
    "normalize_project_id",
    "parse_key",
    "retention_until",
    "validate_key",
]
