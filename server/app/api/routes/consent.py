"""Версии согласия.

Работает по-настоящему: реестр версий — это данные приложения, а не результат
обработки. Экран обязан показывать ровно тот текст, который потом уйдет на
сервер вместе с идентификатором версии, иначе запись «согласие получено» будет
свидетельствовать о том, чего пользователь не читал.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.consent_versions import ConsentVersion, consent_versions, current_consent
from app.api.schemas.consent import ConsentVersionListResponse, ConsentVersionOut

router = APIRouter(prefix="/consent", tags=["согласие"])


def _to_out(version: ConsentVersion) -> ConsentVersionOut:
    return ConsentVersionOut.model_validate(version, from_attributes=True)


@router.get(
    "/current",
    response_model=ConsentVersionOut,
    summary="Действующая версия согласия",
    description="Текст и идентификатор версии, которые нужно показать перед созданием проекта.",
)
async def read_current_consent() -> ConsentVersionOut:
    return _to_out(current_consent())


@router.get(
    "/versions",
    response_model=ConsentVersionListResponse,
    summary="Все версии согласия",
    description=(
        "От старых к новым. Старые версии не удаляются никогда: по ним читаются "
        "согласия, полученные раньше."
    ),
)
async def list_consent_versions() -> ConsentVersionListResponse:
    return ConsentVersionListResponse(
        items=[_to_out(version) for version in consent_versions],
        current_id=current_consent().id,
    )
