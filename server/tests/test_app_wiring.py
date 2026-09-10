"""Тесты связки приложения: боевая фабрика и единый движок базы.

Зачем отдельный файл. Контракт API до сих пор проверялся на
`build_contract_app()` — параллельном приложении, которое подключает роутер
само. Прогон оставался зеленым ровно тогда, когда в боевой фабрике подключение
роутера было закомментировано, а `uvicorn app.main:create_app --factory`
отвечал на любой `/api/...` кодом 404. Тест, который ходит мимо `main.py`,
такой дефект не видит по построению.

Поэтому здесь приложение поднимается **только** публичной фабрикой
`app.main.create_app` — той же, что и в боевом запуске.

Вторая половина файла про движок базы: строка подключения обязана читаться в
одном месте. Проба готовности `/ready` и единица работы, смотрящие в разные
базы, дают худший вид отказа — процесс отчитывается готовым и падает на первом
же запросе к данным.

База данных этим тестам не нужна: адрес подключения заведомо мертвый, ни один
из проверяемых маршрутов в базу не ходит, а создание движка соединений не
открывает.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routes as routes_package
from app.core import config
from app.core.db import create_probe_engine
from app.db.session import get_engine, get_session_factory, reset_engine_cache
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_FILE = REPO_ROOT / "docs" / "api" / "openapi.json"

API_PREFIX = "/api"

# Порт, на котором заведомо никто не слушает: маршруты проверяются без базы.
DEAD_DATABASE_URL = "postgresql+asyncpg://nobody@127.0.0.1:59321/nowhere"
OTHER_DATABASE_URL = "postgresql+asyncpg://nobody@127.0.0.1:59322/elsewhere"

# Тем же именем переменную подставляют площадки, и тем же способом ее пишут
# люди. Обе формы обязаны приводить к одному и тому же движку.
PLATFORM_DSN = "postgresql://nobody@127.0.0.1:59321/nowhere"


@pytest.fixture(autouse=True)
def _clean_process_caches() -> Iterator[None]:
    """Настройки и движок кешируются на процесс, а тесты меняют окружение."""
    config.get_settings.cache_clear()
    reset_engine_cache()
    yield
    config.get_settings.cache_clear()
    reset_engine_cache()


def build_production_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    database_url: str = DEAD_DATABASE_URL,
) -> FastAPI:
    """Ровно то приложение, которое поднимает боевой запуск."""
    monkeypatch.setenv("VOKAL_DATABASE_URL", database_url)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.get_settings.cache_clear()
    return create_app()


def served_paths(app: FastAPI) -> set[str]:
    """Пути, которые приложение действительно объявляет.

    Через схему, а не через `app.routes`: FastAPI подключает роутер отложенно
    и до первого запроса держит в `routes` служебный узел без пути.
    """
    return set(app.openapi()["paths"])


def paths_by_router_module() -> dict[str, set[str]]:
    """Что обязан отдавать каждый роутер из `app/api/router.py`, с префиксом."""
    result: dict[str, set[str]] = {}
    for info in pkgutil.iter_modules(routes_package.__path__):
        module = importlib.import_module(f"{routes_package.__name__}.{info.name}")
        router = getattr(module, "router", None)
        if router is None:
            continue
        result[info.name] = {API_PREFIX + route.path for route in router.routes}
    return result


# --- Подключение роутеров к боевому приложению --------------------------


def test_real_endpoint_answers_through_production_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Главная проверка батча: `/api/...` живет там же, где `/health`."""
    with TestClient(build_production_app(monkeypatch)) as client:
        response = client.get("/api/consent/current")

    assert response.status_code != 404, (
        "боевая фабрика не подключила api_router: /api/... отвечает 404, "
        "хотя тесты контракта зеленые — они ходят мимо app/main.py"
    )
    assert response.status_code == 200
    assert response.json()["id"]


def test_production_app_serves_paths_of_every_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Подключен весь `api_router`, а не отдельный роутер."""
    served = served_paths(build_production_app(monkeypatch))

    expected = paths_by_router_module()
    assert expected, "не найдено ни одного модуля роутеров — проверять нечего"

    missing = {
        module: sorted(paths - served) for module, paths in expected.items() if paths - served
    }
    assert not missing, f"боевое приложение не отдает пути роутеров: {missing}"


def test_production_paths_match_published_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пути боевого приложения совпадают со схемой, по которой живет фронтенд."""
    served = {
        path
        for path in served_paths(build_production_app(monkeypatch))
        if path.startswith(API_PREFIX)
    }
    published = set(json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))["paths"])

    assert served == published, (
        "расхождение с docs/api/openapi.json: "
        f"лишние {sorted(served - published)}, отсутствуют {sorted(published - served)}"
    )


def test_api_prefix_is_not_doubled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Роутеры несут свои префиксы, приложение добавляет `/api` один раз."""
    app = build_production_app(monkeypatch)

    doubled = sorted(path for path in served_paths(app) if path.startswith("/api/api"))
    assert not doubled, f"префикс /api задвоен: {doubled}"

    with TestClient(app) as client:
        assert client.get("/api/api/consent/current").status_code == 404


def test_service_routes_survive_router_mount(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подключение роутеров не должно перекрывать служебные адреса."""
    with TestClient(build_production_app(monkeypatch)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_api_path_still_answers_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Несуществующий адрес под `/api` отвечает общим конвертом ошибки."""
    with TestClient(build_production_app(monkeypatch)) as client:
        response = client.get("/api/no-such-route", headers={"X-Request-ID": "rid-404"})

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["requestId"] == "rid-404"


# --- Один движок базы на процесс ----------------------------------------


def test_engine_is_created_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный вызов геттера отдает тот же объект, а не новый пул."""
    monkeypatch.setenv("VOKAL_DATABASE_URL", DEAD_DATABASE_URL)

    assert get_engine() is get_engine()


def test_session_factory_is_bound_to_the_single_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Фабрика сессий одна и сидит на том же движке."""
    monkeypatch.setenv("VOKAL_DATABASE_URL", DEAD_DATABASE_URL)

    factory = get_session_factory()

    assert get_session_factory() is factory
    assert factory.kw["bind"] is get_engine()


def test_reset_engine_cache_lets_process_change_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сброс кеша существует ради тестов и скриптов и обязан работать."""
    monkeypatch.setenv("VOKAL_DATABASE_URL", DEAD_DATABASE_URL)
    first = get_engine()

    monkeypatch.setenv("VOKAL_DATABASE_URL", OTHER_DATABASE_URL)
    config.get_settings.cache_clear()
    reset_engine_cache()
    second = get_engine()

    assert second is not first
    assert str(second.url) != str(first.url)


def test_probe_engine_and_session_engine_share_one_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Проба `/ready` и единица работы смотрят в одну базу.

    Переменная задана так, как ее подставляют площадки: имя `DATABASE_URL` и
    схема `postgresql://`. Пока строку читали в двух местах, проба видела
    нормализованный адрес, а единица работы не видела переменную вовсе —
    процесс отчитывался готовым и падал на первом обращении к данным.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOKAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", PLATFORM_DSN)
    config.get_settings.cache_clear()
    reset_engine_cache()

    probe = create_probe_engine(config.get_settings())

    assert str(get_engine().url) == str(probe.url)
    assert get_engine().url.drivername == "postgresql+asyncpg"


def test_missing_database_url_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Без адреса базы движок не создается, а не подключается куда-то молча."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOKAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.get_settings.cache_clear()
    reset_engine_cache()

    with pytest.raises(RuntimeError) as error:
        get_engine()

    assert "database_url" in str(error.value).lower()
    assert ".env.example" in str(error.value)
