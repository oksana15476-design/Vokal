"""Промежуточные слои: идентификатор запроса, лог доступа, лимит тела.

Написаны как чистые ASGI-слои, а не через BaseHTTPMiddleware: лимит размера
обязан вмешаться в чтение тела до того, как его прочитает обработчик, а
BaseHTTPMiddleware такой возможности не дает.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import (
    REQUEST_ID_SCOPE_KEY,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from app.core.errors import error_response
from app.core.logging import get_logger

access_logger = get_logger("access")

# Идентификатор приходит снаружи и попадает в логи. Без фильтра туда можно
# положить перевод строки и подделать соседнюю запись лога.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:@-]{1,128}$")

# Методы без тела: тратить на них проверку лимита незачем.
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def sanitize_request_id(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    return candidate if _SAFE_REQUEST_ID.match(candidate) else None


def human_bytes(value: int) -> str:
    for unit, size in (("ГБ", 1024**3), ("МБ", 1024**2), ("КБ", 1024)):
        if value >= size:
            number = value / size
            text = f"{number:.0f}" if abs(number - round(number)) < 0.05 else f"{number:.1f}"
            return f"{text} {unit}"
    return f"{value} Б"


class RequestContextMiddleware:
    """Ставит идентификатор запроса и пишет строку доступа."""

    def __init__(self, app: ASGIApp, *, header_name: str) -> None:
        self.app = app
        self.header_name = header_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = sanitize_request_id(headers.get(self.header_name)) or uuid4().hex
        scope[REQUEST_ID_SCOPE_KEY] = request_id
        token = set_request_id(request_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                MutableHeaders(scope=message)[self.header_name] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as error:
            self._log(scope, 500, started, error=type(error).__name__)
            raise
        else:
            self._log(scope, status["code"], started)
        finally:
            reset_request_id(token)

    def _log(
        self, scope: Scope, status_code: int, started: float, error: str | None = None
    ) -> None:
        # Пишем метод, путь и статус. Ни строки запроса, ни тела: там бывают
        # имена чужих фонограмм и подписанные ссылки
        # (docs/DELETION_AND_RETENTION_DESIGN.md, «Политика логирования»).
        payload: dict[str, Any] = {
            "event": "http_request",
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "status": status_code,
            "durationMs": round((time.perf_counter() - started) * 1000, 2),
        }
        if error:
            payload["error"] = error
        access_logger.info("Запрос обработан", extra=payload)


class _BodyTooLarge(Exception):
    """Внутренний сигнал: тело переросло лимит прямо во время чтения."""


class BodySizeLimitMiddleware:
    """Явный предел размера тела запроса.

    Без него слишком большой файл кладет процесс на память или рвет
    соединение, и пользователь видит не отказ, а сбой сети. Проверка идет в
    два приема: по объявленному Content-Length — до чтения тела, и по факту
    прочитанных байт — если длина не объявлена (chunked).
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "") in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        # Первый рубеж: объявленная длина. Отказ до чтения тела — самый
        # дешевый: гигабайт не поедет через сеть ради ответа 413.
        declared = Headers(scope=scope).get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            await self._reject(scope, send, received=int(declared))
            return

        # Второй рубеж: факт. Длину можно не объявлять (chunked) и соврать.

        # received — сколько байт тела прочитано; too_large — предел пройден;
        # started — вниз ушел ответ приложения; answered — мы ответили сами.
        state: dict[str, Any] = {
            "received": 0,
            "too_large": False,
            "started": False,
            "answered": False,
        }

        async def limited_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state["received"] += len(message.get("body", b""))
                if state["received"] > self.max_bytes:
                    state["too_large"] = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            if state["answered"]:
                # Свой отказ уже отправлен. Остатки ответа приложения глушим,
                # иначе они допишутся в тело нашего 413.
                return
            # Приложение не узнает, почему чтение тела оборвалось: FastAPI
            # ловит любую ошибку разбора тела и превращает ее в свой 400.
            # Поэтому подменяем ответ здесь, где причина известна.
            if state["too_large"] and not state["started"]:
                await self._reject_once(state, scope, send)
                return
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if state["started"]:
                # Ответ уже пошел клиенту, дописать в него отказ нельзя.
                raise
            await self._reject_once(state, scope, send)

    async def _reject_once(self, state: dict[str, Any], scope: Scope, send: Send) -> None:
        if state["answered"]:
            return
        state["answered"] = True
        await self._reject(scope, send, received=state["received"])

    async def _reject(self, scope: Scope, send: Send, *, received: int) -> None:
        response = error_response(
            413,
            "payload_too_large",
            f"Тело запроса больше допустимых {human_bytes(self.max_bytes)}.",
            details={"limitBytes": self.max_bytes, "receivedBytes": received},
        )
        access_logger.warning(
            "Тело запроса больше лимита",
            extra={
                "event": "body_limit_exceeded",
                "method": scope.get("method", ""),
                "path": scope.get("path", ""),
                "limitBytes": self.max_bytes,
                "receivedBytes": received,
            },
        )
        await response(scope, _empty_receive, send)


async def _empty_receive() -> Message:
    # Ответ формируем, не читая тело: клиент мог не дослать его до конца.
    return {"type": "http.disconnect"}


__all__ = [
    "BodySizeLimitMiddleware",
    "RequestContextMiddleware",
    "get_request_id",
    "human_bytes",
    "sanitize_request_id",
]
