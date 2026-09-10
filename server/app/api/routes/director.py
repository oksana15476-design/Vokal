"""AI-директор: предложения, действия, разговор.

Действие приходит кодом из закрытого списка, а не текстом. Незнакомый код —
отказ с перечнем поддерживаемых, а не попытка угадать: музыкальные изменения
применяет детерминированный слой (`app/services/director.py`), LLM только
объясняет и выбирает действие.

Отдельный адрес для пакета действий существует ради истории версий. Пять
действий по одному дадут пять версий и пять пересборок материалов; те же пять
действий пакетом дают одну версию с перечнем изменений.

Что здесь работает по-настоящему: применение действий. Предложения и разговор
отвечают `501` — и это не недоделка, а единственный честный ответ. Предложение
директора — утверждение о конкретной песне («в оригинале две гитары»), и взять
его без разбора песни неоткуда. Разговор требует разбора свободного текста,
которого в продукте нет; выполнять вместо непонятой команды похожую — прямо
запрещенное поведение.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response

from app.api.deps import ProjectIdPath, SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.director import (
    DirectorActionBatchRequest,
    DirectorActionRequest,
    DirectorActionResponse,
    DirectorActionResultOut,
    DirectorChatRequest,
    DirectorChatResponse,
    DirectorSuggestionListResponse,
)
from app.api.schemas.enums import ArtifactType, VersionKind
from app.core.errors import error_response
from app.db.repositories import Repositories
from app.services import director as service
from app.services import projects as projects_service

router = APIRouter(prefix="/projects/{project_id}/director", tags=["директор"])


#: Чего не хватает предложениям директора. Arrangement Engine здесь больше не
#: числится: правила применения действий уже есть. Не хватает именно разбора —
#: того, из чего предложение делает вывод про конкретную песню.
SUGGESTIONS_MISSING = (
    "разбор песни (SongGraph): предложение опирается на форму, партии и состав",
    "Confidence and Review Engine: без уверенности предложение не отличить от догадки",
)

CHAT_MISSING = (
    "адаптер LLM-провайдера",
    "разбор реплики в действие из закрытого списка",
)

WIRING_MISSING = (
    "единица работы базы (app/db/session.py, подключается через dependency_overrides)",
    "авторизация (app/api/deps.py: current_user_id)",
)


def _not_wired(endpoint: str, session: Any, user_id: str | None) -> Response | None:
    if session is None or user_id is None:
        return not_implemented(
            endpoint=endpoint,
            message="Действия директора не включены: нет единицы работы базы и входа в аккаунт.",
            missing=WIRING_MISSING,
        )
    return None


def _refusal(error: projects_service.ProjectRefusal) -> Response:
    return error_response(error.status_code, error.code, error.message, details=error.details)


def _response(outcome: service.ActionOutcome) -> DirectorActionResponse:
    return DirectorActionResponse(
        version=projects_service.version_out(
            outcome.version, current_version_id=outcome.version.id
        ),
        result=DirectorActionResultOut(
            version_label=outcome.version_label,
            version_kind=VersionKind(outcome.version_kind.value),
            history_title=outcome.history_title,
            changes=outcome.changes,
            stale_artifact_types=[
                ArtifactType(item.value) for item in outcome.stale_artifact_types
            ],
        ),
        applied_action_ids=outcome.applied,
    )


@router.get(
    "/suggestions",
    response_model=DirectorSuggestionListResponse,
    summary="Предложения директора",
    responses=errors(401, 403, 404, 501),
)
async def list_suggestions(
    project_id: ProjectIdPath,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    # Список предложений мог бы собраться из каталога действий — и это был бы
    # ровно тот муляж, который продукт запрещает. Предложение говорит не «что
    # умеет директор», а «что стоит сделать с этой песней»; без разбора такое
    # утверждение брать неоткуда.
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/director/suggestions",
        message="Предложений нет: разбора песни, на котором они строятся, еще нет.",
        missing=SUGGESTIONS_MISSING,
    )


@router.post(
    "/actions",
    response_model=DirectorActionResponse,
    status_code=201,
    summary="Выполнить одно действие директора",
    description="Создает новую версию аранжировки и помечает материалы, которые устарели.",
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def apply_action(
    project_id: ProjectIdPath,
    payload: DirectorActionRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response | DirectorActionResponse:
    blocked = _not_wired("POST /api/projects/{project_id}/director/actions", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        outcome = await service.apply_actions(
            repos,
            project,
            action_ids=[payload.action_id],
            base_version_id=payload.base_version_id,
            label=None,
            comment=payload.comment,
            now=datetime.now(UTC),
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return _response(outcome)


@router.post(
    "/actions/batch",
    response_model=DirectorActionResponse,
    status_code=201,
    summary="Собрать одну версию сразу из нескольких действий",
    description=(
        "Действия применяются в указанном порядке и дают одну версию с общим перечнем "
        "изменений, а не цепочку из промежуточных версий."
    ),
    responses=errors(401, 403, 404, 409, 422, 501),
)
async def apply_actions_batch(
    project_id: ProjectIdPath,
    payload: DirectorActionBatchRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response | DirectorActionResponse:
    blocked = _not_wired("POST /api/projects/{project_id}/director/actions/batch", session, user_id)
    if blocked is not None:
        return blocked

    repos = Repositories(session)
    try:
        project = await projects_service.owned_project(
            repos, projects_service.entity_id(project_id), str(user_id)
        )
        outcome = await service.apply_actions(
            repos,
            project,
            action_ids=payload.action_ids,
            base_version_id=payload.base_version_id,
            label=payload.label,
            comment=payload.comment,
            now=datetime.now(UTC),
        )
    except projects_service.ProjectRefusal as error:
        return _refusal(error)

    return _response(outcome)


@router.post(
    "/chat",
    response_model=DirectorChatResponse,
    summary="Реплика директору",
    description=(
        "Свободный текст превращается в действие из закрытого списка. Непонятая команда — "
        "честный ответ «не понял», а не выполнение похожего действия."
    ),
    responses=errors(401, 403, 404, 422, 429, 501),
)
async def chat(
    project_id: ProjectIdPath,
    payload: DirectorChatRequest,
    session: SessionDep,
    user_id: UserDep,
) -> Response:
    # Соблазн здесь — разобрать реплику по ключевым словам и назвать это
    # разговором с директором. Такой разбор угадывает: «сделай мощнее» попадет
    # в усиление припева, а «сделай мощнее бас» — туда же, хотя просили другое.
    # Пока разбора нет, отказ честнее.
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/director/chat",
        message="Разговор с директором не работает: разбирать реплику нечем.",
        missing=CHAT_MISSING,
    )
