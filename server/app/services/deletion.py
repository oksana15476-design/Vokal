"""Удаление исходника и результатов.

Логика двух необратимых операций из `docs/DELETION_AND_RETENTION_DESIGN.md`.
Роутер только переводит отказы в коды HTTP, решения принимаются здесь.

Четыре правила, из которых выведено все остальное.

**Сначала хранилище, потом база.** Порядок не вкусовой. Если сперва пометить
строку, а потом не суметь снести объект, ключ уже стерт из базы (его обнуляет
`request_*_deletion`), и удалять станет нечего и некому: файл останется лежать
навсегда, а пользователю сказано «удалено». Обратный порядок в худшем случае
оставляет запись, которую можно повторить, — повтор идемпотентен.

**Удаление подтверждается, а не объявляется.** После `delete()` у хранилища
спрашивается `exists()`. Это не перестраховка: `DELETE` в S3-совместимом
хранилище с включенным версионированием создает delete-marker, объект остается
доступен по версии, а вызов отчитывается успехом. Ровно этот случай назван в
дизайн-доке первой из трех непочинимых ошибок. Не подтвердилось — состояние
остается неподтвержденным, и «удалено» никому не показывается.

**Повтор — успех.** Второй запуск на уже удаленном проекте отвечает тем же
состоянием и в хранилище не ходит. Отказ на повторе заставил бы пользователя
думать, что удаление не прошло.

**Срок виден.** `DELETION_SLA_HOURS` (`app/storage/retention.py`) — обещание,
а не константа для отчета. Запрошенное и не подтвержденное дольше срока
удаление показывается ошибкой: неисполненное обещание удаления — инцидент, а
не строка в логе.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.api.schemas.deletion import (
    DeletionAcceptedOut,
    DeletionStatusOut,
    DeletionTargetStatus,
)
from app.api.schemas.enums import DeletionState
from app.db import enums, models
from app.db.repositories import DeletionScope, Repositories
from app.services.projects import ProjectRefusal
from app.storage import DELETION_SLA_HOURS, ObjectStorage, StorageError, deletion_deadline

#: Что остается после удаления. Текст показывается пользователю дословно:
#: дизайн-док требует называть сохраняемое, а не умалчивать о нем.
RETENTION_NOTE = (
    "После удаления остаются: название и дата песни, выбранная цель обработки, "
    "запись в аудит-логе о самом факте удаления и события оплаты. "
    "Разбор песни остается после удаления исходника — по нему можно восстановить "
    "содержание произведения."
)

#: Состояния, в которых запускать удаление заново незачем.
_SETTLED = (enums.DeletionState.PURGE_REQUESTED, enums.DeletionState.PURGED)


def _now() -> datetime:
    return datetime.now(tz=UTC)


async def _purge(storage: ObjectStorage, keys: Sequence[str]) -> str:
    """Сносит объекты и убеждается, что их не стало. Возвращает след удаления.

    След обязателен (`confirm_purged` не примет пустой): «удалено» без следа —
    утверждение, которое некому проверить. Ключей объектов в следе нет: по
    ключу вместе с подписанной ссылкой восстанавливается доступ к чужой
    фонограмме, и политика логирования дизайн-дока запрещает их писать.
    """
    removed = 0
    for key in keys:
        try:
            if await storage.delete(key):
                removed += 1
        except StorageError as error:
            raise ProjectRefusal(
                503,
                "storage_unavailable",
                "Не удалось удалить файл из хранилища. Повторите запрос.",
                details={"reason": type(error).__name__},
            ) from error

        try:
            still_there = await storage.exists(key)
        except StorageError as error:
            raise ProjectRefusal(
                503,
                "storage_unavailable",
                "Не удалось проверить, что файл удален. Повторите запрос.",
                details={"reason": type(error).__name__},
            ) from error

        if still_there:
            # Хранилище отчиталось об удалении, а объект на месте. Показывать
            # «удалено» в этот момент — это и есть ложное обещание.
            raise ProjectRefusal(
                503,
                "deletion_unconfirmed",
                "Хранилище не подтвердило удаление файла. Удаление не выполнено.",
                details={"storage": type(storage).__name__},
            )

    return (
        f"объектов найдено: {len(keys)}; удалено: {removed}; "
        f"отсутствие проверено: {len(keys)}; "
        f"хранилище: {type(storage).__name__}; время: {_now().isoformat()}"
    )


async def _source_keys(repos: Repositories, project: models.Project) -> list[str]:
    """Ключи исходника: сам файл, нормализованная копия и превью.

    Удаленные строки читаются намеренно: у прерванного удаления ключ мог
    остаться на уже помеченной строке, и пропустить его значит оставить объект
    в хранилище навсегда.
    """
    uploads = await repos.uploads.list_for_project(project.id, include_deleted=True)
    keys: list[str] = []
    for upload in uploads:
        keys.extend(
            key
            for key in (
                upload.storage_key,
                upload.normalized_storage_key,
                upload.preview_storage_key,
            )
            if key
        )
    return keys


async def _results_keys(repos: Repositories, project: models.Project) -> list[str]:
    artifacts = await repos.artifacts.list_for_project(project.id, include_deleted=True)
    return [artifact.storage_key for artifact in artifacts if artifact.storage_key]


async def delete_source(
    repos: Repositories, project: models.Project, *, storage: ObjectStorage
) -> models.Project:
    """Убирает исходную запись. Разбор и материалы остаются."""
    if project.source_deletion_state in _SETTLED:
        return project

    receipt = await _purge(storage, await _source_keys(repos, project))
    await repos.projects.request_source_deletion(project.id)
    return await repos.projects.confirm_purged(
        project.id, scope=DeletionScope.SOURCE, receipt=receipt
    )


async def delete_results(
    repos: Repositories, project: models.Project, *, storage: ObjectStorage
) -> models.Project:
    """Убирает материалы. История версий остается перечнем изменений без файлов."""
    if project.results_deletion_state in _SETTLED:
        return project

    receipt = await _purge(storage, await _results_keys(repos, project))
    await repos.projects.request_results_deletion(project.id)
    return await repos.projects.confirm_purged(
        project.id, scope=DeletionScope.RESULTS, receipt=receipt
    )


def _target_status(
    state: enums.DeletionState,
    requested_at: datetime | None,
    purged_at: datetime | None,
    error: str | None,
) -> DeletionTargetStatus:
    if error is None and state is enums.DeletionState.PURGE_REQUESTED and requested_at is not None:
        if deletion_deadline(requested_at) < _now():
            error = (
                f"Срок удаления ({DELETION_SLA_HOURS} часа) истек, "
                "а хранилище удаление не подтвердило."
            )
    return DeletionTargetStatus(
        state=DeletionState(state.value),
        requested_at=requested_at,
        completed_at=purged_at,
        error=error,
    )


def status_out(project: models.Project) -> DeletionStatusOut:
    """Состояние обеих операций. «Удалено» — только по подтверждению."""
    return DeletionStatusOut(
        project_id=str(project.id),
        source=_target_status(
            project.source_deletion_state,
            project.source_deletion_requested_at,
            project.source_purged_at,
            project.source_purge_error,
        ),
        results=_target_status(
            project.results_deletion_state,
            project.results_deletion_requested_at,
            project.results_purged_at,
            project.results_purge_error,
        ),
        retention_note=project.retention_note or RETENTION_NOTE,
    )


def accepted_out(
    project: models.Project,
    *,
    scope: DeletionScope,
    status_url: str,
    revoked_links_count: int | None = None,
) -> DeletionAcceptedOut:
    """Ответ на запуск удаления.

    `requested_at` берется из строки, а не из текущего времени: повтор обязан
    называть тот момент, когда удаление действительно произошло, а не момент
    повторного нажатия.
    """
    state: enums.DeletionState = getattr(project, f"{scope.value}_deletion_state")
    requested_at = getattr(project, f"{scope.value}_deletion_requested_at")
    return DeletionAcceptedOut(
        project_id=str(project.id),
        state=DeletionState(state.value),
        requested_at=requested_at or _now(),
        status_url=status_url,
        revoked_links_count=revoked_links_count,
    )
