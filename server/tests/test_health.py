"""Тесты каркаса: живость, готовность, единая ошибка, лимит тела, логи.

Почему все в одном файле: зона батча «каркас» — ровно этот путь. Разделение
по файлам сделает следующий батч, когда появятся роутеры API.
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core import config
from app.core.logging import LOGGER_NAME, JsonFormatter
from app.main import create_app

# Порт, на котором заведомо никто не слушает. Нужен, чтобы проверить: /ready
# действительно ходит в базу, а не отвечает «готов» по константе.
DEAD_DATABASE_URL = "postgresql+asyncpg://nobody@127.0.0.1:59321/nowhere"

# Живая база подставляется снаружи. Если переменной нет — тест готовности
# пропускается с внятным сообщением, а не тихо считается пройденным.
LIVE_DATABASE_URL = os.environ.get("VOKAL_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Настройки кешируются на процесс, а тесты меняют окружение."""
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def tmp_dir_without_env() -> str:
    """Каталог без .env: иначе настройки подхватят локальный файл разработчика."""
    return tempfile.mkdtemp(prefix="vokal-no-env-")


def build_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_url: str = DEAD_DATABASE_URL,
    **env: str,
) -> FastAPI:
    monkeypatch.setenv("VOKAL_DATABASE_URL", database_url)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    return create_app()


# --- Живость ------------------------------------------------------------


def test_health_alive_when_database_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """Живость не зависит от базы: иначе оркестратор перезапустит живой процесс."""
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"]
    assert "version" in body


def test_health_returns_request_id_header(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/health")

    assert response.headers.get("X-Request-ID")


def test_request_id_is_taken_from_incoming_header(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/health", headers={"X-Request-ID": "rid-from-gateway-1"})

    assert response.headers["X-Request-ID"] == "rid-from-gateway-1"


def test_dirty_request_id_is_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Заголовок приходит снаружи и попадает в логи: мусор в него не пускаем."""
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/health", headers={"X-Request-ID": 'rid " with spaces'})

    assert response.headers["X-Request-ID"] != 'rid " with spaces'
    assert response.headers["X-Request-ID"]


# --- Готовность ---------------------------------------------------------


def test_ready_reports_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """База недоступна — значит не готовы. Проверка настоящая, а не константа."""
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/ready", headers={"X-Request-ID": "rid-ready-down"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "not_ready"
    assert body["error"]["requestId"] == "rid-ready-down"
    assert body["error"]["details"]["checks"]["database"]["status"] == "error"
    assert body["error"]["details"]["checks"]["database"]["error"]


def test_ready_does_not_leak_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = "postgresql+asyncpg://user:sup3rsecret@127.0.0.1:59321/nowhere"
    with TestClient(build_app(monkeypatch, database_url=dsn)) as client:
        response = client.get("/ready")

    assert "sup3rsecret" not in response.text


@pytest.mark.skipif(
    not LIVE_DATABASE_URL,
    reason="нет VOKAL_TEST_DATABASE_URL: живую базу проверить нечем",
)
def test_ready_ok_with_live_database(monkeypatch: pytest.MonkeyPatch) -> None:
    assert LIVE_DATABASE_URL is not None
    with TestClient(build_app(monkeypatch, database_url=LIVE_DATABASE_URL)) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["status"] == "ok"
    assert body["checks"]["database"]["latencyMs"] >= 0


# --- Единая модель ошибки ----------------------------------------------


def test_unknown_route_uses_error_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Неизвестный адрес отвечает 404 в общей модели ошибки.

    Пример адреса менялся. Раньше здесь стоял `/api/projects` — он и правда
    был неизвестен, пока роутер не подключался в `app/main.py`. После
    подключения адрес стал настоящим и начал честно отвечать `501`, а тест
    покраснел, хотя проверяемое им поведение не менялось. Теперь берется
    адрес, которого нет ни в одном роутере, — тогда проверка переживет
    появление новых ручек.
    """
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/api/такого-адреса-нет", headers={"X-Request-ID": "rid-404"})

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert body["error"]["requestId"] == "rid-404"


def test_unhandled_exception_hides_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Наружу — код и request id. Внутренности остаются в логах."""
    app = build_app(monkeypatch)

    @app.get("/tests/boom")
    def boom() -> None:
        raise ValueError("пароль от базы в тексте исключения")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/tests/boom", headers={"X-Request-ID": "rid-500"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["requestId"] == "rid-500"
    assert "пароль" not in response.text
    assert "ValueError" not in response.text


def test_validation_error_uses_error_model(monkeypatch: pytest.MonkeyPatch) -> None:
    app = build_app(monkeypatch)

    @app.get("/tests/typed")
    def typed(count: int) -> dict[str, int]:
        return {"count": count}

    with TestClient(app) as client:
        response = client.get("/tests/typed", params={"count": "не число"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["requestId"]


def test_router_can_set_its_own_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Контракт для батча роутеров: свой код и текст в HTTPException."""
    app = build_app(monkeypatch)

    @app.get("/tests/conflict")
    def conflict() -> None:
        raise HTTPException(
            status_code=409,
            detail={"code": "version_conflict", "message": "Версия уже изменилась."},
        )

    with TestClient(app) as client:
        response = client.get("/tests/conflict")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "version_conflict"
    assert body["error"]["message"] == "Версия уже изменилась."
    assert body["error"]["requestId"]


def test_missing_database_url_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без адреса базы процесс не поднимается и говорит, чего не хватает."""
    monkeypatch.delenv("VOKAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_dir_without_env())
    config.get_settings.cache_clear()

    with pytest.raises(config.ConfigurationError) as error:
        config.get_settings()

    assert "VOKAL_DATABASE_URL" in str(error.value) or "database_url" in str(error.value)
    assert ".env.example" in str(error.value)


# --- Лимит размера тела -------------------------------------------------


def _app_with_echo(monkeypatch: pytest.MonkeyPatch, limit_bytes: int) -> FastAPI:
    app = build_app(monkeypatch, VOKAL_MAX_REQUEST_BODY_BYTES=str(limit_bytes))

    @app.post("/tests/echo")
    async def echo(payload: dict) -> dict:
        return {"received": len(payload.get("data", ""))}

    return app


def test_body_over_limit_returns_readable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_echo(monkeypatch, 1024)
    with TestClient(app) as client:
        response = client.post(
            "/tests/echo",
            json={"data": "x" * 4096},
            headers={"X-Request-ID": "rid-413"},
        )

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "payload_too_large"
    assert body["error"]["requestId"] == "rid-413"
    assert "1 КБ" in body["error"]["message"]
    assert body["error"]["details"]["limitBytes"] == 1024


def test_body_within_limit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app_with_echo(monkeypatch, 4096)
    with TestClient(app) as client:
        response = client.post("/tests/echo", json={"data": "x" * 100})

    assert response.status_code == 200
    assert response.json() == {"received": 100}


def test_body_over_limit_without_content_length(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без Content-Length лимит считается по факту прочитанных байт."""
    app = _app_with_echo(monkeypatch, 1024)

    def chunks() -> Iterator[bytes]:
        for _ in range(8):
            yield b"x" * 512

    with TestClient(app) as client:
        response = client.post(
            "/tests/echo",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_limit_error_carries_cors_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без заголовков CORS браузер покажет сетевую ошибку вместо нашего текста."""
    app = _app_with_echo(monkeypatch, 1024)
    with TestClient(app) as client:
        response = client.post(
            "/tests/echo",
            json={"data": "x" * 4096},
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


# --- CORS ---------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
)
def test_cors_allows_frontend_origins(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    with TestClient(build_app(monkeypatch)) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_rejects_foreign_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(build_app(monkeypatch)) as client:
        response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert response.headers.get("access-control-allow-origin") is None


# --- Структурные логи ---------------------------------------------------


def _capture_logs() -> tuple[io.StringIO, logging.Handler]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return stream, handler


def test_access_log_is_json_with_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    stream, handler = _capture_logs()
    try:
        with TestClient(build_app(monkeypatch)) as client:
            client.get("/health", headers={"X-Request-ID": "rid-log-1"})
    finally:
        logging.getLogger(LOGGER_NAME).removeHandler(handler)

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    access = [line for line in lines if line.get("event") == "http_request"]
    assert access, "нет записи доступа в логах"
    record = access[-1]
    assert record["requestId"] == "rid-log-1"
    assert record["method"] == "GET"
    assert record["path"] == "/health"
    assert record["status"] == 200
    assert record["durationMs"] >= 0
    assert record["level"] == "INFO"


def test_request_body_never_reaches_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Требование DELETION_AND_RETENTION_DESIGN: тело запроса не логируется."""
    stream, handler = _capture_logs()
    app = _app_with_echo(monkeypatch, 65536)
    try:
        with TestClient(app) as client:
            client.post("/tests/echo", json={"data": "очень-приватная-строка"})
    finally:
        logging.getLogger(LOGGER_NAME).removeHandler(handler)

    assert "очень-приватная-строка" not in stream.getvalue()


def test_logging_survives_alembic_file_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Прогон миграций в том же процессе не должен глушить наши логи.

    `fileConfig` из migrations/env.py идет с disable_existing_loggers=True, а в
    alembic.ini наших логгеров нет. Без починки в setup_logging лог доступа
    после миграций пропадает молча.
    """
    logging.getLogger(LOGGER_NAME).disabled = True
    logging.getLogger(f"{LOGGER_NAME}.access").disabled = True

    stream, handler = _capture_logs()
    try:
        with TestClient(build_app(monkeypatch)) as client:
            client.get("/health", headers={"X-Request-ID": "rid-after-alembic"})
    finally:
        logging.getLogger(LOGGER_NAME).removeHandler(handler)

    lines = [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]
    assert [line for line in lines if line.get("event") == "http_request"]
