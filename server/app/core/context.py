"""Идентификатор запроса, доступный из любого места обработки.

Через contextvar, а не через параметр функции: идентификатор нужен логам,
обработчикам ошибок и будущим адаптерам провайдеров, и протаскивать его
руками через каждый вызов — гарантированный способ где-то его потерять.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from typing import Any

# Тот же идентификатор кладется и в scope запроса. Причина: слой обработки
# ошибок Starlette (ServerErrorMiddleware) снаружи нашего слоя, и к моменту
# сборки ответа 500 contextvar уже сброшен. Из scope он читается всегда.
REQUEST_ID_SCOPE_KEY = "vokal.request_id"

_request_id: ContextVar[str | None] = ContextVar("vokal_request_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def set_request_id(value: str) -> Token[str | None]:
    return _request_id.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id.reset(token)


def request_id_from_scope(scope: MutableMapping[str, Any]) -> str | None:
    value = scope.get(REQUEST_ID_SCOPE_KEY)
    return value if isinstance(value, str) else None
