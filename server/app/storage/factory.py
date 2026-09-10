"""Выбор реализации хранилища по настройкам.

Одна переменная — `VOKAL_STORAGE_BACKEND`. Умолчание — локальный диск.

Почему выбор вынесен в отдельный модуль, а не сделан импортом нужного класса
там, где он нужен: вызывающий код обязан зависеть от контракта `ObjectStorage`,
а не от конкретной реализации. Переезд на S3 тогда — смена одной переменной
окружения, а не правка мест, где хранилище используется.

Неизвестное значение переменной — отказ с перечислением известных. Молча
свалиться на локальный диск при опечатке в `s3` значит начать писать
пользовательские фонограммы на диск контейнера, который исчезнет при
следующем деплое.
"""

from __future__ import annotations

from functools import lru_cache

from .base import ObjectStorage
from .config import KNOWN_BACKENDS, LOCAL_BACKEND, S3_BACKEND, StorageSettings, get_storage_settings
from .errors import StorageConfigurationError
from .local import LocalDiskStorage
from .s3 import S3CompatibleStorage


def create_storage(settings: StorageSettings | None = None) -> ObjectStorage:
    """Собирает хранилище по настройкам."""
    resolved = settings or get_storage_settings()
    backend = (resolved.backend or "").strip().lower()

    if backend == LOCAL_BACKEND:
        return LocalDiskStorage(resolved.local_root)
    if backend == S3_BACKEND:
        return S3CompatibleStorage(resolved)

    raise StorageConfigurationError(
        f"Неизвестное значение VOKAL_STORAGE_BACKEND: {resolved.backend!r}. "
        f"Известные: {', '.join(KNOWN_BACKENDS)}."
    )


@lru_cache(maxsize=1)
def get_storage() -> ObjectStorage:
    """Хранилище процесса. Кэш ради одного клиента S3 на процесс, а не на запрос."""
    return create_storage()
