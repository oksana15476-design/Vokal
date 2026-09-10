"""Окружение Alembic.

Драйвер асинхронный (asyncpg), поэтому миграции гоняются через
`asyncio.run`: engine у приложения один, и заводить второй, синхронный, ради
миграций — значит держать две конфигурации подключения и однажды развести их.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  (импорт наполняет metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Строка подключения: сначала конфиг Alembic, затем окружение.

    Порядок такой, чтобы тесты и скрипты могли подставить свою базу, не трогая
    переменные окружения процесса.
    """
    from_config = config.get_main_option("sqlalchemy.url")
    if from_config:
        return from_config
    from_env = os.environ.get("VOKAL_DATABASE_URL")
    if not from_env:
        raise RuntimeError(
            "Не задана строка подключения: ни sqlalchemy.url в alembic.ini, "
            "ни VOKAL_DATABASE_URL в окружении."
        )
    return from_env


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
