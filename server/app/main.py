"""Сборка приложения FastAPI.

Приложение собирается фабрикой, а не создается на уровне модуля: импорт
модуля не должен читать окружение, иначе тесты не смогут собрать приложение
с другими настройками, а любая ошибка конфигурации будет падать на импорте.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import API_PREFIX, api_router
from app.core.config import Settings, get_settings
from app.core.db import check_database, create_probe_engine
from app.core.errors import error_response, register_error_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import BodySizeLimitMiddleware, RequestContextMiddleware

logger = get_logger("app")


def _service_version() -> str:
    try:
        return version("vokal-server")
    except PackageNotFoundError:
        # Пакет не установлен (например, запуск из исходников). Врать номером
        # версии нельзя: пишем прямо, что версия неизвестна.
        return "unknown"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)
    service_version = _service_version()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.settings = settings
        application.state.db_probe_engine = create_probe_engine(settings)
        logger.info(
            "Сервис запущен",
            extra={"event": "startup", "env": settings.app_env, "version": service_version},
        )
        try:
            yield
        finally:
            await application.state.db_probe_engine.dispose()
            logger.info("Сервис остановлен", extra={"event": "shutdown"})

    app = FastAPI(
        title="Vokal Director API",
        version=service_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        default_response_class=JSONResponse,
    )

    # Порядок важен. Слой, добавленный последним, оборачивает остальные:
    # 1. RequestContext — снаружи всех, иначе у части ответов не будет
    #    идентификатора запроса и строки в логе доступа;
    # 2. CORS — выше лимита тела, иначе браузер покажет отказ 413 как сетевую
    #    ошибку и наш текст до пользователя не дойдет;
    # 3. BodySizeLimit — ближе всех к обработчику, вмешивается в чтение тела.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[settings.request_id_header],
    )
    app.add_middleware(RequestContextMiddleware, header_name=settings.request_id_header)

    register_error_handlers(app)

    @app.get("/health", tags=["служебные"], summary="Живость процесса")
    async def health() -> dict[str, str]:
        """Отвечает, пока жив процесс.

        Намеренно не трогает базу: если живость завязать на внешнюю
        зависимость, оркестратор будет перезапускать здоровый процесс из-за
        недоступной базы и лечить не то место.
        """
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": service_version,
        }

    # response_model=None: обработчик отдает либо словарь готовности, либо
    # готовый JSONResponse с ошибкой, и вывести из аннотации одну схему нельзя.
    @app.get(
        "/ready",
        tags=["служебные"],
        summary="Готовность принимать запросы",
        response_model=None,
    )
    async def ready(request: Request) -> JSONResponse | dict[str, object]:
        """Готовность подтверждается запросом в базу, а не константой."""
        check = await check_database(
            request.app.state.db_probe_engine,
            timeout=settings.db_check_timeout_seconds,
            dsn=settings.database_url,
        )
        database = {
            "status": "ok" if check.ok else "error",
            "latencyMs": check.latency_ms,
        }
        if not check.ok:
            database["error"] = check.error
            return error_response(
                503,
                "not_ready",
                "Сервис не готов принимать запросы: база данных недоступна.",
                details={"checks": {"database": database}},
            )
        return {
            "status": "ready",
            "service": settings.app_name,
            "version": service_version,
            "checks": {"database": database},
        }

    # --- Роутеры API -----------------------------------------------------
    # Префикс не выписан строкой по месту, а взят из `app/api/router.py`: там
    # он объявлен один раз. Сами роутеры несут собственные `/consent`,
    # `/uploads`, `/projects`, и `/api` внутри них не повторяется — иначе
    # адреса стали бы `/api/api/...`.
    #
    # Подключение идет после служебных адресов, но перекрыть их не может:
    # все пути роутера лежат под `/api`, а `/health` и `/ready` — нет.
    #
    # Что за этими адресами есть на самом деле: настоящий ответ дают только
    # версии согласия и ограничения загрузки. Остальные отвечают `501` с
    # разбором в `details.missing` — заглушек, изображающих готовность,
    # в API нет намеренно.
    app.include_router(api_router, prefix=API_PREFIX)

    return app
