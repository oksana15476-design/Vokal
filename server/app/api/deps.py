"""Зависимости роутеров.

Обе зависимости здесь — **заглушки**, и это видно снаружи: сессия равна `None`,
пользователь равен `None`. Ни одна из них не притворяется работающей.

Так сделано потому, что слой данных и авторизация собираются другими батчами.
Роутеры уже объявляют шов, куда их подключат:

    from app.db.session import get_session
    app.dependency_overrides[db_session] = get_session

Заглушка не бросает исключение намеренно. Если бы бросала, запрос падал бы
`500` («внутренняя ошибка») до того, как дойдет до обработчика, и клиент видел
бы поломку вместо честного `501` «не реализовано». Разница существенная:
`500` зовет чинить сервер, `501` говорит, что этой части еще нет.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Query


async def db_session() -> AsyncIterator[Any | None]:
    """Сессия базы данных. Пока `None`: единицу работы подключает батч БД."""
    yield None


async def current_user_id() -> str | None:
    """Владелец запроса. Пока `None`: авторизации в продукте еще нет.

    Все адреса ниже описаны так, будто проверка прав уже есть (`401`, `403` в
    схеме) — потому что она обязательна, а не потому, что она работает. До ее
    появления адреса отвечают `501`, и подставить чужой проект некуда.
    """
    return None


SessionDep = Annotated[Any | None, Depends(db_session)]
UserDep = Annotated[str | None, Depends(current_user_id)]


class Pagination:
    """Постраничность списков: одинаковая для всех перечислений."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=200, description="Сколько записей вернуть")] = 20,
        offset: Annotated[int, Query(ge=0, description="Сколько записей пропустить")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PageDep = Annotated[Pagination, Depends(Pagination)]
