"""Сборка роутеров API.

Одно место подключения на весь API. Приложение подключает его так:

    from app.api.router import API_PREFIX, api_router
    app.include_router(api_router, prefix=API_PREFIX)

Префикс объявлен здесь константой, а не строкой по месту вызова. Причина
простая: адреса, по которым живет фронтенд, не должны зависеть от того, какое
из приложений собрало роутер. Сам `api_router` собственного префикса не несет,
и роутеры внутри тоже — `/api` добавляется ровно один раз, при подключении.

Порядок подключения значим. `projects` объявляет `/projects/{project_id}` и
идет последним: роутеры с постоянными сегментами внутри проекта
(`/projects/{project_id}/versions`, `/delete-source` и прочие) должны быть
объявлены раньше, иначе постоянный сегмент рискует совпасть с шаблоном
идентификатора. FastAPI разбирает маршруты по первому совпадению.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    consent,
    deletion,
    director,
    jobs,
    projects,
    review,
    sharing,
    stage_pack,
    uploads,
    versions,
)

# Внешний префикс API. Сюда он вынесен, чтобы приложения не выписывали его
# строкой каждое у себя. `app/api/contract_app.py` пока объявляет свою такую же
# константу — его зона чужая, и правка туда описана отдельно. Разойтись молча
# они не смогут: `tests/test_app_wiring.py` сверяет пути боевого приложения
# с выгруженной схемой `docs/api/openapi.json`.
API_PREFIX = "/api"

api_router = APIRouter()

api_router.include_router(consent.router)
api_router.include_router(uploads.router)
api_router.include_router(jobs.router)
api_router.include_router(stage_pack.router)
api_router.include_router(director.router)
api_router.include_router(versions.router)
api_router.include_router(review.router)
api_router.include_router(sharing.router)
api_router.include_router(deletion.router)
api_router.include_router(projects.router)
