"""Подключение к базе и единица работы.

Единица работы — одна транзакция на запрос. Успешный запрос коммитит, любое
исключение откатывает, соединение закрывается всегда. Половина записанного
запроса хуже незаписанного: продукт покажет проект без версии или версию без
материалов и будет выглядеть рабочим.

Слой асинхронный (SQLAlchemy 2 + asyncpg). Причина не в моде: обработка песни
идет джобами, и эндпоинты прогресса держат соединение долго. Синхронные
обработчики FastAPI на таких запросах выедают пул потоков.

Строка подключения берется только из окружения. Умолчания с логином и паролем
здесь нет и быть не может: `VOKAL_DATABASE_URL` не задан — падаем с понятной
причиной, а не подключаемся молча куда-то еще.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL_ENV = "VOKAL_DATABASE_URL"


def database_url() -> str:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"Переменная окружения {DATABASE_URL_ENV} не задана. "
            "Пример: postgresql+asyncpg://user@host/vokal. "
            "Значения по умолчанию нет намеренно: подключение к чужой базе "
            "по умолчанию — худшая из возможных ошибок конфигурации."
        )
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Engine на процесс.

    `pool_pre_ping` включен: соединение, которое разорвал файрвол или
    перезапуск базы, иначе всплывет как ошибка случайного запроса пользователя.
    """
    return create_async_engine(database_url(), pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    # autoflush оставлен включенным (умолчание): репозитории перечитывают
    # строки с populate_existing, и незаписанная правка иначе была бы затерта
    # следующим чтением.
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    *, factory: async_sessionmaker[AsyncSession] | None = None
) -> AsyncIterator[AsyncSession]:
    """Транзакция на блок: коммит на выходе, откат на любом исключении.

    `factory` подменяется в тестах и скриптах. В боевом коде не передается.
    """
    maker = factory or get_session_factory()
    session = maker()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: одна транзакция на запрос.

    Подключение к приложению делает батч API — здесь только сама единица
    работы, без импорта FastAPI.
    """
    async with session_scope() as session:
        yield session


def reset_engine_cache() -> None:
    """Сбрасывает закешированные engine и фабрику.

    Нужно там, где строка подключения меняется в рамках процесса: тесты,
    скрипты обслуживания. В обработке запросов не вызывается.
    """
    get_engine.cache_clear()
    get_session_factory.cache_clear()
