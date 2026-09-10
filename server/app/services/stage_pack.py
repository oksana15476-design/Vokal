"""Stage Pack: пакет к репетиции и выдача файлов материалов.

Три правила, из которых выведено все остальное в этом модуле.

**Пакет состоит из посчитанного, а не из запланированного.** Материал, файла
которого нет, готовым не показывается — даже если в колонке `status` стоит
`ready`. Состояние выводится из фактов, как состояние загрузки в
`app/services/uploads.py`: есть объект в хранилище — материал готов, нет —
`pending`. Разница не косметическая: «готово» рядом с несобранным файлом
превращается в мертвую ссылку, и обнаружит ее музыкант на репетиции, а не мы.

**Чего нет — про то сказано словами.** Пустой пакет без объяснения читается
как «обработка ничего не дала». Поэтому в `warnings` попадает разбор того, чего
именно не хватает: сколько материалов без файлов, есть ли разбор песни,
сколько материалов устарело после правки аранжировки, удалены ли результаты.

**Файл идет через наш адрес.** Развилка закрыта в `app/storage/base.py`:
аудио отдается приложением. Подписанная ссылка на объект наружу не выдается
даже там, где хранилище ее умеет: отозвать ее нельзя, и `delete-results`
перестал бы исполняться для всех, кому ссылку уже отправили
(`docs/DELETION_AND_RETENTION_DESIGN.md`). Отсюда же и отсутствие срока жизни
у выданного адреса: он не ключ доступа, права проверяются на каждом запросе, а
закрывается он удалением результатов, а не таймером. Выдумывать «через 15
минут» на месте несуществующего срока нельзя — это обещание, которое некому
исполнить.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from urllib.parse import quote

from app.api.schemas.artifacts import (
    ArtifactDownloadOut,
    ArtifactOut,
    StagePackOut,
    StagePackResponse,
)
from app.api.schemas.enums import ArtifactStatus
from app.db import enums, models
from app.db.repositories import Repositories
from app.services import jobs as jobs_service
from app.services import projects as projects_service
from app.services.projects import ProjectRefusal
from app.storage import ObjectStorage, StorageError

#: Чем отдается файл материала и как он называется на диске у человека.
#: `VIEW` в таблице нет намеренно: этот материал показывается на экране,
#: файла у него не бывает, и требовать от него объект в хранилище — значит
#: объявить несобранным то, что собрано.
FILE_KIND: dict[enums.ArtifactFormat, tuple[str, str]] = {
    enums.ArtifactFormat.PDF: ("application/pdf", "pdf"),
    enums.ArtifactFormat.MIDI: ("audio/midi", "mid"),
    enums.ArtifactFormat.WAV: ("audio/wav", "wav"),
    enums.ArtifactFormat.ZIP: ("application/zip", "zip"),
    enums.ArtifactFormat.MUSICXML: ("application/vnd.recordare.musicxml+xml", "musicxml"),
}

DOWNLOAD_MISSING = (
    "сборка материалов: обработки звука нет, файл этого материала не создавался",
    "разбор песни (SongGraph), из которого материалы собираются",
)

#: Символы, которых не должно быть в имени файла: разделители путей и кавычки
#: заголовка. Заменяются, а не вырезаются, чтобы имя осталось читаемым.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def has_file_slot(artifact: models.Artifact) -> bool:
    """Полагается ли этому материалу файл вообще."""
    return artifact.artifact_format in FILE_KIND


def is_built(artifact: models.Artifact) -> bool:
    """Собран ли материал на самом деле."""
    return not has_file_slot(artifact) or bool(artifact.storage_key)


def artifact_out(artifact: models.Artifact) -> ArtifactOut:
    """Материал в ответ контракта, с состоянием по факту.

    Колонка `status` описывает замысел («этот материал должен быть готов»), а
    отдавать наружу надо положение дел. Пока объекта в хранилище нет, материал
    остается `pending`, чем бы ни была заполнена колонка.
    """
    out = projects_service.artifact_out(artifact)
    if is_built(artifact):
        return out
    return out.model_copy(update={"status": ArtifactStatus.PENDING})


def stage_pack_out(version_id: uuid.UUID, artifacts: Sequence[models.Artifact]) -> StagePackOut:
    """Материалы одной версии. Своей таблицы у пакета нет — это срез по версии."""
    return StagePackOut(
        id=f"pack-{version_id}",
        version_id=str(version_id),
        artifacts=[artifact_out(artifact) for artifact in artifacts],
    )


def pack_warnings(
    project: models.Project,
    artifacts: Sequence[models.Artifact],
    *,
    analysis_source: str,
    job_warnings: Sequence[str],
) -> list[str]:
    """Что в пакете не собрано и почему — словами, а не пустым местом.

    Тексты временные: любой пользовательский текст проходит связку копирайтер —
    главред (CLAUDE.md). До этой правки формулировки держим нейтральными, без
    обещаний сроков и результата.
    """
    warnings: list[str] = []

    if project.results_deletion_state is not enums.DeletionState.PRESENT:
        # Молчать об этом нельзя: пустой пакет иначе читается как «обработка
        # ничего не дала».
        warnings.append("Результаты этой песни удалены и не восстанавливаются.")

    warnings.extend(job_warnings)

    unbuilt = [artifact for artifact in artifacts if not is_built(artifact)]
    if unbuilt:
        warnings.append(
            f"Файлы собраны не у всех материалов: {len(unbuilt)} из {len(artifacts)} "
            "пока без файла. Скачать их нельзя."
        )

    if analysis_source == "none":
        warnings.append(
            "Разбора песни нет: тональность, темп и аккорды не рассчитаны. "
            "Материалы собраны без него."
        )

    stale = [artifact for artifact in artifacts if artifact.is_stale]
    if stale:
        warnings.append(
            f"Устарели материалы: {len(stale)}. Они не соответствуют текущей версии "
            "аранжировки, их нужно пересобрать."
        )

    return warnings


async def pack_version(
    repos: Repositories, project: models.Project, version_id: str | None
) -> uuid.UUID:
    """Версия, чьи материалы показываем.

    Явно названная версия проверяется на принадлежность песне: иначе по
    идентификатору чужой версии можно было бы вытащить чужие материалы.
    """
    versions = await repos.versions.list_for_project(project.id)
    if not versions:
        raise ProjectRefusal(
            409,
            "no_version_yet",
            "У песни еще нет версии аранжировки: показывать нечего.",
        )
    if version_id is None:
        return project.current_version_id or versions[-1].id

    wanted = projects_service.entity_id(version_id)
    if wanted not in {version.id for version in versions}:
        raise ProjectRefusal(404, "not_found", "Версия не найдена.")
    return wanted


async def refuse_while_processing(repos: Repositories, project: models.Project) -> None:
    """Пока обработка идет, Stage Pack не отдается.

    Показать половину собранного пакета хуже, чем не показать ничего:
    музыкант унесет на репетицию то, что через минуту пересоберут.
    """
    job = await jobs_service.latest_job(repos, project.id)
    if job is not None and job.status in jobs_service.LIVE_STATUSES:
        raise ProjectRefusal(
            409,
            "processing_in_progress",
            "Обработка еще идет. Материалы будут готовы, когда задание завершится.",
            details={"jobId": str(job.id), "status": job.status.value},
        )


async def read_pack(
    repos: Repositories, project: models.Project, version_id: str | None
) -> StagePackResponse:
    """Пакет к репетиции целиком: материалы, разбор и места для проверки."""
    await refuse_while_processing(repos, project)
    version = await pack_version(repos, project, version_id)

    artifacts = await repos.artifacts.list_for_version(version)
    upload = await projects_service.source_upload(repos, project)
    issues = await repos.review_issues.list_for_project(project.id)
    comments: list[models.ReviewComment] = []
    for issue in issues:
        comments.extend(await repos.review_comments.list_for_issue(issue.id))

    analysis = projects_service.analysis_out(project, upload)
    job = await jobs_service.latest_job(repos, project.id)

    return StagePackResponse(
        stage_pack=stage_pack_out(version, artifacts),
        analysis=analysis,
        review_issues=[projects_service.review_issue_out(issue, comments) for issue in issues],
        warnings=pack_warnings(
            project,
            artifacts,
            analysis_source=analysis.source.value,
            job_warnings=list(job.warnings or []) if job is not None else [],
        ),
    )


# --- выдача файла ------------------------------------------------------------


def refuse_if_results_deleted(project: models.Project) -> None:
    """После удаления результатов адрес честно говорит «удалено».

    Не «не найдено»: разница для пользователя существенная. «Не найдено»
    заставляет искать ошибку в ссылке, а результаты он удалил сам, и
    восстановления не будет.
    """
    if project.results_deletion_state is not enums.DeletionState.PRESENT:
        raise ProjectRefusal(
            410,
            "results_deleted",
            "Результаты этой песни удалены и не восстанавливаются.",
        )


async def owned_artifact(
    repos: Repositories, project: models.Project, artifact_id: str
) -> models.Artifact:
    """Материал этой песни.

    Материал чужой песни отвечает «не найден», а не «закрыт»: адрес вложен в
    песню, и подтверждать существование чужой строки по чужому идентификатору
    незачем.
    """
    artifact = await repos.artifacts.get(projects_service.entity_id(artifact_id))
    if artifact is None or artifact.project_id != project.id:
        raise ProjectRefusal(404, "not_found", "Материал не найден.")
    return artifact


def file_name_for(artifact: models.Artifact) -> str:
    """Имя файла для человека: название материала и расширение по формату."""
    media = FILE_KIND.get(artifact.artifact_format)
    stem = _UNSAFE_NAME.sub(" ", artifact.name).strip() or "material"
    return f"{stem}.{media[1]}" if media else stem


def content_disposition(artifact: models.Artifact) -> str:
    """Заголовок с именем файла, читаемым и в старом клиенте, и в новом.

    Две формы имени сразу: `filename` для тех, кто не понимает RFC 5987, и
    `filename*` с процентным кодированием для всех остальных. Русское название
    материала иначе приезжает мусором — а файл несут в папку с нотами, и
    опознать его надо глазами.
    """
    name = file_name_for(artifact)
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def media_type_for(artifact: models.Artifact) -> str:
    media = FILE_KIND.get(artifact.artifact_format)
    return media[0] if media else "application/octet-stream"


def require_file(artifact: models.Artifact) -> str:
    """Ключ объекта материала или честный отказ.

    Отказ, а не ссылка: адрес, за которым нет файла, снаружи неотличим от
    рабочего, и обнаружится это переходом по нему.
    """
    if not has_file_slot(artifact):
        raise ProjectRefusal(
            409,
            "artifact_has_no_file",
            "У этого материала нет файла: он показывается на экране, а не скачивается.",
            details={"format": artifact.artifact_format.value},
        )
    if not artifact.storage_key:
        raise ProjectRefusal(
            409,
            "artifact_not_built",
            "Файл этого материала еще не собран, скачивать нечего.",
            details={"missing": list(DOWNLOAD_MISSING)},
        )
    return artifact.storage_key


def download_out(artifact: models.Artifact, *, url: str) -> ArtifactDownloadOut:
    """Описание выдачи: наш адрес, имя файла и отсутствие выдуманного срока.

    `size_bytes` остается пустым: размер объекта хранилище не сообщает, а
    вычитывать файл целиком ради числа под кнопкой — платить памятью процесса
    за украшение. Размер приходит вместе с самим файлом, заголовком ответа.
    """
    return ArtifactDownloadOut(
        artifact_id=str(artifact.id),
        url=url,
        expires_at=None,
        file_name=file_name_for(artifact),
        size_bytes=None,
    )


async def artifact_file(artifact: models.Artifact, *, storage: ObjectStorage) -> bytes:
    """Содержимое файла материала.

    Читается целиком: потокового чтения у контракта хранилища пока нет
    (`app/storage/base.py`), и притворяться, что оно есть, здесь нечем.
    Пропавший объект — это «удалено», а не `500`: ключ в базе есть, файла нет,
    и сказать об этом надо прямо.
    """
    key = require_file(artifact)
    try:
        return await storage.get(key)
    except StorageError as error:
        raise ProjectRefusal(
            410,
            "file_missing",
            "Файл материала недоступен: в хранилище его нет.",
            details={"reason": type(error).__name__},
        ) from error


def filter_artifacts(
    artifacts: Sequence[models.Artifact],
    *,
    artifact_type: str | None,
    audience: str | None,
) -> list[models.Artifact]:
    return [
        artifact
        for artifact in artifacts
        if (artifact_type is None or artifact.artifact_type.value == artifact_type)
        and (audience is None or artifact.audience.value == audience)
    ]
