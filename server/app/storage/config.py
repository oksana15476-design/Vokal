"""Настройки хранилища.

Отдельный класс настроек, а не поля в `app.core.config.Settings`, по двум
причинам. Первая — зона правок: `app/core/config.py` правят другие батчи
параллельно, и общий файл превратился бы в конфликт вместо кода. Вторая —
связность: настройки хранилища читает только хранилище, и когда появится
второй бэкенд, менять придется один файл. Префикс `VOKAL_STORAGE_` не
пересекается с `VOKAL_` из ядра, потому что ядро игнорирует лишние переменные
(`extra="ignore"`).

Выбор реализации — одна переменная `VOKAL_STORAGE_BACKEND`. Умолчание —
локальный диск: он работает без единого секрета, а значит поднятый из
`git clone` сервис не падает на первой загрузке файла и не требует заводить
бакет ради проверки.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Значения `VOKAL_STORAGE_BACKEND`.
LOCAL_BACKEND = "local"
S3_BACKEND = "s3"
KNOWN_BACKENDS = (LOCAL_BACKEND, S3_BACKEND)

#: Куда локальный диск кладет файлы по умолчанию. Относительный путь —
#: намеренно: абсолютное умолчание вроде `/var/lib/vokal` требует прав, которых
#: у разработчика нет, и первая же загрузка падает на `PermissionError`.
DEFAULT_LOCAL_ROOT = Path("var/object-storage")

#: Сколько живет подписанная ссылка. Пятнадцать минут — столько, сколько нужно
#: браузеру начать скачивание, и мало, чтобы ссылка из чужой истории браузера
#: осталась рабочей.
DEFAULT_SIGNED_URL_TTL_SECONDS = 900


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOKAL_STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend: str = LOCAL_BACKEND
    local_root: Path = DEFAULT_LOCAL_ROOT

    # Умолчаний у доступов нет и не будет. Пустое значение означает «не
    # настроено», и S3-хранилище на таком значении отказывается стартовать,
    # а не пытается ходить в никуда.
    s3_endpoint_url: str | None = None
    s3_bucket: str | None = None
    s3_region: str = "ru-central1"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_signed_url_ttl_seconds: int = DEFAULT_SIGNED_URL_TTL_SECONDS


@lru_cache(maxsize=1)
def get_storage_settings() -> StorageSettings:
    return StorageSettings()
