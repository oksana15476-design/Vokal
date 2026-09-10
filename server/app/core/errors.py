"""Единая модель ошибки для всего API.

Одна форма ответа на любую ошибку: машинный код для ветвления на фронтенде,
человеческий текст для показа и идентификатор запроса, по которому
поддержка находит след в логах. Разные формы ошибок у разных обработчиков —
это гарантированный разнобой в интерфейсе.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import get_request_id, request_id_from_scope
from app.core.logging import get_logger

logger = get_logger("errors")

CODE_BY_STATUS: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

# Тексты временные: любой пользовательский текст проходит связку копирайтер —
# главред (CLAUDE.md). До этой правки формулировки держим нейтральными и без
# обещаний сроков и результата.
MESSAGE_BY_STATUS: dict[int, str] = {
    400: "Запрос составлен неверно.",
    401: "Нужен вход в аккаунт.",
    403: "Доступ к этому объекту закрыт.",
    404: "Ресурс не найден.",
    405: "Такой метод для этого адреса не поддерживается.",
    409: "Объект изменился: обновите данные и повторите.",
    413: "Тело запроса слишком большое.",
    415: "Формат содержимого не поддерживается.",
    422: "Данные запроса не прошли проверку.",
    429: "Слишком много запросов подряд.",
    500: "Внутренняя ошибка сервиса.",
    503: "Сервис временно недоступен.",
}


def build_error_payload(
    code: str,
    message: str,
    *,
    details: Any = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "requestId": request_id if request_id is not None else get_request_id(),
            "details": details,
        }
    }


def error_response(
    status_code: int,
    code: str | None = None,
    message: str | None = None,
    *,
    details: Any = None,
    headers: dict[str, str] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    resolved_code = code or CODE_BY_STATUS.get(status_code, "error")
    resolved_message = message or MESSAGE_BY_STATUS.get(status_code, "Ошибка обработки запроса.")
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(
            resolved_code, resolved_message, details=details, request_id=request_id
        ),
        headers=headers,
    )


def resolve_request_id(request: Request) -> str | None:
    """Сначала scope, потом contextvar.

    Ответ 500 собирается снаружи нашего слоя контекста, когда contextvar уже
    сброшен. Без запасного источника у самых важных ошибок не было бы
    идентификатора — ровно у тех, с которыми приходят в поддержку.
    """
    return request_id_from_scope(request.scope) or get_request_id()


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code: str | None = None
    message: str | None = None
    details: Any = None

    # Роутеры могут кидать HTTPException с готовым кодом:
    # raise HTTPException(409, {"code": "version_conflict", "message": "..."}).
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code")
        message = exc.detail.get("message")
        details = exc.detail.get("details")
    elif isinstance(exc.detail, str) and exc.detail and not _is_default_detail(exc):
        # Тексты Starlette по умолчанию английские ("Not Found"): такие
        # подменяем своими, а осмысленный текст роутера оставляем.
        message = exc.detail

    if not message:
        message = MESSAGE_BY_STATUS.get(exc.status_code)

    return error_response(
        exc.status_code,
        code,
        message,
        details=details,
        headers=getattr(exc, "headers", None),
        request_id=resolve_request_id(request),
    )


def _is_default_detail(exc: StarletteHTTPException) -> bool:
    try:
        return exc.detail == HTTPStatus(exc.status_code).phrase
    except ValueError:
        return False


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Из подробностей убрано поле input: там лежит то, что прислал пользователь,
    # а тело запроса наружу и в логи не возвращается
    # (docs/DELETION_AND_RETENTION_DESIGN.md, «Политика логирования»).
    fields = [
        {
            "field": ".".join(str(part) for part in item.get("loc", ())),
            "reason": item.get("msg", ""),
        }
        for item in exc.errors()
    ]
    return error_response(
        422,
        "validation_error",
        details={"fields": fields},
        request_id=resolve_request_id(request),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Тип и текст исключения остаются в логе рядом с requestId. Наружу уходит
    # только код: сообщения исключений регулярно содержат куски конфигурации.
    logger.exception(
        "Необработанное исключение",
        extra={
            "event": "unhandled_exception",
            "method": request.method,
            "path": request.url.path,
            "error": type(exc).__name__,
        },
    )
    return error_response(500, "internal_error", request_id=resolve_request_id(request))


def register_error_handlers(app: Any) -> None:
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
