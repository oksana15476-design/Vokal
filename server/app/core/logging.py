"""Структурные логи: одна строка — один JSON-объект.

Формат нужен не ради моды: разбор жалобы на обработку начинается с
идентификатора запроса, а грепать по нему человекочитаемый текст с
переносами строк невозможно. Идентификатор подставляется автоматически из
контекста, чтобы его нельзя было забыть передать.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.context import get_request_id

LOGGER_NAME = "vokal"

# Служебные поля LogRecord считаем один раз: все остальное, что положили в
# extra, уезжает в JSON как поля события. color_message добавлен к
# служебным: uvicorn кладет туда тот же текст с ANSI-кодами.
_RESERVED = frozenset(
    vars(logging.LogRecord(name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None))
) | {"message", "asctime", "taskName", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = get_request_id()
        if request_id:
            payload["requestId"] = request_id

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # ensure_ascii=False — иначе русский текст в логах превращается в
        # \u-последовательности и перестает искаться грепом.
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.set_name("vokal-json")

    root = logging.getLogger()
    # Снимаем только свой прошлый обработчик. Чужие (например, перехват
    # pytest) не трогаем: сборка приложения не должна ломать чужие тесты.
    for existing in list(root.handlers):
        if existing.get_name() == "vokal-json":
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Чужой logging.config.fileConfig по умолчанию идет с
    # disable_existing_loggers=True и гасит все логгеры, которых нет в его
    # конфигурации. Так делает alembic (migrations/env.py), и после прогона
    # миграций в том же процессе наши логи молчат. Молчащий лог замечают не
    # при выкладке, а в разборе инцидента, поэтому включаем свои явно.
    for existing_name, existing_logger in logging.root.manager.loggerDict.items():
        if existing_name == LOGGER_NAME or existing_name.startswith(f"{LOGGER_NAME}."):
            if isinstance(existing_logger, logging.Logger):
                existing_logger.disabled = False
    logging.getLogger(LOGGER_NAME).disabled = False

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # Свой лог доступа уже есть в middleware и знает про идентификатор запроса.
    # Штатный лог uvicorn дал бы вторую строку в другом формате.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False


def get_logger(suffix: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}")
