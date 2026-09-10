"""Тестовая база и фикстуры слоя данных.

Схема в тестах поднимается **миграциями**, а не `metadata.create_all`. Причина
простая: до боевой базы доедет миграция, а не модели. Если тесты строят схему в
обход миграций, зеленый прогон ничего не говорит о том, поднимется ли схема на
сервере, и расхождение вскроется на деплое.

Откат между тестами сделан внешней транзакцией, а не пересозданием базы: каждый
тест получает сессию внутри транзакции, которая гарантированно откатывается.
Пересоздавать схему на каждый тест дорого, а `DELETE FROM` по таблицам молча
пропускает то, что появилось в схеме позже.

Подключение берется из `VOKAL_TEST_DATABASE_URL`. Умолчание идет через
unix-сокет и peer-аутентификацию, чтобы в репозитории не было ни пароля, ни
строки подключения с секретом.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _default_test_database_url() -> str:
    """Локальное умолчание без секретов: сокет + peer-аутентификация."""
    return f"postgresql+asyncpg://{getpass.getuser()}@/vokal_test?host=/var/run/postgresql"


TEST_DATABASE_URL = os.environ.get("VOKAL_TEST_DATABASE_URL") or _default_test_database_url()


async def _recreate_database() -> None:
    """Пересоздает тестовую базу с нуля.

    Именно с нуля, потому что первая миграция обязана поднимать схему на пустой
    базе. Накатывать ее на остатки прошлого прогона — значит не проверять то,
    ради чего миграция написана.
    """
    import asyncpg

    url = make_url(TEST_DATABASE_URL)
    database = url.database
    if not database:
        raise RuntimeError("В VOKAL_TEST_DATABASE_URL не указано имя базы.")

    maintenance = url.set(database="postgres")
    connect_kwargs: dict[str, object] = {
        "user": maintenance.username,
        "password": maintenance.password,
        "database": maintenance.database,
    }
    host = maintenance.host or maintenance.query.get("host")
    if host:
        connect_kwargs["host"] = host
    if maintenance.port:
        connect_kwargs["port"] = maintenance.port

    connection = await asyncpg.connect(**connect_kwargs)  # type: ignore[arg-type]
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{database}"')
    finally:
        await connection.close()


def _run_migrations() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Один раз за прогон: чистая база + `alembic upgrade head`.

    Не `autouse`: `conftest.py` общий на весь каталог тестов, и автозапуск
    заставил бы поднимать PostgreSQL ради тестов, которым база не нужна
    вовсе, — например, проверок HTTP-слоя. Базу получают только те тесты,
    которые попросили `engine`, `connection` или `session`.
    """
    try:
        asyncio.run(_recreate_database())
    except OSError as error:  # база недоступна — это провал, а не повод пропустить тесты
        raise RuntimeError(
            "Не удалось подключиться к тестовому PostgreSQL по адресу "
            f"{TEST_DATABASE_URL}. Поднимите сервер или задайте "
            "VOKAL_TEST_DATABASE_URL."
        ) from error
    _run_migrations()
    yield TEST_DATABASE_URL


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """Свой engine на тест.

    NullPool и отдельный engine нужны потому, что соединения asyncpg привязаны
    к событийному циклу. Пул, переживший тест, отдаст в следующий тест
    соединение из чужого уже закрытого цикла.
    """
    created = create_async_engine(migrated_database, poolclass=NullPool)
    try:
        yield created
    finally:
        await created.dispose()


@pytest_asyncio.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Соединение с открытой внешней транзакцией: она откатывается после теста."""
    opened = await engine.connect()
    transaction = await opened.begin()
    try:
        yield opened
    finally:
        if transaction.is_active:
            await transaction.rollback()
        await opened.close()


@pytest.fixture
def session_factory(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий на тестовом соединении.

    `join_transaction_mode="create_savepoint"` позволяет коду под тестом делать
    настоящий `commit()` — он схлопнется в release savepoint, а внешний откат
    все равно вернет базу в исходное состояние. Без этого проверить единицу
    работы (коммит и откат) нельзя: тест либо не откатывается, либо не коммитит.
    """
    return async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    opened = session_factory()
    try:
        yield opened
    finally:
        await opened.close()
