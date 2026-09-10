"""Проба базы данных для проверки готовности.

Здесь только проба. Сессии, модели и миграции живут в `app/db` и
`server/migrations` — их приносит соседний батч. Отдельное соединение для
пробы взято сознательно: готовность означает «сервис может открыть новое
соединение», а не «в пуле лежит старое».
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings

_MAX_ERROR_LENGTH = 300


@dataclass(frozen=True)
class DatabaseCheck:
    ok: bool
    latency_ms: float
    error: str | None = None


def create_probe_engine(settings: Settings) -> AsyncEngine:
    from sqlalchemy.pool import NullPool

    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"timeout": settings.db_connect_timeout_seconds},
    )


async def check_database(engine: AsyncEngine, *, timeout: float, dsn: str) -> DatabaseCheck:
    """Настоящий запрос в базу, а не флаг в памяти.

    `SELECT 1` выбран потому, что не зависит от схемы: каркас обязан отвечать
    о готовности и до того, как миграции создадут таблицы.
    """
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except TimeoutError:
        return DatabaseCheck(
            ok=False,
            latency_ms=_elapsed_ms(started),
            error=f"База не ответила за {timeout} с",
        )
    except Exception as error:  # noqa: BLE001 — любая ошибка означает «не готовы»
        return DatabaseCheck(
            ok=False,
            latency_ms=_elapsed_ms(started),
            error=mask_secrets(f"{type(error).__name__}: {error}", dsn),
        )
    return DatabaseCheck(ok=True, latency_ms=_elapsed_ms(started))


def mask_secrets(message: str, dsn: str) -> str:
    """Убирает пароль из текста ошибки.

    Текст ошибки уходит в ответ `/ready` и в логи, а драйверы регулярно
    вкладывают в него полный DSN вместе с паролем.
    """
    message = message[:_MAX_ERROR_LENGTH]
    try:
        password = make_url(dsn).password
    except Exception:  # noqa: BLE001 — разобрать DSN не удалось, маскировать нечего
        return message
    if password:
        message = message.replace(password, "***")
    return message


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
