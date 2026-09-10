"""Тесты загрузки исходника.

Написаны до реализации и устроены так, чтобы каждый мог упасть. Проверяются не
вызовы функций, а обещания, которые загрузка дает пользователю:

1. **Отказ приходит отказом.** Неподходящий формат, слишком большой файл,
   пустое тело и неизвестная версия согласия отвечают своим кодом и текстом,
   а не `500` и не тихим приемом.
2. **Факт отличается от заявления.** Оценка качества считается по тому, что
   сервер прочитал из файла, и совпадает с правилом фронтенда до случая
   с клиппингом включительно.
3. **Повтор не плодит объекты.** Тот же файл в ту же загрузку — успех без
   второй записи в хранилище; другой файл — отказ, а не тихая перезапись.
4. **Удаление необратимо.** Объект исчезает из хранилища, ключ — из базы, а
   отклоненная и удаленная загрузки больше ничего не принимают.

Хранилище подставное: батч хранилища идет параллельно, и его реализация здесь
не проверяется. Один тест в конце все же ходит в настоящий локальный диск —
без него «работает против интерфейса» осталось бы утверждением.
"""

from __future__ import annotations

import hashlib
import io
import re
import struct
import uuid
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.consent_versions import current_consent
from app.api.contract_app import build_contract_app
from app.api.routes import uploads as uploads_route
from app.api.schemas.enums import UploadQuality, UploadState
from app.api.schemas.uploads import MAX_UPLOAD_BYTES, UploadCompleteRequest, UploadCreateRequest
from app.db import enums as db_enums
from app.db import models
from app.db.repositories import ProjectCreate, Repositories, UserCreate
from app.services import uploads as service
from app.storage import (
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    ObjectStorage,
    StoredObject,
)

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- фикстуры и вспомогательное ---------------------------------------------


class FakeStorage(ObjectStorage):
    """Хранилище в памяти. Считает записи, чтобы дубль был виден тестом."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.put_calls = 0
        self.delete_calls = 0

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        if key in self.objects:
            raise ObjectAlreadyExistsError(key)
        self.put_calls += 1
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


class CorruptingStorage(FakeStorage):
    """Хранилище, которое отчитывается чужой контрольной суммой."""

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        stored = await super().put(key, data, content_type)
        return StoredObject(
            key=stored.key,
            size_bytes=stored.size_bytes,
            checksum_sha256=hashlib.sha256(data + b"corrupt").hexdigest(),
            content_type=stored.content_type,
        )


def wav_bytes(
    *,
    channels: int = 2,
    sample_rate: int = 44100,
    seconds: float = 0.5,
    amplitude: float = 0.5,
    sample_width: int = 2,
) -> bytes:
    """Настоящий PCM WAV: сервер читает из него и факты, и пик."""
    frames = int(sample_rate * seconds)
    value = int(round(amplitude * 32767))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(sample_width)
        target.setframerate(sample_rate)
        target.writeframes(struct.pack("<h", value) * frames * channels)
    return buffer.getvalue()


def flac_bytes(*, sample_rate: int = 44100, channels: int = 2, total_samples: int = 88200) -> bytes:
    """Заголовок FLAC без звука: проверяет чтение фактов из сжатого формата.

    Кодировщика в окружении нет, а ветка чтения тегов обязана быть проверена
    на настоящем разборе, а не на подмене функции.
    """
    packed = (sample_rate << 44) | ((channels - 1) << 41) | ((16 - 1) << 36) | total_samples
    return (
        b"fLaC"
        + bytes([0x80, 0, 0, 34])
        + struct.pack(">HH", 4096, 4096)
        + (0).to_bytes(3, "big")
        + (0).to_bytes(3, "big")
        + packed.to_bytes(8, "big")
        + b"\x00" * 16
    )


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


def create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "fileName": "track.wav",
        "sizeBytes": 4096,
        "contentType": "audio/wav",
        "consent": {"accepted": True, "versionId": current_consent().id},
    }
    payload.update(overrides)
    return payload


def build_app(session: AsyncSession, user_id: object, storage: ObjectStorage):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    app.dependency_overrides[uploads_route.object_storage] = lambda: storage
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://vokal.test"
    )


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


# --- Задача 4: оценка качества повторяет правило фронтенда --------------------


async def test_quality_repeats_frontend_rule_for_mono() -> None:
    assert (
        service.quality_from_audio(channels=1, sample_rate=48000, peak=0.5) is UploadQuality.LOW
    )


async def test_quality_repeats_frontend_rule_for_low_sample_rate() -> None:
    assert (
        service.quality_from_audio(channels=2, sample_rate=22050, peak=0.5) is UploadQuality.LOW
    )


async def test_quality_is_good_only_without_clipping() -> None:
    assert (
        service.quality_from_audio(channels=2, sample_rate=44100, peak=0.5) is UploadQuality.GOOD
    )


async def test_clipping_takes_quality_down_to_medium() -> None:
    """Пик у единицы — обычный мастеринг, а не брак: оценка «средне», не «низко»."""
    assert (
        service.quality_from_audio(channels=2, sample_rate=48000, peak=0.999)
        is UploadQuality.MEDIUM
    )
    assert (
        service.quality_from_audio(channels=2, sample_rate=48000, peak=1.0) is UploadQuality.MEDIUM
    )


async def test_quality_between_thresholds_is_medium() -> None:
    assert (
        service.quality_from_audio(channels=2, sample_rate=32000, peak=0.1) is UploadQuality.MEDIUM
    )


async def test_unknown_peak_never_becomes_good() -> None:
    """Сервер не декодирует сжатые форматы: «хорошо» без подтверждения не ставится."""
    assert (
        service.quality_from_audio(channels=2, sample_rate=48000, peak=None) is UploadQuality.MEDIUM
    )


async def test_quality_thresholds_match_frontend_source() -> None:
    """Числа правила те же, что в `src/services/audioFile.ts`.

    Правку порога на одной стороне видно здесь, а не на первом файле, который
    сервер оценит иначе, чем экран.
    """
    source = (REPO_ROOT / "src" / "services" / "audioFile.ts").read_text(encoding="utf-8")
    rule = re.search(r"qualityFromAudio\s*=\s*\(audio.*?\n};", source, re.DOTALL)
    assert rule, "в audioFile.ts не найдена функция qualityFromAudio"
    body = rule.group(0)
    assert "numberOfChannels < 2" in body
    assert "sampleRate < 32000" in body
    assert "peak >= 0.999" in body
    assert "sampleRate >= 44100" in body


# --- Задача 3: факты о записи ------------------------------------------------


async def test_facts_are_read_from_wav_including_peak() -> None:
    facts = service.read_audio_facts(wav_bytes(seconds=1.0, amplitude=0.5))
    assert facts is not None
    assert facts.sample_rate == 44100
    assert facts.channels == 2
    assert round(facts.duration_seconds) == 1
    assert facts.peak is not None
    assert 0.49 < facts.peak < 0.51


async def test_clipped_wav_is_read_as_clipping() -> None:
    facts = service.read_audio_facts(wav_bytes(amplitude=1.0))
    assert facts is not None and facts.peak is not None
    assert facts.peak >= 0.999


async def test_facts_are_read_from_compressed_header_without_peak() -> None:
    facts = service.read_audio_facts(flac_bytes(sample_rate=48000, channels=2))
    assert facts is not None
    assert facts.sample_rate == 48000
    assert facts.channels == 2
    # Выборки mutagen не декодирует: пик неизвестен, и это записано как
    # неизвестность, а не как ноль.
    assert facts.peak is None


async def test_unreadable_file_gives_no_facts_and_is_not_an_error() -> None:
    assert service.read_audio_facts(b"\x00\x01\x02 not audio at all" * 20) is None


# --- Задача 7: состояния и переходы -----------------------------------------


def _upload_row(**overrides: object) -> models.Upload:
    row = models.Upload(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        file_name="track.wav",
        file_format=db_enums.UploadFormat.WAV,
        duration_seconds=0,
        quality=db_enums.UploadQuality.LOW,
    )
    for name, value in overrides.items():
        setattr(row, name, value)
    return row


async def test_state_is_derived_from_row_without_extra_column() -> None:
    assert service.state_of(_upload_row()) is UploadState.AWAITING_FILE
    assert service.state_of(_upload_row(storage_key="source/a/b/c")) is UploadState.STORED
    assert service.state_of(_upload_row(deleted_at=datetime.now(UTC))) is UploadState.REJECTED
    assert (
        service.state_of(_upload_row(deleted_at=datetime.now(UTC), size_bytes=10))
        is UploadState.PURGED
    )


async def test_closed_states_accept_nothing() -> None:
    assert service.ALLOWED_TRANSITIONS[UploadState.REJECTED] == frozenset()
    assert service.ALLOWED_TRANSITIONS[UploadState.PURGED] == frozenset()


# --- Задача 1 и 5: заявка, отказы до тела файла ------------------------------


async def test_create_upload_returns_identifier_and_target(session: AsyncSession) -> None:
    project = await make_project(session)
    storage = FakeStorage()
    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.post(
            "/api/uploads", json=create_payload(projectId=str(project.id))
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["upload"]["id"]
    assert body["upload"]["state"] == UploadState.AWAITING_FILE.value
    assert body["upload"]["durationSeconds"] == 0
    assert body["upload"]["sizeBytes"] is None
    assert body["target"]["method"] == "PUT"
    assert body["target"]["url"].endswith(f"/api/uploads/{body['upload']['id']}/content")
    assert body["target"]["expiresAt"]


async def test_create_upload_refuses_unsupported_format(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads",
            json=create_payload(projectId=str(project.id), fileName="track.aiff"),
        )

    assert response.status_code == 422
    error = error_of(response)
    assert error["code"] == "validation_error"
    assert any("fileName" in item["field"] for item in error["details"]["fields"])


async def test_create_upload_refuses_oversized_file(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads",
            json=create_payload(projectId=str(project.id), sizeBytes=MAX_UPLOAD_BYTES + 1),
        )

    assert response.status_code == 422
    assert any(
        "sizeBytes" in item["field"] for item in error_of(response)["details"]["fields"]
    )


async def test_service_refuses_oversized_file_by_code(session: AsyncSession) -> None:
    """Та же проверка вне схемы: логика не должна зависеть от пути вызова."""
    with pytest.raises(service.UploadRefusal) as refusal:
        service.check_new_upload(file_name="track.wav", size_bytes=MAX_UPLOAD_BYTES + 1)
    assert refusal.value.status_code == 413
    assert refusal.value.code == "payload_too_large"

    with pytest.raises(service.UploadRefusal) as bad_format:
        service.check_new_upload(file_name="track.aiff", size_bytes=1024)
    assert bad_format.value.status_code == 415
    assert bad_format.value.code == "unsupported_format"


async def test_create_upload_refuses_foreign_project(session: AsyncSession) -> None:
    project = await make_project(session)
    stranger = await make_project(session, contact="other@example.test")
    async with client_for(build_app(session, stranger.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads", json=create_payload(projectId=str(project.id))
        )

    assert response.status_code == 403
    assert error_of(response)["code"] == "forbidden"


async def test_create_upload_answers_not_found_for_unknown_project(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads", json=create_payload(projectId=str(uuid.uuid4()))
        )

    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


async def test_upload_without_project_answers_named_stub(session: AsyncSession) -> None:
    """Заглушка обязана называть, чего не хватает, а не отвечать выдумкой."""
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post("/api/uploads", json=create_payload())

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    missing = " ".join(error["details"]["missing"])
    assert "uploads.project_id" in missing
    assert "upload_id" in missing


async def test_unwired_deps_answer_stub_and_name_them() -> None:
    """Без единицы работы и входа в аккаунт адрес отвечает `501`, а не `500`."""
    async with client_for(build_contract_app()) as client:
        response = await client.post("/api/uploads", json=create_payload())

    assert response.status_code == 501
    missing = " ".join(error_of(response)["details"]["missing"])
    assert "app/db/session.py" in missing
    assert "current_user_id" in missing


# --- Задача 9: согласие ------------------------------------------------------


async def test_file_is_not_accepted_without_consent(session: AsyncSession) -> None:
    project = await make_project(session)
    payload = create_payload(projectId=str(project.id))
    payload.pop("consent")
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post("/api/uploads", json=payload)

    assert response.status_code == 422
    assert error_of(response)["code"] == "consent_required"


async def test_unknown_consent_version_is_refused(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads",
            json=create_payload(
                projectId=str(project.id),
                consent={"accepted": True, "versionId": "consent-1999-01-01"},
            ),
        )

    assert response.status_code == 422
    assert any(
        "versionId" in item["field"] for item in error_of(response)["details"]["fields"]
    )


async def test_declined_consent_is_refused(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            "/api/uploads",
            json=create_payload(
                projectId=str(project.id),
                consent={"accepted": False, "versionId": current_consent().id},
            ),
        )

    assert response.status_code == 422


# --- Задача 2, 3, 4: прием тела файла ---------------------------------------


async def _make_upload(
    session: AsyncSession,
    project: models.Project,
    *,
    file_name: str = "track.wav",
    size_bytes: int = 4096,
    sample_rate: int | None = None,
    channels: int | None = None,
) -> models.Upload:
    request = UploadCreateRequest.model_validate(
        {
            "fileName": file_name,
            "sizeBytes": size_bytes,
            "sampleRate": sample_rate,
            "channels": channels,
            "consent": {"accepted": True, "versionId": current_consent().id},
        }
    )
    return await service.create_upload(
        Repositories(session), project_id=project.id, request=request
    )


async def test_stored_file_gets_checksum_size_and_facts(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    data = wav_bytes(seconds=2.0, amplitude=0.5)

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(
            f"/api/uploads/{upload.id}/content",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == UploadState.STORED.value
    assert body["sizeBytes"] == len(data)
    assert body["sampleRate"] == 44100
    assert body["channels"] == 2
    assert body["durationSeconds"] == 2
    assert body["quality"] == UploadQuality.GOOD.value

    # Ключ объекта воспроизводим и совпадает с тем, что записано в базе.
    assert storage.put_calls == 1
    [key] = list(storage.objects)
    assert upload.storage_key == key
    assert hashlib.sha256(storage.objects[key][0]).hexdigest() == hashlib.sha256(data).hexdigest()


async def test_clipped_file_is_stored_as_medium(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(
            f"/api/uploads/{upload.id}/content", content=wav_bytes(amplitude=1.0)
        )

    assert response.status_code == 200
    assert response.json()["quality"] == UploadQuality.MEDIUM.value


async def test_unreadable_file_is_accepted_without_facts(session: AsyncSession) -> None:
    """Нечитаемый формат — отсутствие фактов, а не отказ в загрузке."""
    project = await make_project(session)
    upload = await _make_upload(session, project, file_name="track.m4a")
    storage = FakeStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(
            f"/api/uploads/{upload.id}/content", content=b"\x00\x11 not audio" * 100
        )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == UploadState.STORED.value
    assert body["durationSeconds"] == 0
    assert "разобрать формат не удалось" in body["sourceNote"].lower()


async def test_client_reported_facts_are_marked_as_such(session: AsyncSession) -> None:
    """Сведения браузера сохраняются, но названы его сведениями."""
    project = await make_project(session)
    upload = await _make_upload(
        session, project, file_name="track.m4a", sample_rate=44100, channels=2
    )
    assert "браузер" in (upload.source_note or "")

    storage = FakeStorage()
    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(
            f"/api/uploads/{upload.id}/content", content=b"\x00\x11 not audio" * 100
        )

    body = response.json()
    assert body["sampleRate"] == 44100
    assert "браузер" in body["sourceNote"]


async def test_empty_body_is_refused_and_closes_upload(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        first = await client.put(f"/api/uploads/{upload.id}/content", content=b"")
        assert first.status_code == 422
        assert error_of(first)["code"] == "empty_file"
        assert storage.put_calls == 0

        state = await client.get(f"/api/uploads/{upload.id}")
        assert state.json()["state"] == UploadState.REJECTED.value

        # Задача 7: отклоненная загрузка больше ничего не принимает.
        again = await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())
        assert again.status_code == 409
        assert error_of(again)["code"] == "upload_state_conflict"


async def test_oversized_body_is_refused(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    # Данные не собираются в памяти целиком: проверяется решение, а не транспорт.
    huge = b"\x00" * (MAX_UPLOAD_BYTES + 1)

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(f"/api/uploads/{upload.id}/content", content=huge)

    assert response.status_code == 413
    assert error_of(response)["code"] == "payload_too_large"
    assert storage.put_calls == 0


async def test_expired_slot_is_refused(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    upload.created_at = datetime.now(UTC) - service.UPLOAD_SLOT_TTL - timedelta(minutes=1)
    await session.flush()
    storage = FakeStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())
        assert response.status_code == 409
        assert error_of(response)["code"] == "upload_slot_expired"
        assert storage.put_calls == 0

        state = await client.get(f"/api/uploads/{upload.id}")
        assert state.json()["state"] == UploadState.REJECTED.value


async def test_storage_that_reports_other_checksum_is_not_trusted(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = CorruptingStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        response = await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())

    assert response.status_code == 409
    assert error_of(response)["code"] == "checksum_mismatch"
    # Объект, про который хранилище сказало не то, не остается лежать.
    assert storage.objects == {}


async def test_foreign_upload_is_closed(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    stranger = await make_project(session, contact="other@example.test")

    async with client_for(build_app(session, stranger.user_id, FakeStorage())) as client:
        put = await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())
        read = await client.get(f"/api/uploads/{upload.id}")

    assert put.status_code == 403
    assert read.status_code == 403


async def test_unknown_upload_is_not_found(session: AsyncSession) -> None:
    project = await make_project(session)
    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.get(f"/api/uploads/{uuid.uuid4()}")
        strange = await client.get("/api/uploads/не-идентификатор")

    assert response.status_code == 404
    assert strange.status_code == 404


# --- Задача 6: идемпотентность ----------------------------------------------


async def test_same_file_twice_does_not_duplicate_object(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    data = wav_bytes()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        first = await client.put(f"/api/uploads/{upload.id}/content", content=data)
        second = await client.put(f"/api/uploads/{upload.id}/content", content=data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["state"] == UploadState.STORED.value
    assert storage.put_calls == 1
    assert len(storage.objects) == 1


async def test_other_file_into_stored_upload_is_refused(session: AsyncSession) -> None:
    """Перезапись означала бы, что материалы посчитаны уже по другому файлу."""
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes(seconds=0.5))
        response = await client.put(
            f"/api/uploads/{upload.id}/content", content=wav_bytes(seconds=1.0)
        )

    assert response.status_code == 409
    assert error_of(response)["code"] == "upload_state_conflict"
    assert storage.put_calls == 1


# --- Подтверждение приема ----------------------------------------------------


async def test_complete_checks_size_and_checksum(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    data = wav_bytes()
    checksum = hashlib.sha256(data).hexdigest()

    async with client_for(build_app(session, project.user_id, storage)) as client:
        await client.put(f"/api/uploads/{upload.id}/content", content=data)

        ok = await client.post(
            f"/api/uploads/{upload.id}/complete",
            json={"sizeBytes": len(data), "checksum": checksum},
        )
        wrong_size = await client.post(
            f"/api/uploads/{upload.id}/complete",
            json={"sizeBytes": len(data) - 1, "checksum": checksum},
        )
        wrong_sum = await client.post(
            f"/api/uploads/{upload.id}/complete",
            json={"sizeBytes": len(data), "checksum": "0" * 64},
        )

    assert ok.status_code == 200
    assert ok.json()["state"] == UploadState.STORED.value
    assert wrong_size.status_code == 409
    assert error_of(wrong_size)["code"] == "size_mismatch"
    assert wrong_sum.status_code == 409
    assert error_of(wrong_sum)["code"] == "checksum_mismatch"


async def test_complete_before_file_is_refused(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)

    async with client_for(build_app(session, project.user_id, FakeStorage())) as client:
        response = await client.post(
            f"/api/uploads/{upload.id}/complete", json={"sizeBytes": 4096}
        )

    assert response.status_code == 409
    assert error_of(response)["code"] == "upload_state_conflict"


# --- Задача 8: удаление исходника -------------------------------------------


async def test_purge_removes_object_and_marks_row(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    repos = Repositories(session)

    async with client_for(build_app(session, project.user_id, storage)) as client:
        await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())
    assert len(storage.objects) == 1

    purged = await service.purge_source(repos, upload, storage=storage)

    assert storage.objects == {}
    assert purged.storage_key is None
    assert purged.deleted_at is not None
    assert service.state_of(purged) is UploadState.PURGED


async def test_purge_is_irreversible_and_visible(session: AsyncSession) -> None:
    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = FakeStorage()
    repos = Repositories(session)

    async with client_for(build_app(session, project.user_id, storage)) as client:
        await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())
        await service.purge_source(repos, upload, storage=storage)

        state = await client.get(f"/api/uploads/{upload.id}")
        again = await client.put(f"/api/uploads/{upload.id}/content", content=wav_bytes())

    assert state.status_code == 200
    assert state.json()["state"] == UploadState.PURGED.value
    assert again.status_code == 409

    with pytest.raises(service.UploadRefusal) as refusal:
        await service.purge_source(repos, upload, storage=storage)
    assert refusal.value.status_code == 409


async def test_purge_of_upload_without_file_is_refused(session: AsyncSession) -> None:
    """Удалять нечего: заявка без файла закрывается не удалением исходника."""
    project = await make_project(session)
    upload = await _make_upload(session, project)

    with pytest.raises(service.UploadRefusal) as refusal:
        await service.purge_source(Repositories(session), upload, storage=FakeStorage())

    assert refusal.value.status_code == 409


# --- Настоящее хранилище -----------------------------------------------------


async def test_upload_works_against_real_local_storage(
    session: AsyncSession, tmp_path: Path
) -> None:
    """Один прогон против настоящей реализации `ObjectStorage`, а не подставной.

    Без него «работает через интерфейс хранилища» осталось бы утверждением,
    проверенным только подставным объектом, который сам себе не возражает.
    """
    from app.storage import LocalDiskStorage

    project = await make_project(session)
    upload = await _make_upload(session, project)
    storage = LocalDiskStorage(tmp_path / "storage")
    data = wav_bytes(seconds=1.0, amplitude=0.5)

    async with client_for(build_app(session, project.user_id, storage)) as client:
        stored = await client.put(f"/api/uploads/{upload.id}/content", content=data)
        confirmed = await client.post(
            f"/api/uploads/{upload.id}/complete",
            json={"sizeBytes": len(data), "checksum": hashlib.sha256(data).hexdigest()},
        )

    assert stored.status_code == 200, stored.text
    assert confirmed.status_code == 200, confirmed.text
    key = upload.storage_key
    assert key and await storage.get(key) == data

    await service.purge_source(Repositories(session), upload, storage=storage)
    # Ключ запомнен до удаления: после него в базе ключа нет вовсе, и это
    # часть обещания — по строке нельзя добраться до удаленного файла.
    assert upload.storage_key is None
    assert not await storage.exists(key)


async def test_complete_request_schema_still_names_size() -> None:
    """Подтверждение без размера не проходит: сверять было бы нечего."""
    with pytest.raises(ValueError):
        UploadCompleteRequest.model_validate({})
