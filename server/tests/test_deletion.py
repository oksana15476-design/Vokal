"""Тесты удаления исходника и результатов.

Написаны до реализации. Проверяется не то, что функция вызвалась, а обещания,
которые кнопка «Удалить» дает пользователю в
`docs/DELETION_AND_RETENTION_DESIGN.md`:

1. **Удаление физическое.** После `delete-source` объекта нет в хранилище —
   не «строка помечена», а объекта нет. Пометка в базе без снесенного объекта
   это и есть ложное обещание, ради которого документ писался.
2. **Удаление видимое.** Состояние читается отдельным адресом и различает
   «удаление выполняется» и «удалено». Срок SLA (24 часа,
   `app/storage/retention.py`) не украшение: просроченное удаление показывается
   как инцидент, а не как «еще выполняется».
3. **Удаление идемпотентное.** Повтор отвечает успехом и не трогает хранилище
   второй раз.
4. **Отказ хранилища не превращается в «удалено».** Если объект снести не
   удалось, состояние остается прежним, а клиент видит отказ.

Хранилище подставное: физическое удаление проверяется по его содержимому, а не
по вызову метода. Один тест ходит в настоящий локальный диск — иначе «объект
физически убран» осталось бы утверждением про заглушку.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.api.routes import deletion as deletion_route
from app.db import enums as db_enums
from app.db import models
from app.db.repositories import (
    ArtifactCreate,
    ProjectCreate,
    Repositories,
    UploadCreate,
    UserCreate,
    VersionCreate,
)
from app.storage import (
    DELETION_SLA_HOURS,
    LocalDiskStorage,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    ObjectStorage,
    StorageError,
    StoredObject,
)

pytestmark = pytest.mark.asyncio


# --- подставное хранилище и фикстуры ----------------------------------------


class FakeStorage(ObjectStorage):
    """Хранилище в памяти. Содержимое видно тесту, вызовы посчитаны."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.delete_calls = 0

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        if key in self.objects:
            raise ObjectAlreadyExistsError(key)
        self.objects[key] = (data, content_type)
        return StoredObject(
            key=key,
            size_bytes=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            content_type=content_type,
        )

    async def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key][0]

    async def delete(self, key: str) -> bool:
        self.delete_calls += 1
        return self.objects.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def signed_url(self, key: str, expires_seconds: int) -> str | None:
        return None


class BrokenStorage(FakeStorage):
    """Хранилище, которое не может удалить."""

    async def delete(self, key: str) -> bool:
        self.delete_calls += 1
        raise StorageError("хранилище недоступно")


class SilentStorage(FakeStorage):
    """Хранилище, которое отчитывается об удалении, но объект оставляет.

    Ровно тот случай, ради которого дизайн-док требует подтверждения: в
    S3 с включенным версионированием `DELETE` создает delete-marker, а объект
    остается доступен.
    """

    async def delete(self, key: str) -> bool:
        self.delete_calls += 1
        return True


async def make_project(
    session: AsyncSession, *, contact: str = "band@example.test"
) -> models.Project:
    repos = Repositories(session)
    user = await repos.users.create(UserCreate(contact=contact))
    return await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Late Train Home",
            scenario=db_enums.Scenario.BAND,
            processing_goal_id=db_enums.ProcessingGoalId.BAND_REHEARSAL,
        )
    )


async def add_upload(
    session: AsyncSession,
    project: models.Project,
    *,
    storage_key: str | None = None,
    normalized_storage_key: str | None = None,
    preview_storage_key: str | None = None,
) -> models.Upload:
    repos = Repositories(session)
    return await repos.uploads.create(
        UploadCreate(
            project_id=project.id,
            file_name="track.wav",
            file_format=db_enums.UploadFormat.WAV,
            duration_seconds=210,
            quality=db_enums.UploadQuality.GOOD,
            storage_key=storage_key,
            normalized_storage_key=normalized_storage_key,
            preview_storage_key=preview_storage_key,
        )
    )


async def add_version(session: AsyncSession, project: models.Project) -> models.Version:
    repos = Repositories(session)
    return await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Версия для репетиции",
            kind=db_enums.VersionKind.BAND,
            created_by="Vokal",
            changes=["собран первый пакет"],
            artifacts_snapshot=[{"id": "a1"}],
        )
    )


async def add_artifact(
    session: AsyncSession,
    project: models.Project,
    version: models.Version,
    *,
    storage_key: str | None = None,
    name: str = "Партия баса",
) -> models.Artifact:
    repos = Repositories(session)
    return await repos.artifacts.create(
        ArtifactCreate(
            project_id=project.id,
            version_id=version.id,
            artifact_type=db_enums.ArtifactType.PART,
            name=name,
            artifact_format=db_enums.ArtifactFormat.PDF,
            status=db_enums.ArtifactStatus.READY,
            storage_key=storage_key,
        )
    )


def build_app(session: AsyncSession, user_id: object, storage: ObjectStorage):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    app.dependency_overrides[deletion_route.object_storage] = lambda: storage
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


# --- честный отказ там, где швов еще нет ------------------------------------


async def test_deletion_is_refused_while_wiring_is_missing() -> None:
    """Без сессии и входа адрес отвечает `501`, а не «удалено»."""
    app = build_contract_app()
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{uuid.uuid4()}/delete-source", json={"confirm": True}
        )

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert error["details"]["missing"]


async def test_deletion_without_confirmation_is_refused(session: AsyncSession) -> None:
    """Необратимая операция не запускается пустым телом."""
    project = await make_project(session)
    app = build_app(session, project.user_id, FakeStorage())

    async with client_for(app) as client:
        response = await client.post(f"/api/projects/{project.id}/delete-source", json={})

    assert response.status_code == 422


# --- задача 1: объект физически убран из хранилища --------------------------


async def test_delete_source_removes_object_from_storage(session: AsyncSession) -> None:
    """Объекта нет в хранилище, ключа нет в базе, строка помечена."""
    project = await make_project(session)
    upload = await add_upload(
        session,
        project,
        storage_key="source/ab/abcdef/one.wav",
        preview_storage_key="source/ab/abcdef/one-preview.wav",
    )
    storage = FakeStorage()
    await storage.put(upload.storage_key or "", b"raw audio", "audio/wav")
    await storage.put(upload.preview_storage_key or "", b"preview", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-source",
            json={"confirm": True, "reason": "по просьбе владельца записи"},
        )

    assert response.status_code == 202, response.text
    assert storage.objects == {}, "объект остался в хранилище, а пользователю сказано «удалено»"

    repos = Repositories(session)
    stored = await repos.uploads.get(upload.id, include_deleted=True)
    assert stored is not None
    assert stored.storage_key is None
    assert stored.preview_storage_key is None
    assert stored.deleted_at is not None

    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    assert refreshed.source_deletion_state is db_enums.DeletionState.PURGED
    assert refreshed.source_purge_receipt


async def test_delete_source_leaves_results_alone(session: AsyncSession) -> None:
    """Смысл операции в том, что материалы остаются: удален исходник."""
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    version = await add_version(session, project)
    artifact = await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")

    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")
    await storage.put("results/ab/abcdef/p.pdf", b"pdf", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )

    assert response.status_code == 202
    assert "results/ab/abcdef/p.pdf" in storage.objects, "удаление исходника снесло материалы"

    repos = Repositories(session)
    kept = await repos.artifacts.get(artifact.id)
    assert kept is not None and kept.storage_key == "results/ab/abcdef/p.pdf"


async def test_delete_results_removes_artifact_objects(session: AsyncSession) -> None:
    """Материалы уходят из хранилища, история версий остается без файлов."""
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    version = await add_version(session, project)
    await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")

    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")
    await storage.put("results/ab/abcdef/p.pdf", b"pdf", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-results", json={"confirm": True}
        )

    assert response.status_code == 202, response.text
    assert "results/ab/abcdef/p.pdf" not in storage.objects
    assert "source/ab/abcdef/one.wav" in storage.objects, "удаление результатов снесло исходник"

    repos = Repositories(session)
    kept_version = await repos.versions.get(version.id)
    assert kept_version is not None, "история версий должна остаться"
    assert kept_version.artifacts_snapshot is None, "снимок материалов — это тоже материалы"

    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    assert refreshed.results_deletion_state is db_enums.DeletionState.PURGED


async def test_deletion_is_verified_not_declared(session: AsyncSession) -> None:
    """Хранилище отчиталось об удалении, но объект остался — это не «удалено».

    Проверяется именно факт: состояние обязано остаться неподтвержденным.
    """
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")

    storage = SilentStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )

    assert response.status_code == 503, response.text
    repos = Repositories(session)
    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    assert refreshed.source_deletion_state is not db_enums.DeletionState.PURGED


async def test_storage_failure_does_not_claim_deletion(session: AsyncSession) -> None:
    """Отказ хранилища виден клиентом, а состояние остается прежним."""
    project = await make_project(session)
    upload = await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")

    app = build_app(session, project.user_id, BrokenStorage())
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )

    assert response.status_code == 503
    assert error_of(response)["code"] == "storage_unavailable"

    repos = Repositories(session)
    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    assert refreshed.source_deletion_state is db_enums.DeletionState.PRESENT

    # Ключ не обнулен: иначе повторить удаление будет нечем, и объект
    # останется в хранилище навсегда.
    kept = await repos.uploads.get(upload.id, include_deleted=True)
    assert kept is not None and kept.storage_key == "source/ab/abcdef/one.wav"


async def test_deletion_reaches_real_local_disk(session: AsyncSession, tmp_path: Path) -> None:
    """Один прогон против настоящего диска: файла на диске больше нет."""
    project = await make_project(session)
    key = f"source/{project.id.hex[:2]}/{project.id.hex}/one.wav"
    await add_upload(session, project, storage_key=key)

    storage = LocalDiskStorage(tmp_path)
    await storage.put(key, b"raw audio", "audio/wav")
    assert await storage.exists(key)

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )

    assert response.status_code == 202, response.text
    assert not await storage.exists(key)
    assert not list(tmp_path.rglob("*.wav")), "файл остался на диске"


# --- задача 2: повтор отвечает честно ---------------------------------------


async def test_repeated_deletion_succeeds_without_touching_storage(session: AsyncSession) -> None:
    """Повтор — успех, а не ошибка, и второго обращения в хранилище нет."""
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        first = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )
        calls_after_first = storage.delete_calls
        second = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )

    assert first.status_code == 202
    assert second.status_code == 202, second.text
    assert second.json()["state"] == "purged"
    assert storage.delete_calls == calls_after_first, "повтор пошел удалять уже удаленное"

    # Момент запроса не переписывается вторым вызовом: удаление произошло
    # тогда, когда произошло.
    assert second.json()["requestedAt"] == first.json()["requestedAt"]


async def test_unconfirmed_deletion_is_not_confirmed_by_a_repeat(session: AsyncSession) -> None:
    """Повтор поверх незавершенного удаления не объявляет его выполненным.

    Состояние `purge_requested` означает, что ключи объектов из базы уже стерты,
    а подтверждения от хранилища еще нет. Адресовать объект больше нечем, и
    проверить его отсутствие невозможно — значит и «удалено» показывать не с
    чего. Повтор обязан оставить состояние неподтвержденным, а не дописать
    подтверждение из ничего.
    """
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    repos = Repositories(session)
    await repos.projects.request_source_deletion(project.id)
    await repos.projects.request_results_deletion(project.id)

    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        source_again = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )
        results_again = await client.post(
            f"/api/projects/{project.id}/delete-results", json={"confirm": True}
        )

    assert source_again.status_code == 202, source_again.text
    assert source_again.json()["state"] == "purge_requested"
    assert results_again.status_code == 202, results_again.text
    assert results_again.json()["state"] == "purge_requested"

    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    assert refreshed.source_purged_at is None, "подтверждение удаления записано без проверки"
    assert refreshed.results_purged_at is None


# --- задача 3: удаление видно ------------------------------------------------


async def test_deletion_status_reports_both_operations(session: AsyncSession) -> None:
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        await client.post(f"/api/projects/{project.id}/delete-source", json={"confirm": True})
        response = await client.get(f"/api/projects/{project.id}/deletion-status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"]["state"] == "purged"
    assert body["source"]["completedAt"]
    assert body["results"]["state"] == "present"
    assert body["retentionNote"], "что сохраняется после удаления — не пустая строка"


async def test_accepted_answer_points_at_status_address(session: AsyncSession) -> None:
    """Адрес статуса в ответе рабочий, а не строка «когда-нибудь»."""
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        accepted = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )
        status = await client.get(accepted.json()["statusUrl"])

    assert status.status_code == 200, status.text
    assert status.json()["projectId"] == str(project.id)


async def test_overdue_deletion_is_reported_as_incident(session: AsyncSession) -> None:
    """Просроченное удаление показывается инцидентом, а не «еще выполняется».

    Срок — `DELETION_SLA_HOURS` из `app/storage/retention.py`.
    """
    project = await make_project(session)
    repos = Repositories(session)
    await repos.projects.request_source_deletion(project.id)
    refreshed = await repos.projects.get(project.id)
    assert refreshed is not None
    refreshed.source_deletion_requested_at = datetime.now(UTC) - timedelta(
        hours=DELETION_SLA_HOURS + 1
    )
    await session.flush()

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/deletion-status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"]["state"] == "purge_requested"
    assert body["source"]["error"], "просроченный срок удаления обязан быть виден"
    assert str(DELETION_SLA_HOURS) in body["source"]["error"]


async def test_deletion_within_sla_is_not_called_overdue(session: AsyncSession) -> None:
    """Только что запрошенное удаление инцидентом не считается."""
    project = await make_project(session)
    repos = Repositories(session)
    await repos.projects.request_source_deletion(project.id)

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/deletion-status")

    assert response.status_code == 200
    assert response.json()["source"]["error"] is None


# --- задача 4: чужое не удаляется -------------------------------------------


async def test_deletion_of_foreign_project_is_closed(session: AsyncSession) -> None:
    """Чужую песню нельзя ни удалить, ни спросить о ее состоянии."""
    project = await make_project(session)
    await add_upload(session, project, storage_key="source/ab/abcdef/one.wav")
    storage = FakeStorage()
    await storage.put("source/ab/abcdef/one.wav", b"raw", "audio/wav")

    stranger = await make_project(session, contact="stranger@example.test")
    app = build_app(session, stranger.user_id, storage)

    async with client_for(app) as client:
        deleted = await client.post(
            f"/api/projects/{project.id}/delete-source", json={"confirm": True}
        )
        status = await client.get(f"/api/projects/{project.id}/deletion-status")

    assert deleted.status_code == 403
    assert status.status_code == 403
    assert "source/ab/abcdef/one.wav" in storage.objects, "чужое удаление дошло до хранилища"


async def test_unknown_project_is_not_found(session: AsyncSession) -> None:
    project = await make_project(session)
    app = build_app(session, project.user_id, FakeStorage())

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{uuid.uuid4()}/deletion-status")

    assert response.status_code == 404
