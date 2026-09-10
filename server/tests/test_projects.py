"""Тесты песен: разорванный круг, честная карточка, сроки хранения.

Написаны до реализации. Каждый проверяет обещание, а не вызов функции.

1. **Круг разорван.** До этого батча клиент не мог создать первым ни песню,
   ни загрузку: строка загрузки требовала песни, а создание песни требовало
   принятой загрузки. Здесь проверяется сквозной путь «создать -> загрузить ->
   открыть», который до разрыва круга был непроходим вовсе.
2. **Пустое остается пустым.** У песни без задания нет обработки, а не
   задание-призрак со статусом «в очереди» и пустым идентификатором. По такому
   идентификатору клиент пошел бы спрашивать статус и получил бы `404`.
3. **Сроки хранения из одного источника.** `app/db/retention.py` больше не
   объявляет своих величин: он берет их у `app/storage/retention.py`. Тест
   ловит расхождение, а не читает комментарии.

База настоящая: проверяется то, что доедет до сервера, а не то, что удобно
подставить. Хранилище подставное — оно из чужого батча, и его реализация
здесь не проверяется.
"""

from __future__ import annotations

import hashlib
import io
import struct
import uuid
import wave
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.consent_versions import current_consent
from app.api.contract_app import build_contract_app
from app.api.routes import uploads as uploads_route
from app.db import enums, models
from app.db import retention as db_retention
from app.db.repositories import ProjectCreate, Repositories, UploadCreate, UserCreate
from app.storage import ObjectAlreadyExistsError, ObjectNotFoundError, ObjectStorage, StoredObject
from app.storage import retention as storage_retention

pytestmark = pytest.mark.asyncio


# --- вспомогательное ---------------------------------------------------------


class FakeStorage(ObjectStorage):
    """Хранилище в памяти: батч хранилища идет отдельно, тут проверяется не он."""

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


def wav_bytes(*, seconds: float = 0.5) -> bytes:
    """Настоящий PCM WAV: сервер читает из него факты, а не верит на слово."""
    sample_rate = 44100
    frames = int(sample_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(struct.pack("<h", 16000) * frames * 2)
    return buffer.getvalue()


async def make_user(session: AsyncSession, *, contact: str = "band@example.test") -> models.User:
    return await Repositories(session).users.create(UserCreate(contact=contact))


def band_payload(**overrides: object) -> dict[str, object]:
    """Тело создания песни для сценария группы. Без `uploadId`: файла еще нет."""
    payload: dict[str, object] = {
        "name": "Late Train Home: подготовка",
        "scenario": "band",
        "goalId": "band-rehearsal",
        "setup": {
            "kind": "band",
            "vocalRange": "A2-C4",
            "guitars": 2,
            "bass": "5 струн",
            "keys": "Nord Stage",
            "drums": "акустика",
            "targetStyle": "ближе к оригиналу",
        },
        "consent": {"accepted": True, "versionId": current_consent().id},
    }
    payload.update(overrides)
    return payload


def build_app(session: AsyncSession, user_id: object, storage: ObjectStorage | None = None):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    app.dependency_overrides[uploads_route.object_storage] = lambda: storage or FakeStorage()
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


async def upload_file(
    client: httpx.AsyncClient, project_id: str, *, name: str = "track.wav"
) -> str:
    """Полный путь файла: заявка, тело, подтверждение. Возвращает идентификатор."""
    data = wav_bytes()
    created = await client.post(
        "/api/uploads",
        json={
            "projectId": project_id,
            "fileName": name,
            "sizeBytes": len(data),
            "contentType": "audio/wav",
            "consent": {"accepted": True, "versionId": current_consent().id},
        },
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload"]["id"]

    sent = await client.put(f"/api/uploads/{upload_id}/content", content=data)
    assert sent.status_code == 200, sent.text

    confirmed = await client.post(
        f"/api/uploads/{upload_id}/complete", json={"sizeBytes": sent.json()["sizeBytes"]}
    )
    assert confirmed.status_code == 200, confirmed.text
    return str(upload_id)


# --- Задача 1: круг «загрузка требует песни, песня требует загрузки» ---------


async def test_project_is_created_before_any_file(session: AsyncSession) -> None:
    """Песню можно завести до файла — иначе первым не создать вообще ничего."""
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        response = await client.post("/api/projects", json=band_payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"]
    assert body["name"] == "Late Train Home: подготовка"
    # Файла еще нет, и выдумывать его нечем.
    assert body["upload"] is None


async def test_created_project_takes_a_file_and_shows_it(session: AsyncSession) -> None:
    """Сквозной путь: создать -> загрузить -> открыть. До разрыва круга непроходим."""
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        created = await client.post("/api/projects", json=band_payload())
        assert created.status_code == 201, created.text
        project_id = created.json()["id"]

        await upload_file(client, project_id)

        opened = await client.get(f"/api/projects/{project_id}")

    assert opened.status_code == 200, opened.text
    upload = opened.json()["upload"]
    assert upload is not None, "загруженный файл не виден в карточке песни"
    assert upload["fileName"] == "track.wav"
    assert upload["state"] == "stored"


async def test_project_without_file_needs_its_own_name(session: AsyncSession) -> None:
    """Без файла имя брать неоткуда: молча назвать песню «без названия» нельзя."""
    user = await make_user(session)
    payload = band_payload()
    del payload["name"]

    async with client_for(build_app(session, user.id)) as client:
        response = await client.post("/api/projects", json=payload)

    assert response.status_code == 422, response.text
    # Отказ обязан назвать, чего не хватает: «неверный запрос» без предмета
    # заставляет пользователя гадать, что именно он сделал не так.
    reasons = [field["reason"] for field in error_of(response)["details"]["fields"]]
    assert any("название" in reason.lower() for reason in reasons), reasons


async def test_project_of_unknown_account_is_refused(session: AsyncSession) -> None:
    """Вход в аккаунт, за которым нет пользователя, — отказ, а не 500 на внешнем ключе."""
    async with client_for(build_app(session, uuid.uuid4())) as client:
        response = await client.post("/api/projects", json=band_payload())

    assert response.status_code == 401, response.text
    assert error_of(response)["code"] == "unauthorized"


async def make_holder(
    session: AsyncSession, user: models.User
) -> tuple[models.Project, models.Upload]:
    """Строка песни без согласия и принятый файл в ней.

    Так выглядят демо-данные (`app/db/seed.py`) и будущий импорт: строка
    `projects` появилась не из `POST /api/projects`, сценарий и согласие у нее
    еще не заполнены.
    """
    repos = Repositories(session)
    holder = await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="держатель файла",
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
        )
    )
    upload = await repos.uploads.create(
        UploadCreate(
            project_id=holder.id,
            file_name="track.wav",
            file_format=enums.UploadFormat.WAV,
            duration_seconds=180,
            quality=enums.UploadQuality.GOOD,
            size_bytes=4096,
            storage_key=f"source/{holder.id}/track.wav",
        )
    )
    return holder, upload


async def test_project_is_created_around_an_accepted_upload(session: AsyncSession) -> None:
    """Второй путь создания: песня оформляется поверх строки, где файл уже лежит."""
    user = await make_user(session)
    _, upload = await make_holder(session, user)
    payload = band_payload(uploadId=str(upload.id))
    del payload["name"]  # без имени: собирается из имени файла

    async with client_for(build_app(session, user.id)) as client:
        response = await client.post("/api/projects", json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "track: подготовка"
    assert body["upload"]["fileName"] == "track.wav"
    assert body["legalConsent"]["accepted"] is True


async def test_same_upload_does_not_make_a_second_project(session: AsyncSession) -> None:
    """Из одной загрузки песня создается один раз: вторая была бы дублем."""
    user = await make_user(session)
    _, upload = await make_holder(session, user)
    payload = band_payload(uploadId=str(upload.id))

    async with client_for(build_app(session, user.id)) as client:
        first = await client.post("/api/projects", json=payload)
        second = await client.post("/api/projects", json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert error_of(second)["code"] == "upload_already_used"


async def test_unknown_upload_is_not_found(session: AsyncSession) -> None:
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        response = await client.post("/api/projects", json=band_payload(uploadId=str(uuid.uuid4())))

    assert response.status_code == 404, response.text
    assert error_of(response)["code"] == "not_found"


# --- Задача 2: пустое остается пустым ---------------------------------------


async def test_project_without_job_has_no_processing(session: AsyncSession) -> None:
    """Задания нет — значит `null`, а не «в очереди» с пустым идентификатором.

    Пустой идентификатор клиент отнесет на адрес задания и получит `404`.
    """
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        response = await client.post("/api/projects", json=band_payload())

    assert response.status_code == 201, response.text
    assert response.json()["processing"] is None


async def test_project_list_shows_created_project_without_job(session: AsyncSession) -> None:
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        created = await client.post("/api/projects", json=band_payload())
        assert created.status_code == 201, created.text
        listed = await client.get("/api/projects")

    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created.json()["id"]
    assert body["items"][0]["jobStatus"] is None


async def test_stage_pack_is_not_invented_for_project_without_versions() -> None:
    """Пакет без версии — не объект с придуманным идентификатором, а его отсутствие."""
    from app.services import projects as service

    assert service.stage_pack_or_none(None, []) is None


async def test_foreign_project_is_closed(session: AsyncSession) -> None:
    owner = await make_user(session)
    stranger = await make_user(session, contact="other@example.test")

    async with client_for(build_app(session, owner.id)) as client:
        created = await client.post("/api/projects", json=band_payload())
    project_id = created.json()["id"]

    async with client_for(build_app(session, stranger.id)) as client:
        response = await client.get(f"/api/projects/{project_id}")

    assert response.status_code == 403, response.text
    assert error_of(response)["code"] == "forbidden"


async def test_project_is_renamed(session: AsyncSession) -> None:
    user = await make_user(session)

    async with client_for(build_app(session, user.id)) as client:
        created = await client.post("/api/projects", json=band_payload())
        project_id = created.json()["id"]
        renamed = await client.patch(
            f"/api/projects/{project_id}", json={"name": "Late Train Home: концерт"}
        )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Late Train Home: концерт"


# --- Задача 4: сроки хранения из одного источника ---------------------------


async def test_retention_takes_days_from_storage_module() -> None:
    """Величины не объявляются второй раз: два источника расходятся молча."""
    assert db_retention.SOURCE_DAYS is storage_retention.SOURCE_DAYS
    assert db_retention.RESULTS_DAYS is storage_retention.RESULTS_DAYS
    assert db_retention.AUDIT_LOG_DAYS is storage_retention.AUDIT_LOG_DAYS
    assert db_retention.TECH_LOG_DAYS is storage_retention.TECH_LOG_DAYS


async def test_retention_of_deleted_row_is_a_real_deadline() -> None:
    """У удаленной строки есть срок, а не `None`: иначе сметать ее нечем и некогда."""
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    assert db_retention.resolve_retention_until(deleted_at) == deleted_at + timedelta(
        days=storage_retention.RESULTS_DAYS
    )


async def test_retention_of_source_row_is_shorter_than_results() -> None:
    """Исходник живет 30 дней, результаты 180: род объекта выбирает вызывающий."""
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    expected = deleted_at + timedelta(days=storage_retention.SOURCE_DAYS)
    assert db_retention.resolve_retention_until(deleted_at, kind="source") == expected


async def test_retention_of_unknown_kind_is_refused() -> None:
    """Незнакомый род — ошибка, а не тихое умолчание в 180 дней."""
    with pytest.raises(ValueError):
        db_retention.resolve_retention_until(datetime(2026, 1, 1, tzinfo=UTC), kind="песни")


async def test_physical_purge_still_refuses_and_says_why() -> None:
    """Удаление, о котором отчитались, но которого не было, хуже отсутствия функции."""
    with pytest.raises(NotImplementedError) as error:
        db_retention.purge_objects(["source/late-train-home.mp3"])
    assert "хранилищ" in str(error.value).lower()
