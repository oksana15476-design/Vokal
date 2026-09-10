"""Настройки сервиса. Единственный источник — переменные окружения.

Значений по умолчанию для адреса базы нет намеренно: правдоподобный адрес
вроде `localhost/vokal` прячет ошибку конфигурации до первого запроса к базе,
а нам нужно, чтобы неверно настроенный процесс не поднимался вовсе.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Фронтенд Vite: 5173 — сервер разработки, 4173 — предпросмотр сборки,
# против которого гоняются сквозные проверки.
DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"
)

# Столько же принимает фронтенд (`maxUploadBytes` в src/services/mockServices.ts).
# Держим одно число с двух сторон, иначе пользователь получит отказ там, где
# интерфейс обещал прием.
DEFAULT_MAX_REQUEST_BODY_BYTES = 50 * 1024 * 1024


class ConfigurationError(RuntimeError):
    """Процесс не может стартовать: окружение задано неверно."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VOKAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "vokal-api"
    app_env: str = "local"
    log_level: str = "INFO"

    # Псевдоним DATABASE_URL оставлен потому, что этим именем переменную
    # подставляют почти все площадки, включая Timeweb.
    database_url: str = Field(
        validation_alias=AliasChoices("VOKAL_DATABASE_URL", "DATABASE_URL"),
        description="DSN PostgreSQL, например postgresql+asyncpg://user:pass@host:5432/vokal",
    )
    db_connect_timeout_seconds: float = 5.0
    db_check_timeout_seconds: float = 3.0

    cors_origins: str = DEFAULT_CORS_ORIGINS
    request_id_header: str = "X-Request-ID"
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES

    # Схема API нужна фронтенду для генерации клиента, но открытая схема
    # наружу в проде — лишняя подсказка. Выключается переменной.
    docs_enabled: bool = True

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("адрес базы данных пустой")
        # SQLAlchemy 2 в асинхронном режиме требует явный драйвер. Обычный
        # postgresql:// молча уводит на синхронный psycopg и падает позже
        # невнятной ошибкой, поэтому чиним схему здесь.
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        # Строка с запятыми, а не list[str]: pydantic-settings пытается разобрать
        # сложные типы как JSON до валидаторов, и человеку пришлось бы писать
        # в .env массив в кавычках.
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        missing = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
        raise ConfigurationError(
            "Не заданы обязательные переменные окружения: "
            + ", ".join(missing)
            + ". Шаблон — server/.env.example."
        ) from error
