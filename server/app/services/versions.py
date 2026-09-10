"""Version Engine: история аранжировки, снимок материалов, откат.

Три правила задают форму этого модуля.

**Первое. Версия неизменяема.** После вставки строка `versions` не меняется
никогда — это держит триггер базы (`migrations/versions/0002_versions_are_immutable.py`),
а не аккуратность вызывающего кода. Отсюда следует все остальное: откат создает
новую версию, а не правит целевую; переключение текущей версии не трогает
историю; снимок материалов пишется один раз, вместе с самой версией.

**Второе. Материалы принадлежат версии.** Строки `artifacts` переезжают в новую
версию вместе с пометками об устаревании, а покидаемая версия сохраняет их
снимок. Так у пакета к репетиции всегда один набор материалов — тот, что
соответствует текущей версии, — а история хранит то, что было раньше.

Отсюда прочтение `artifacts_snapshot`: это **материалы, с которыми версия
создана**. Схема раньше называла его состоянием «на момент выхода из версии»;
записать такое можно было бы только правкой уже созданной строки, то есть
переписыванием истории. Разницы по существу нет, потому что материалы меняются
только вместе с версией: состояние на выходе из версии и есть то, с чем в нее
вошли, плюс пометки — а они уезжают уже в следующую версию.

**Третье. Снимка нет — так и сказано.** У версии, заведенной до появления
материалов, снимок пустой (`NULL`). Откат на нее не выдает текущие материалы за
восстановленные: они переносятся как есть и помечаются к пересборке, и об этом
сказано и в перечне изменений, и отдельным списком в ответе.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db import enums, models
from app.db.repositories import ArtifactPatch, ProjectPatch, Repositories, VersionCreate
from app.services.projects import ProjectRefusal, artifact_out

#: Автор версии, созданной человеком: откат, ручная сборка.
HUMAN_AUTHOR = "Пользователь"
#: Автор версии, созданной действием директора.
DIRECTOR_AUTHOR = "AI-директор"

#: Что записывается в историю, когда снимка материалов у целевой версии не было.
NO_SNAPSHOT_CHANGE = (
    "Снимок материалов этой версии не сохранялся: материалы перенесены как есть "
    "и помечены к пересборке."
)


@dataclass(frozen=True, slots=True)
class MaterialState:
    """Состояние материала в собираемой версии."""

    status: enums.ArtifactStatus
    is_stale: bool


@dataclass(frozen=True, slots=True)
class VersionDraft:
    """Из чего собирается новая версия. Все поля обязательны намеренно.

    Умолчаний здесь нет: подпись «без названия» или автор «система» — это
    придуманные за пользователя данные в записи, которая переживет и правку,
    и откат.
    """

    label: str
    kind: enums.VersionKind
    changes: list[str]
    created_by: str
    status: enums.VersionStatus


@dataclass(frozen=True, slots=True)
class RollbackOutcome:
    """Результат отката: новая версия и честный счет по материалам."""

    version: models.Version
    restored: list[models.Artifact]
    stale_artifact_ids: list[str]
    restored_from: uuid.UUID


# --- чтение ------------------------------------------------------------------


def version_uuid(value: str) -> uuid.UUID:
    """Идентификатор версии из адреса.

    Чужая форма — «не найдено», а не «неверный запрос»: в контракте
    идентификаторы непрозрачные строки, и клиент не обязан знать, что внутри
    UUID.
    """
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProjectRefusal(404, "not_found", "Версия не найдена.") from error


async def list_versions(repos: Repositories, project: models.Project) -> Sequence[models.Version]:
    return await repos.versions.list_for_project(project.id)


async def version_of_project(
    repos: Repositories, project: models.Project, version_id: str
) -> models.Version:
    """Версия своей песни. Чужая отвечает «не найдено».

    Не `403`: адрес вложен в песню, права на песню уже проверены, и
    подтверждать существование чужой строки по чужому идентификатору незачем.
    """
    version = await repos.versions.get(version_uuid(version_id))
    if version is None or version.project_id != project.id:
        raise ProjectRefusal(404, "not_found", "Версия не найдена.")
    return version


async def current_version(repos: Repositories, project: models.Project) -> models.Version | None:
    if project.current_version_id is None:
        return None
    return await repos.versions.get(project.current_version_id)


async def materials_of(
    repos: Repositories, version: models.Version | None
) -> list[models.Artifact]:
    """Материалы версии — строки, привязанные к ней сейчас."""
    if version is None:
        return []
    return list(await repos.artifacts.list_for_version(version.id))


def snapshot_of(artifacts: Sequence[models.Artifact]) -> list[dict[str, Any]]:
    """Снимок материалов в том же виде, в каком их читает клиент.

    Именно в контрактном виде, а не в виде строк базы: снимок отдается в ответе
    как `artifactsSnapshot`, и вторая форма записи означала бы второй разбор
    того же на клиенте.
    """
    return [artifact_out(artifact).model_dump(mode="json", by_alias=True) for artifact in artifacts]


# --- запись ------------------------------------------------------------------


async def build_version(
    repos: Repositories,
    project: models.Project,
    *,
    base: models.Version | None,
    draft: VersionDraft,
    materials: Sequence[models.Artifact],
    marks: Mapping[uuid.UUID, MaterialState],
    now: datetime,
) -> models.Version:
    """Собрать новую версию и передать ей материалы.

    Порядок шагов важен: сначала пометки, потом снимок, потом сама версия и
    только затем переезд материалов. Снимок обязан показывать то состояние, с
    которым версия начинается, — иначе откат вернул бы материалы без пометок,
    то есть выдал бы непересобранное за готовое.
    """
    for artifact in materials:
        mark = marks.get(artifact.id)
        if mark is None:
            continue
        await repos.artifacts.update(
            artifact.id, ArtifactPatch(status=mark.status, is_stale=mark.is_stale)
        )

    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            parent_version_id=base.id if base is not None else None,
            label=draft.label,
            kind=draft.kind,
            created_by=draft.created_by,
            status=draft.status,
            created_at=now,
            changes=list(draft.changes),
            artifacts_snapshot=snapshot_of(materials),
        )
    )

    for artifact in materials:
        await repos.artifacts.update(artifact.id, ArtifactPatch(version_id=version.id))
    await repos.projects.update(project.id, ProjectPatch(current_version_id=version.id))
    await repos.session.flush()
    return version


async def rollback(
    repos: Repositories,
    project: models.Project,
    target: models.Version,
    *,
    label: str | None,
    comment: str | None,
    now: datetime,
) -> RollbackOutcome:
    """Откат на любую глубину. Целевая версия при этом не меняется.

    Возвращается не «состояние как было», а честный счет: что восстановлено из
    снимка и что придется пересобрать. Материал, снимка которого нет, не
    выдается за восстановленный.
    """
    if project.current_version_id is not None and target.id == project.current_version_id:
        raise ProjectRefusal(
            409,
            "version_already_current",
            "Эта версия уже текущая: откатываться некуда.",
            details={"versionId": str(target.id)},
        )

    base = await current_version(repos, project)
    live = await materials_of(repos, base)
    snapshot = target.artifacts_snapshot

    if snapshot is None:
        # Снимка нет — вернуть материалы этой версии неоткуда. Показать текущие
        # как восстановленные значило бы соврать: их состав относится к другой
        # версии.
        restored = live
        marks = {
            artifact.id: MaterialState(status=enums.ArtifactStatus.REBUILD_REQUIRED, is_stale=True)
            for artifact in restored
        }
        stale_ids = [str(artifact.id) for artifact in restored]
        change = NO_SNAPSHOT_CHANGE
    else:
        restored, marks, stale_ids = await _restore_from_snapshot(repos, project, snapshot)
        change = f"Материалы вернулись к состоянию версии «{target.label}»."

    changes = [f"Откат к версии «{target.label}».", change]
    if comment:
        # Пояснение человека остается в истории рядом с самим откатом: иначе по
        # списку версий не понять, почему вернулись назад.
        changes.append(comment)

    version = await build_version(
        repos,
        project,
        base=base,
        draft=VersionDraft(
            label=label or f"Откат к «{target.label}»",
            kind=target.kind,
            changes=changes,
            created_by=HUMAN_AUTHOR,
            status=(enums.VersionStatus.NEEDS_REVIEW if stale_ids else enums.VersionStatus.DRAFT),
        ),
        materials=restored,
        marks=marks,
        now=now,
    )
    return RollbackOutcome(
        version=version,
        restored=restored,
        stale_artifact_ids=stale_ids,
        restored_from=target.id,
    )


async def _restore_from_snapshot(
    repos: Repositories, project: models.Project, snapshot: Sequence[Any]
) -> tuple[list[models.Artifact], dict[uuid.UUID, MaterialState], list[str]]:
    """Разложить снимок на «нашлось» и «придется пересобрать».

    Строки материалов могли уйти вместе с удалением результатов. Восстановить
    удаленное нельзя (`docs/DELETION_AND_RETENTION_DESIGN.md`), поэтому такие
    записи снимка попадают в список к пересборке, а не в список восстановленных.
    """
    restored: list[models.Artifact] = []
    marks: dict[uuid.UUID, MaterialState] = {}
    stale_ids: list[str] = []

    for entry in snapshot:
        if not isinstance(entry, dict):
            continue
        raw_id = str(entry.get("id", ""))
        try:
            artifact_id = uuid.UUID(raw_id)
        except ValueError:
            stale_ids.append(raw_id)
            continue

        artifact = await repos.artifacts.get(artifact_id)
        if artifact is None or artifact.project_id != project.id:
            stale_ids.append(raw_id)
            continue

        state = _state_of(entry)
        restored.append(artifact)
        marks[artifact.id] = state
        if state.is_stale or state.status is enums.ArtifactStatus.REBUILD_REQUIRED:
            stale_ids.append(raw_id)

    return restored, marks, stale_ids


def _state_of(entry: Mapping[str, Any]) -> MaterialState:
    """Состояние материала из записи снимка.

    Незнакомый статус не подменяется «готово»: в снимке это означает испорченную
    запись, и считать материал готовым по испорченной записи — ровно тот случай,
    когда музыкант унесет на репетицию не те ноты.
    """
    try:
        status = enums.ArtifactStatus(str(entry.get("status", "")))
    except ValueError:
        return MaterialState(status=enums.ArtifactStatus.REBUILD_REQUIRED, is_stale=True)
    return MaterialState(status=status, is_stale=bool(entry.get("isStale", False)))


async def select(
    repos: Repositories, project: models.Project, target: models.Version
) -> models.Version:
    """Сделать версию текущей, не трогая историю.

    Переключение не создает версию и не двигает материалы. Поэтому оно
    возможно только там, где материалы версии при ней и остались. Если они
    уехали в более позднюю версию, честных вариантов два: показать пустой пакет
    там, где история обещает материалы, — или вернуть их молча, и тогда по
    списку версий не понять, почему материалы вдруг стали прежними. Оба плохи,
    поэтому здесь отказ с указанием на откат: он записывается в историю.
    """
    if project.current_version_id == target.id:
        return target

    rows = await repos.artifacts.list_for_version(target.id)
    if not rows and target.artifacts_snapshot:
        raise ProjectRefusal(
            409,
            "materials_moved",
            "Материалы этой версии сейчас в работе у другой: вернуть их можно откатом — "
            "он останется в истории.",
            details={
                "versionId": str(target.id),
                "currentVersionId": (
                    str(project.current_version_id)
                    if project.current_version_id is not None
                    else None
                ),
            },
        )

    await repos.projects.update(project.id, ProjectPatch(current_version_id=target.id))
    await repos.session.flush()
    return target
