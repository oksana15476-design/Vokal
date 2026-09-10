"""AI-директор: предложения, действия, разговор.

Действие приходит кодом из закрытого списка, а не текстом. Незнакомый код —
отказ, а не попытка угадать: музыкальные изменения применяет детерминированный
слой, LLM только объясняет и выбирает действие.

Отдельный адрес для пакета действий существует ради истории версий. Пять
действий по одному дадут пять версий и пять пересборок материалов; те же пять
действий пакетом дают одну версию с перечнем изменений.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import SessionDep, UserDep
from app.api.not_implemented import not_implemented
from app.api.responses import errors
from app.api.schemas.director import (
    DirectorActionBatchRequest,
    DirectorActionRequest,
    DirectorActionResponse,
    DirectorChatRequest,
    DirectorChatResponse,
    DirectorSuggestionListResponse,
)

router = APIRouter(prefix="/projects/{project_id}/director", tags=["директор"])

ProjectIdPath = Annotated[str, Path(min_length=1, max_length=64, description="Идентификатор проекта")]

ARRANGEMENT_MISSING = (
    "Arrangement Engine: правила применения действий",
    "Version Engine: создание версий и пересборка материалов",
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
    return not_implemented(
        endpoint="GET /api/projects/{project_id}/director/suggestions",
        message="Предложений нет: разбора песни, на котором они строятся, еще нет.",
        missing=("разбор песни (SongGraph)", *ARRANGEMENT_MISSING),
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
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/director/actions",
        message="Действия директора не выполняются: аранжировку пока некому менять.",
        missing=ARRANGEMENT_MISSING,
    )


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
) -> Response:
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/director/actions/batch",
        message="Действия директора не выполняются: аранжировку пока некому менять.",
        missing=ARRANGEMENT_MISSING,
    )


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
    return not_implemented(
        endpoint="POST /api/projects/{project_id}/director/chat",
        message="Разговор с директором не работает: LLM-адаптер не подключен.",
        missing=("адаптер LLM-провайдера", *ARRANGEMENT_MISSING),
    )
