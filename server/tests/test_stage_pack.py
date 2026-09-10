"""Тесты Stage Pack и выдачи файлов материалов.

Написаны до реализации. Проверяются обещания пакета к репетиции, а не вызовы
функций.

1. **В пакете только посчитанное.** Материал без файла не может числиться
   готовым: `status = ready` рядом с несобранным файлом — это мертвая ссылка,
   которую музыкант увидит уже на репетиции. Чего нет — про то сказано словами
   и названо, чего именно не хватает.
2. **Файл идет через API.** Развилка закрыта в `app/storage/base.py`: аудио
   отдается нашим адресом. Подписанная ссылка на объект наружу не выдается
   даже тогда, когда хранилище ее умеет, — отозвать ее нельзя, и
   `delete-results` перестал бы исполняться для уже выданных ссылок
   (`docs/DELETION_AND_RETENTION_DESIGN.md`).
3. **Выдуманного адреса не бывает.** Нет файла — отказ с причиной, а не ссылка,
   по которой ничего нет.
4. **Чужое закрыто.** Чужая песня и чужой материал не открываются.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.api.routes import stage_pack as stage_pack_route
from app.db import enums as db_enums
from app.db import models
from app.db.repositories import (
    ArtifactCreate,
    JobCreate,
    ProjectCreate,
    Repositories,
    UploadCreate,
    UserCreate,
    VersionCreate,
)
from app.storage import (
    LocalDiskStorage,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    ObjectStorage,
    StoredObject,
)

pytestmark = pytest.mark.asyncio


# --- подставное хранилище и фикстуры ----------------------------------------


class FakeStorage(ObjectStorage):
    """Хранилище в памяти. Подписанных ссылок не умеет — как локальный диск."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

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
        return self.objects.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def signed_url(self, key: str, expires_seconds: int) -> str | None:
        return None


class PresigningStorage(FakeStorage):
    """Хранилище, которое подписанную ссылку умеет.

    Соблазн отдать ее клиенту сильнее всего именно тогда, когда она есть.
    """

    SIGNED_HOST = "https://storage.example"

    async def signed_url(self, key: str, expires_seconds: int) -> str | None:
        return f"{self.SIGNED_HOST}/{key}?signature=abc&expires={expires_seconds}"


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


async def add_version(session: AsyncSession, project: models.Project) -> models.Version:
    repos = Repositories(session)
    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label="Версия для репетиции",
            kind=db_enums.VersionKind.BAND,
            created_by="Vokal",
            changes=["собран первый пакет"],
        )
    )
    await session.flush()
    return version


async def add_artifact(
    session: AsyncSession,
    project: models.Project,
    version: models.Version,
    *,
    name: str = "Партия баса",
    storage_key: str | None = None,
    artifact_type: db_enums.ArtifactType = db_enums.ArtifactType.PART,
    artifact_format: db_enums.ArtifactFormat = db_enums.ArtifactFormat.PDF,
    audience: db_enums.ArtifactAudience = db_enums.ArtifactAudience.BAND,
    status: db_enums.ArtifactStatus = db_enums.ArtifactStatus.READY,
    is_stale: bool = False,
) -> models.Artifact:
    repos = Repositories(session)
    return await repos.artifacts.create(
        ArtifactCreate(
            project_id=project.id,
            version_id=version.id,
            artifact_type=artifact_type,
            name=name,
            artifact_format=artifact_format,
            status=status,
            audience=audience,
            is_stale=is_stale,
            storage_key=storage_key,
            confidence=0.8,
        )
    )


async def add_upload(session: AsyncSession, project: models.Project) -> models.Upload:
    repos = Repositories(session)
    return await repos.uploads.create(
        UploadCreate(
            project_id=project.id,
            file_name="track.wav",
            file_format=db_enums.UploadFormat.WAV,
            duration_seconds=210,
            quality=db_enums.UploadQuality.GOOD,
        )
    )


def build_app(session: AsyncSession, user_id: object, storage: ObjectStorage):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    app.dependency_overrides[stage_pack_route.object_storage] = lambda: storage
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


# --- честный отказ там, где швов еще нет ------------------------------------


async def test_stage_pack_is_refused_while_wiring_is_missing() -> None:
    app = build_contract_app()
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{uuid.uuid4()}/stage-pack")

    assert response.status_code == 501
    assert error_of(response)["details"]["missing"]


# --- задача 1: в пакете только то, что посчитано ----------------------------


async def test_material_without_file_is_not_called_ready(session: AsyncSession) -> None:
    """Материал, файла которого нет, не показывается готовым.

    Состояние выводится из фактов, а не берется из колонки: в базе может
    лежать `ready`, но пока в хранилище нет объекта, готовым материал не стал.
    """
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(session, project, version, name="Партия баса", storage_key=None)
    await add_artifact(
        session,
        project,
        version,
        name="Минус",
        artifact_type=db_enums.ArtifactType.MINUS,
        artifact_format=db_enums.ArtifactFormat.WAV,
        storage_key="results/ab/abcdef/minus.wav",
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 200, response.text
    by_name = {item["name"]: item for item in response.json()["stagePack"]["artifacts"]}
    assert by_name["Партия баса"]["status"] == "pending"
    assert by_name["Минус"]["status"] == "ready"


async def test_preview_only_material_stays_ready_without_a_file(session: AsyncSession) -> None:
    """Материалу формата `VIEW` файл и не полагается: он показывается на экране."""
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(
        session,
        project,
        version,
        name="Аккорды",
        artifact_type=db_enums.ArtifactType.CHORDS,
        artifact_format=db_enums.ArtifactFormat.VIEW,
        storage_key=None,
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 200, response.text
    assert response.json()["stagePack"]["artifacts"][0]["status"] == "ready"


async def test_pack_says_how_many_files_are_missing(session: AsyncSession) -> None:
    """Клиенту сказано, чего именно нет, а не показан пакет без объяснений."""
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(session, project, version, name="Партия баса", storage_key=None)
    await add_artifact(session, project, version, name="Партия гитары", storage_key=None)
    await add_artifact(
        session,
        project,
        version,
        name="Минус",
        artifact_format=db_enums.ArtifactFormat.WAV,
        storage_key="results/ab/abcdef/minus.wav",
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    warnings = " ".join(response.json()["warnings"])
    assert "2" in warnings and "3" in warnings, warnings
    assert "файл" in warnings.lower(), warnings


async def test_pack_says_that_analysis_is_missing(session: AsyncSession) -> None:
    """Разбора нет — об этом сказано, а чужой разбор не подставляется."""
    project = await make_project(session)
    version = await add_version(session, project)
    await add_upload(session, project)
    await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    body = response.json()
    assert body["analysis"]["source"] == "none"
    assert body["analysis"]["bpm"] == 0
    assert any("разбор" in line.lower() for line in body["warnings"]), body["warnings"]


async def test_pack_says_when_materials_are_stale(session: AsyncSession) -> None:
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(
        session,
        project,
        version,
        name="Партия баса",
        storage_key="results/ab/abcdef/p.pdf",
        is_stale=True,
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    warnings = " ".join(response.json()["warnings"]).lower()
    assert "устарел" in warnings, warnings


async def test_pack_says_that_results_were_deleted(session: AsyncSession) -> None:
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")
    repos = Repositories(session)
    await repos.projects.request_results_deletion(project.id)

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 200, response.text
    assert "удалены" in response.json()["warnings"][0].lower()


async def test_pack_is_refused_while_processing_runs(session: AsyncSession) -> None:
    """Половина собранного пакета хуже, чем ничего: на репетицию уносят не то."""
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")
    repos = Repositories(session)
    await repos.jobs.create(
        JobCreate(
            project_id=project.id,
            idempotency_key=f"job-{uuid.uuid4()}",
            status=db_enums.JobStatus.RUNNING,
        )
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 409
    assert error_of(response)["code"] == "processing_in_progress"


async def test_pack_without_a_version_refuses_instead_of_inventing_one(
    session: AsyncSession,
) -> None:
    project = await make_project(session)
    app = build_app(session, project.user_id, FakeStorage())

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 409
    assert error_of(response)["code"] == "no_version_yet"


async def test_foreign_pack_is_closed(session: AsyncSession) -> None:
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(session, project, version, storage_key="results/ab/abcdef/p.pdf")
    stranger = await make_project(session, contact="stranger@example.test")

    app = build_app(session, stranger.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/stage-pack")

    assert response.status_code == 403


# --- список материалов -------------------------------------------------------


async def test_artifacts_are_filtered_by_type_and_audience(session: AsyncSession) -> None:
    project = await make_project(session)
    version = await add_version(session, project)
    await add_artifact(
        session,
        project,
        version,
        name="Партия баса",
        audience=db_enums.ArtifactAudience.BAND,
        storage_key="results/ab/abcdef/bass.pdf",
    )
    await add_artifact(
        session,
        project,
        version,
        name="Домашнее задание",
        artifact_type=db_enums.ArtifactType.STUDENT,
        audience=db_enums.ArtifactAudience.STUDENT,
        storage_key="results/ab/abcdef/home.pdf",
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        by_type = await client.get(
            f"/api/projects/{project.id}/artifacts", params={"type": "student"}
        )
        by_audience = await client.get(
            f"/api/projects/{project.id}/artifacts", params={"audience": "band"}
        )

    assert by_type.status_code == 200, by_type.text
    assert [item["name"] for item in by_type.json()["items"]] == ["Домашнее задание"]
    assert [item["name"] for item in by_audience.json()["items"]] == ["Партия баса"]


async def test_artifact_of_foreign_project_is_not_found(session: AsyncSession) -> None:
    mine = await make_project(session)
    other = await make_project(session, contact="other@example.test")
    other_version = await add_version(session, other)
    foreign = await add_artifact(
        session, other, other_version, storage_key="results/ab/abcdef/p.pdf"
    )

    app = build_app(session, mine.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{mine.id}/artifacts/{foreign.id}")

    assert response.status_code == 404


# --- задача 2: файл идет через API, выдуманных ссылок нет -------------------


async def test_download_refuses_when_the_file_is_not_built(session: AsyncSession) -> None:
    """Файла нет — отказ с причиной, а не ссылка в никуда."""
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(session, project, version, storage_key=None)

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")

    assert response.status_code in {409, 501}, response.text
    body = response.text.lower()
    assert "url" not in response.json() if response.status_code == 409 else True
    assert "http://vokal.test/api/projects" not in body


async def test_download_never_hands_out_a_signed_storage_url(session: AsyncSession) -> None:
    """Даже когда хранилище умеет подписывать, наружу идет наш адрес.

    Подписанную ссылку нельзя отозвать: с ней `delete-results` перестает
    исполняться для всех, кому ссылку уже отправили.
    """
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, storage_key="results/ab/abcdef/bass.pdf"
    )
    storage = PresigningStorage()
    await storage.put("results/ab/abcdef/bass.pdf", b"%PDF-1.4 bass", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")

    assert response.status_code == 200, response.text
    url = response.json()["url"]
    assert PresigningStorage.SIGNED_HOST not in url, url
    assert "signature" not in url, url
    assert url.startswith("http://vokal.test/api/projects/"), url


async def test_download_link_leads_to_a_working_stream(session: AsyncSession) -> None:
    """Главная проверка задачи: по выданному адресу приходит сам файл.

    Хранилище подписанных ссылок не умеет (`signed_url` отдает `None`) — и
    ровно поэтому файл обязан приехать через наш API, а не остаться битой
    ссылкой.
    """
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session,
        project,
        version,
        name="Минус",
        artifact_format=db_enums.ArtifactFormat.WAV,
        storage_key="results/ab/abcdef/minus.wav",
    )
    storage = FakeStorage()
    payload = b"RIFF....WAVEfmt " + b"\x00" * 64
    await storage.put("results/ab/abcdef/minus.wav", payload, "audio/wav")
    assert await storage.signed_url("results/ab/abcdef/minus.wav", 900) is None

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        described = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")
        assert described.status_code == 200, described.text
        streamed = await client.get(described.json()["url"])

    assert streamed.status_code == 200, streamed.text
    assert streamed.content == payload
    assert streamed.headers["content-type"].startswith("audio/")
    assert "attachment" in streamed.headers.get("content-disposition", "")


async def test_download_streams_from_real_local_disk(session: AsyncSession, tmp_path: Path) -> None:
    """Один прогон против настоящего диска, а не только против подставного."""
    project = await make_project(session)
    version = await add_version(session, project)
    key = f"results/{project.id.hex[:2]}/{project.id.hex}/bass.pdf"
    artifact = await add_artifact(session, project, version, storage_key=key)

    storage = LocalDiskStorage(tmp_path)
    await storage.put(key, b"%PDF-1.4 real file", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        described = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")
        streamed = await client.get(described.json()["url"])

    assert streamed.status_code == 200, streamed.text
    assert streamed.content == b"%PDF-1.4 real file"


async def test_download_of_foreign_material_is_closed(session: AsyncSession) -> None:
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, storage_key="results/ab/abcdef/bass.pdf"
    )
    storage = FakeStorage()
    await storage.put("results/ab/abcdef/bass.pdf", b"%PDF", "application/pdf")
    stranger = await make_project(session, contact="stranger@example.test")

    app = build_app(session, stranger.user_id, storage)
    async with client_for(app) as client:
        described = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")
        streamed = await client.get(
            f"/api/projects/{project.id}/artifacts/{artifact.id}/download",
            params={"content": "true"},
        )

    assert described.status_code == 403
    assert streamed.status_code == 403


async def test_download_after_results_deleted_is_gone_not_broken(session: AsyncSession) -> None:
    """После удаления результатов адрес отвечает «удалено», а не выдает файл."""
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, storage_key="results/ab/abcdef/bass.pdf"
    )
    storage = FakeStorage()
    await storage.put("results/ab/abcdef/bass.pdf", b"%PDF", "application/pdf")

    repos = Repositories(session)
    await repos.projects.request_results_deletion(project.id)

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")

    assert response.status_code == 410, response.text
    assert error_of(response)["code"] == "results_deleted"


async def test_missing_object_is_reported_not_crashed(session: AsyncSession) -> None:
    """Ключ есть, объекта нет: честный отказ, а не `500`."""
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, storage_key="results/ab/abcdef/lost.pdf"
    )

    app = build_app(session, project.user_id, FakeStorage())
    async with client_for(app) as client:
        response = await client.get(
            f"/api/projects/{project.id}/artifacts/{artifact.id}/download",
            params={"content": "true"},
        )

    assert response.status_code == 410, response.text
    assert error_of(response)["code"] == "file_missing"


async def test_download_names_the_file_for_a_human(session: AsyncSession) -> None:
    """Имя файла осмысленное и с расширением: его понесут в папку с нотами."""
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, name="Партия баса", storage_key="results/ab/abcdef/bass.pdf"
    )
    storage = FakeStorage()
    await storage.put("results/ab/abcdef/bass.pdf", b"%PDF", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        described = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")
        streamed = await client.get(described.json()["url"])

    assert described.json()["fileName"].endswith(".pdf")
    # Размер хранилище не сообщает, и выдумывать его нечем: он приходит
    # заголовком вместе с самим файлом.
    assert described.json()["sizeBytes"] is None
    assert int(streamed.headers["content-length"]) == 4
    disposition = streamed.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition, disposition


async def test_download_does_not_promise_an_expiry_it_cannot_keep(
    session: AsyncSession,
) -> None:
    """Срок жизни адреса не выдумывается.

    Адрес не ключ доступа: права проверяются на каждом запросе, а закрывается
    он удалением результатов, а не таймером. Поставить сюда «через 15 минут»
    значило бы пообещать то, чего никто не исполняет.
    """
    project = await make_project(session)
    version = await add_version(session, project)
    artifact = await add_artifact(
        session, project, version, storage_key="results/ab/abcdef/bass.pdf"
    )
    storage = FakeStorage()
    await storage.put("results/ab/abcdef/bass.pdf", b"%PDF", "application/pdf")

    app = build_app(session, project.user_id, storage)
    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/artifacts/{artifact.id}/download")

    assert response.json()["expiresAt"] is None
