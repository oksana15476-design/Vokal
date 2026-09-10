"""Проекты.

Проект создается из уже принятой загрузки, а не вместе с файлом: файл идет в
хранилище отдельным запросом, и связывать две долгие операции в одну — значит
терять обе при обрыве.

Согласие приходит здесь же и вместе с версией формулировки. Это не
формальность: без версии запись «согласие получено» остается без предмета, и
восстановить ее задним числом нечем.

Логика живет в `app/services/projects.py`, роутер только переводит ее отказы в
коды HTTP. Что здесь работает по-настоящему: создание, список, карточка
целиком, переименование, демо-проекты.

`501` остается там, где нет швов, а не там, где не дописан код: сессия базы и
владелец запроса в `app/api/deps.py` пока заглушки (`None`). Без них нельзя ни
записать строку, ни проверить, чья это песня. Ответ говорит это дословно.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import PageDep, ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.enums import JobStatus, Scenario
from app.api.schemas.jobs import ProcessingJobOut
from app.api.schemas.projects import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectOut,
    ProjectPatchRequest,
)
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import jobs as jobs_service
from app.services import projects as service

router = APIRouter(prefix="/projects", tags=["проекты"])

WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)

DEMO_MISSING = ("демо-данные в базе: python -m app.db.seed",)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    """Швы, без которых работа с песнями невозможна честно."""
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Работа с песнями не включена: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


async def _processing_of(repos: Repositories, project: Any) -> Any:
    """Состояние обработки для карточки песни.

    `ProjectOut.processing` обязателен по контракту, а задания может не быть
    вовсе: песня создана, обработку никто не запускал. Идентификатор в этом
    случае пустой — придумывать идентификатор несуществующего задания нельзя,
    по нему клиент пойдет спрашивать статус и получит `404`.
    """
    job = await jobs_service.latest_job(repos, project.id)
    if job is None:
        return ProcessingJobOut(
            id="",
            project_id=str(project.id),
            status=JobStatus.QUEUED,
            steps=[],
            warnings=[],
            progress_percent=0,
            retry_count=0,
        )
    return jobs_service.job_out(job, await jobs_service.steps_of(repos, job))


@router.post(
    "",
    response_model=ProjectOut,
    status_code=201,
    summary="Создать проект из загрузки",
    description=(
        "Сценарий, цель и типизированная настройка обязаны сойтись между собой. "
        "Согласие принимается только с известной сервером версией формулировки."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def create_project(
    payload: ProjectCreateRequest,
    session: SessionDep,
    user_id: UserDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description=(
                "Ключ повтора. Повторный запрос с тем же ключом не создает второй проект: "
                "обрыв связи на ответе не должен превращаться в дубль."
            ),
        ),
    ] = None,
) -> Response | ProjectOut:
    blocked = _not_wired("POST /api/projects", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        upload, holder = await service.holder_for_upload(
            repos, upload_id=payload.upload_id, user_id=str(user_id)
        )
        project = await service.create_project(
            repos,
            upload=upload,
            holder=holder,
            payload=payload,
            now=datetime.now(UTC),
        )
        bundle = await service.load_bundle(repos, project)
        return service.project_out(bundle, await _processing_of(repos, project))
    except service.ProjectRefusal as error:
        return _refusal(error)


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="Список проектов",
    description="Сверху то, что открывали последним: список песен читается сверху вниз.",
    responses=errors(401, 422, 501),
)
async def list_projects(
    page: PageDep,
    session: SessionDep,
    user_id: UserDep,
    scenario: Annotated[Scenario | None, Query(description="Отбор по сценарию")] = None,
    search: Annotated[
        str | None, Query(max_length=200, description="Поиск по названию проекта")
    ] = None,
) -> Response | ProjectListResponse:
    blocked = _not_wired("GET /api/projects", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        owner = service.owner_id(str(user_id))
        items, total = await service.list_projects(
            repos,
            user_id=owner,
            limit=page.limit,
            offset=page.offset,
            scenario=scenario,
            search=search,
        )
        jobs = await jobs_service.latest_jobs_for_projects(repos, [item.id for item in items])
        summaries = []
        for project in items:
            found = jobs.get(project.id)
            summaries.append(
                service.project_summary(
                    project,
                    await service.source_upload(repos, project),
                    jobs_service.job_out(*found) if found else None,
                )
            )
    except service.ProjectRefusal as error:
        return _refusal(error)

    return ProjectListResponse(items=summaries, total=total, limit=page.limit, offset=page.offset)


@router.get(
    "/demo",
    response_model=list[ProjectOut],
    summary="Демо-проекты",
    description=(
        "Три подготовленные песни для знакомства с продуктом. Разбор у них есть, "
        "потому что он сделан заранее: `analysisSource = demo`. Своего файла за ними нет."
    ),
    responses=errors(401, 501),
)
async def read_demo_projects(
    session: SessionDep,
    user_id: UserDep,
) -> Response | list[ProjectOut]:
    blocked = _not_wired("GET /api/projects/demo", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    found = await service.demo_projects(repos)
    if not found:
        # Пустой список читался бы как «демо кончились». Их не кончилось, их
        # не залили: это состояние установки, и говорить о нем надо прямо.
        return not_implemented(
            endpoint="GET /api/projects/demo",
            message="Демо-проектов нет в базе: их еще не залили.",
            missing=DEMO_MISSING,
        )

    try:
        return [
            service.project_out(
                await service.load_bundle(repos, project),
                await _processing_of(repos, project),
            )
            for project in found
        ]
    except service.ProjectRefusal as error:
        return _refusal(error)


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Проект целиком",
    description="Карточка со всем, что показывает экран: разбор, материалы, версии, выдача.",
    responses=errors(401, 403, 404, 501),
)
async def read_project(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ProjectOut:
    blocked = _not_wired("GET /api/projects/{project_id}", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await service.owned_project(repos, service.entity_id(project_id), str(user_id))
        # Открыли — значит открыли. Порядок списка песен строится по этой
        # отметке, и не обновлять ее здесь значит сортировать список по
        # времени создания, притворяясь, что это время последнего открытия.
        project = await repos.projects.touch_opened(project.id)
        bundle = await service.load_bundle(repos, project)
        return service.project_out(bundle, await _processing_of(repos, project))
    except service.ProjectRefusal as error:
        return _refusal(error)


@router.patch(
    "/{project_id}",
    response_model=ProjectOut,
    summary="Переименовать проект",
    responses=errors(401, 403, 404, 422, 501),
)
async def patch_project(
    project_id: ProjectIdPath,
    payload: ProjectPatchRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response | ProjectOut:
    blocked = _not_wired("PATCH /api/projects/{project_id}", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await service.owned_project(repos, service.entity_id(project_id), str(user_id))
        project = await service.rename_project(repos, project, payload.name)
        bundle = await service.load_bundle(repos, project)
        return service.project_out(bundle, await _processing_of(repos, project))
    except service.ProjectRefusal as error:
        return _refusal(error)
