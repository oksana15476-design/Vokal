"""Подключение к базе и единица работы.

Единица работы — одна транзакция на запрос. Успешный запрос коммитит, любое
исключение откатывает, соединение закрывается всегда. Половина записанного
запроса хуже незаписанного: продукт покажет проект без версии или версию без
материалов и будет выглядеть рабочим.

Слой асинхронный (SQLAlchemy 2 + asyncpg). Причина не в моде: обработка песни
идет джобами, и эндпоинты прогресса держат соединение долго. Синхронные
обработчики FastAPI на таких запросах выедают пул потоков.

Строка подключения берется из настроек сервиса и больше ниоткуда. Умолчания с
логином и паролем нет и быть не может: адрес не задан — падаем с понятной
причиной, а не подключаемся молча куда-то еще.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


def database_url() -> str:
    """Адрес базы. Единственный источник — `Settings`.

    Раньше модуль читал переменную окружения сам, и в одном процессе
    получалось два разных ответа на вопрос «куда подключаться». `Settings`
    понимает и имя `DATABASE_URL` (так переменную называют площадки), и схему
    `postgresql://` без драйвера — приводит ее к `postgresql+asyncpg://`.
    Прямое чтение окружения не делало ни того, ни другого. Итог расхождения
    был худшим из возможных: проба `/ready` брала адрес из настроек и
    отвечала «готов», а первая же сессия падала — процесс отчитывался
    работающим, не будучи им.

    Отсутствие адреса поднимает `ConfigurationError` (это `RuntimeError`) с
    перечислением недостающих переменных и ссылкой на `server/.env.example`.
    """
    return get_settings().database_url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """Engine на процесс — один, и создается один раз.

    Кеш здесь не оптимизация: engine владеет пулом соединений. Второй engine
    в том же процессе означает второй пул, то есть вдвое больше соединений к
    базе, чем показывают настройки, и лимит подключений PostgreSQL
    заканчивается не там, где его считали.

    `pool_pre_ping` включен: соединение, которое разорвал файрвол или
    перезапуск базы, иначе всплывет как ошибка случайного запроса пользователя.

    Отдельный движок в процессе есть ровно один и по делу — проба готовности
    (`app/core/db.py`, `NullPool`): готовность означает «сервис может открыть
    новое соединение», а не «в пуле лежит старое». Адрес базы у обоих теперь
    общий, потому что оба берут его из `Settings`.
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

    Настройки сбрасываются вместе с движком: адрес базы читается из них, и
    сброс одного лишь движка молча пересоздал бы его на прежнем адресе —
    функция не делала бы того, ради чего ее зовут.

    Старые соединения при этом не закрываются: `dispose()` — операция
    асинхронная, а сюда ходят и синхронные скрипты. Вызывающий, которому
    важно закрыть пул, делает это сам до сброса.
    """
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
