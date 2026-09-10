"""Приложение, несущее только контракт API.

Зачем отдельно от `app/main.py`: боевое приложение поднимает настройки,
подключение к базе и слои посредников, а для контракта нужна ровно схема —
адреса, схемы запроса и ответа, коды ошибок. Это же приложение выгружает
`docs/api/openapi.json` и на нем же гоняются тесты контракта, поэтому
выгруженная схема и проверенная схема совпадают по построению.

Запуск выгрузки из каталога `server`:

    python -m app.api.contract_app > ../docs/api/openapi.json
"""

from __future__ import annotations

import json
import sys

from fastapi import FastAPI

from app.api.router import api_router
from app.core.errors import register_error_handlers

API_PREFIX = "/api"

DESCRIPTION = """
Контракт между фронтендом и сервером Vokal Director.

**Что здесь важно знать до чтения адресов.**

* Большая часть адресов отвечает `501`. Это не заготовка на будущее: схема
  запроса и ответа настоящая и полная, реализации за адресом еще нет. В
  `details.missing` сказано, чего именно не хватает. Заглушек, возвращающих
  правдоподобные данные, в API нет — мок в ответе сервера хуже отказа.
* Ошибка всегда выглядит одинаково: `{"error": {"code", "message",
  "requestId", "details"}}`.
* Имена полей — camelCase. Идентификаторы — непрозрачные строки.
* Незнакомое поле в теле запроса — ошибка `422`, а не тихо отброшенное
  значение.
"""


def build_contract_app() -> FastAPI:
    """Собирает приложение с одним лишь роутером API."""
    app = FastAPI(
        title="Vokal Director API",
        version="0.1.0",
        description=DESCRIPTION.strip(),
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )
    register_error_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


def main() -> None:
    schema = build_contract_app().openapi()
    # ensure_ascii=False: схема наполовину русская, и экранированные коды
    # сделали бы файл нечитаемым в ревью.
    json.dump(schema, sys.stdout, ensure_ascii=False, indent=2, sort_keys=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
