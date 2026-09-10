"""Сборка роутеров API.

Одно место подключения на весь API. Приложение подключает его так:

    from app.api.router import api_router
    app.include_router(api_router, prefix="/api")

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
