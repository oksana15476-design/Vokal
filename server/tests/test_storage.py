"""Тесты хранилища объектов.

Почему все в одном файле: зона батча — `app/storage/**` и этот файл.

Что здесь проверяется в первую очередь — не «функция вызвалась», а три вещи,
на которых хранилище ломается молча:

1. **Порча файла не проходит незамеченной.** Байт на диске может измениться
   без нашего участия; отдать испорченную фонограмму как исправную — хуже, чем
   отказать. Поэтому есть тест, который портит файл руками.
2. **Ключ не выводит за корень.** `../../etc/passwd` и симлинк наружу — два
   разных способа выйти, и закрыт должен быть каждый.
3. **Подписанная ссылка либо настоящая, либо `None`.** Правило из `base.py`:
   выдуманный адрес снаружи неотличим от рабочего.

Тесты S3 не ходят в сеть. Подпись ссылки считается локально, а недоступность
эндпоинта проверяется отказом на этапе конструктора: класс обязан падать без
настроек, а не делать вид.
"""

from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.storage import (
    ChecksumMismatchError,
    InvalidKeyError,
    LocalDiskStorage,
    ObjectAlreadyExistsError,
    ObjectKind,
    ObjectNotFoundError,
    S3CompatibleStorage,
    StorageConfigurationError,
    StorageError,
    StorageSettings,
    build_key,
    create_storage,
    find_expired,
    parse_key,
    validate_key,
)
from app.storage.retention import RESULTS_DAYS, SOURCE_DAYS

WAV = "audio/wav"


def _project_id() -> str:
    return uuid.uuid4().hex


def _local(tmp_path: Path) -> LocalDiskStorage:
    return LocalDiskStorage(tmp_path / "storage")


# --- Ключи объектов ------------------------------------------------------


def test_build_key_separates_kinds_and_projects() -> None:
    project = _project_id()
    source = build_key(ObjectKind.SOURCE, project, file_name="song.mp3")
    results = build_key(ObjectKind.RESULTS, project, file_name="song.mp3")

    assert source.startswith("source/")
    assert results.startswith("results/")
    assert project in source
    assert source != results


def test_build_key_survives_identical_file_names_of_different_users() -> None:
    """Два пользователя грузят «Песня.mp3» — ключи обязаны разойтись."""
    first = build_key(ObjectKind.SOURCE, _project_id(), file_name="Песня.mp3")
    second = build_key(ObjectKind.SOURCE, _project_id(), file_name="Песня.mp3")

    assert first != second
    # Имя файла в ключ не попадает вовсе: по ключу нельзя узнать, как
    # пользователь назвал свою фонограмму.
    assert "Песня" not in first
    assert "песня" not in first.lower()


def test_build_key_survives_identical_file_names_inside_one_project() -> None:
    """Тот же проект, то же имя, вторая загрузка — ключ обязан быть другим."""
    project = _project_id()
    first = build_key(ObjectKind.SOURCE, project, file_name="Песня.mp3")
    second = build_key(ObjectKind.SOURCE, project, file_name="Песня.mp3")

    assert first != second


def test_build_key_keeps_extension_only() -> None:
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="Мастер FINAL.WAV")
    assert key.endswith(".wav")


def test_build_key_without_file_name_has_no_extension() -> None:
    key = build_key(ObjectKind.RESULTS, _project_id())
    assert "." not in key.rsplit("/", 1)[-1]


def test_build_key_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        build_key("логи-которых-нет", _project_id())  # type: ignore[arg-type]


def test_build_key_rejects_non_hex_project_id() -> None:
    """Идентификатор проекта — UUID. Иначе шардирование ключа теряет смысл."""
    with pytest.raises(InvalidKeyError):
        build_key(ObjectKind.SOURCE, "../../etc")


def test_parse_key_round_trip() -> None:
    project = _project_id()
    key = build_key(ObjectKind.SOURCE, project, file_name="song.flac")
    parsed = parse_key(key)

    assert parsed.kind is ObjectKind.SOURCE
    assert parsed.project_id == project
    assert parsed.extension == "flac"


BAD_KEYS = [
    "../../etc/passwd",
    "source/../../etc/passwd",
    "/etc/passwd",
    "source/..",
    "source//song.mp3",
    "source/./song.mp3",
    "source\\..\\etc",
    "",
    "   ",
    "source/song\x00.mp3",
    "source/" + "a" * 600,
]


@pytest.mark.parametrize("key", BAD_KEYS)
def test_invalid_keys_are_rejected_by_validation(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)


@pytest.mark.parametrize("key", BAD_KEYS)
def test_invalid_keys_are_rejected_by_parsing(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        parse_key(key)


@pytest.mark.parametrize("key", BAD_KEYS)
@pytest.mark.asyncio
async def test_storage_refuses_to_write_by_invalid_key(key: str, tmp_path: Path) -> None:
    """Тот же список — но через запись: именно тут ключ становится путем."""
    storage = _local(tmp_path)

    with pytest.raises(InvalidKeyError):
        await storage.put(key, b"payload", WAV)


# --- Локальный диск: запись и чтение -------------------------------------


@pytest.mark.asyncio
async def test_put_then_get_returns_same_bytes(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    data = b"RIFF....WAVEfmt " * 64

    stored = await storage.put(key, data, WAV)

    assert stored.key == key
    assert stored.size_bytes == len(data)
    assert stored.checksum_sha256 == hashlib.sha256(data).hexdigest()
    assert stored.content_type == WAV
    assert await storage.get(key) == data


@pytest.mark.asyncio
async def test_put_refuses_to_overwrite(tmp_path: Path) -> None:
    """Перезапись ключа запрещена: старый артефакт кто-то уже мог скачать."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "первый".encode(), WAV)

    with pytest.raises(ObjectAlreadyExistsError):
        await storage.put(key, "второй".encode(), WAV)

    assert await storage.get(key) == "первый".encode()


@pytest.mark.asyncio
async def test_get_missing_object_raises(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")

    with pytest.raises(ObjectNotFoundError):
        await storage.get(key)


@pytest.mark.asyncio
async def test_exists_reflects_reality(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")

    assert await storage.exists(key) is False
    await storage.put(key, "данные".encode(), WAV)
    assert await storage.exists(key) is True


@pytest.mark.asyncio
async def test_stat_returns_content_type_and_retention(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    before = datetime.now(UTC)

    await storage.put(key, "данные".encode(), WAV)
    record = await storage.stat(key)

    assert record.content_type == WAV
    assert record.retention_until >= before + timedelta(days=SOURCE_DAYS - 1)


# --- Контрольная сумма ---------------------------------------------------


@pytest.mark.asyncio
async def test_corrupted_file_is_not_returned_as_valid(tmp_path: Path) -> None:
    """Главный тест модуля: молчаливая порция байтов недопустима."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "исходные данные песни".encode(), WAV)

    path = storage.path_for(key)
    path.write_bytes("подмененные данные!!!".encode())

    with pytest.raises(ChecksumMismatchError) as error:
        await storage.get(key)
    assert key in str(error.value)


@pytest.mark.asyncio
async def test_lost_metadata_is_reported_not_ignored(tmp_path: Path) -> None:
    """Без записанной суммы читать нечем: это отказ, а не «сумма совпала»."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "данные".encode(), WAV)

    storage.metadata_path_for(key).unlink()

    with pytest.raises(ObjectNotFoundError):
        await storage.get(key)


@pytest.mark.asyncio
async def test_put_repairs_an_object_left_without_metadata(tmp_path: Path) -> None:
    """Остаток оборванной укладки перезаписывается: отдать его все равно нельзя."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "первая попытка".encode(), WAV)
    storage.metadata_path_for(key).unlink()

    await storage.put(key, "вторая попытка".encode(), WAV)

    assert await storage.get(key) == "вторая попытка".encode()


@pytest.mark.asyncio
async def test_metadata_of_another_object_is_refused(tmp_path: Path) -> None:
    """Запись метаданных обязана называть свой ключ.

    Содержимое у объектов здесь одинаковое, поэтому сумма сходится и подмену
    ловит только сверка ключа. Цена пропуска — уборщик по сроку хранения
    получает чужое имя и удаляет не тот файл.
    """
    storage = _local(tmp_path)
    project = _project_id()
    first = build_key(ObjectKind.SOURCE, project, file_name="a.wav")
    second = build_key(ObjectKind.SOURCE, project, file_name="b.wav")
    same_bytes = "одинаковое содержимое".encode()
    await storage.put(first, same_bytes, WAV)
    await storage.put(second, same_bytes, WAV)

    storage.metadata_path_for(second).write_text(
        storage.metadata_path_for(first).read_text(encoding="utf-8"), encoding="utf-8"
    )

    with pytest.raises(StorageError, match="ключ"):
        await storage.get(second)


# --- Выход за корень -----------------------------------------------------


@pytest.mark.asyncio
async def test_traversal_key_writes_nothing_outside_root(tmp_path: Path) -> None:
    storage = LocalDiskStorage(tmp_path / "storage")
    victim = tmp_path / "victim.txt"
    victim.write_text("нетронутый", encoding="utf-8")

    with pytest.raises(InvalidKeyError):
        await storage.put("../victim.txt", "взлом".encode(), WAV)

    assert victim.read_text(encoding="utf-8") == "нетронутый"


@pytest.mark.asyncio
async def test_symlink_out_of_root_is_refused(tmp_path: Path) -> None:
    """Синтаксис ключа чист, а путь все равно уходит наружу — второй рубеж."""
    storage = _local(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    escape = storage.root / "objects" / "source"
    escape.parent.mkdir(parents=True, exist_ok=True)
    escape.symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidKeyError):
        await storage.put("source/ab/deadbeef/x.bin", "взлом".encode(), WAV)

    assert list(outside.iterdir()) == []


# --- Удаление ------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_object_and_reports_true(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "данные".encode(), WAV)

    assert await storage.delete(key) is True
    assert await storage.exists(key) is False
    assert not storage.path_for(key).exists()
    assert not storage.metadata_path_for(key).exists()


@pytest.mark.asyncio
async def test_delete_missing_object_returns_false(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")

    assert await storage.delete(key) is False


@pytest.mark.asyncio
async def test_delete_sweeps_empty_directories_but_keeps_root(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    project = _project_id()
    key = build_key(ObjectKind.SOURCE, project, file_name="song.wav")
    await storage.put(key, "данные".encode(), WAV)
    project_dir = storage.path_for(key).parent

    await storage.delete(key)

    assert not project_dir.exists()
    assert not project_dir.parent.exists()
    assert storage.root.exists()


@pytest.mark.asyncio
async def test_delete_keeps_neighbours_of_the_same_project(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    project = _project_id()
    first = build_key(ObjectKind.SOURCE, project, file_name="a.wav")
    second = build_key(ObjectKind.SOURCE, project, file_name="b.wav")
    await storage.put(first, "первый".encode(), WAV)
    await storage.put(second, "второй".encode(), WAV)

    await storage.delete(first)

    assert await storage.get(second) == "второй".encode()


@pytest.mark.asyncio
async def test_local_root_hides_itself_from_git(tmp_path: Path) -> None:
    """Корень по умолчанию относительный и может оказаться внутри репозитория.

    Чужая фонограмма, попавшая в историю git, оттуда уже не убирается: история
    необратима. Поэтому корень закрывается от git сам, а не надеется на то,
    что кто-то не забудет строку в `.gitignore`.
    """
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")

    await storage.put(key, "фонограмма".encode(), WAV)

    marker = storage.root / ".gitignore"
    assert marker.is_file()
    assert "*" in marker.read_text(encoding="utf-8").split()


# --- Подписанная ссылка --------------------------------------------------


@pytest.mark.asyncio
async def test_local_disk_has_no_signed_url(tmp_path: Path) -> None:
    """Контракт `base.py`: локальный диск честно отвечает `None`."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "данные".encode(), WAV)

    assert await storage.signed_url(key, 600) is None


# --- Уборка по сроку хранения --------------------------------------------


@pytest.mark.asyncio
async def test_find_expired_returns_only_overdue_objects(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    project = _project_id()
    source = build_key(ObjectKind.SOURCE, project, file_name="song.wav")
    results = build_key(ObjectKind.RESULTS, project, file_name="pack.zip")
    await storage.put(source, "исходник".encode(), WAV)
    await storage.put(results, "результат".encode(), "application/zip")

    # День после срока исходника, но задолго до срока результатов.
    moment = datetime.now(UTC) + timedelta(days=SOURCE_DAYS + 1)
    expired = await find_expired(storage, now=moment)

    assert [record.key for record in expired] == [source]


@pytest.mark.asyncio
async def test_find_expired_is_empty_before_the_deadline(tmp_path: Path) -> None:
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "исходник".encode(), WAV)

    assert await find_expired(storage, now=datetime.now(UTC)) == []


@pytest.mark.asyncio
async def test_find_expired_deletes_nothing(tmp_path: Path) -> None:
    """Функция только находит. Удаляет планировщик, которого еще нет."""
    storage = _local(tmp_path)
    key = build_key(ObjectKind.SOURCE, _project_id(), file_name="song.wav")
    await storage.put(key, "исходник".encode(), WAV)

    await find_expired(storage, now=datetime.now(UTC) + timedelta(days=RESULTS_DAYS + 1))

    assert await storage.exists(key) is True


# --- Выбор реализации по настройкам --------------------------------------


def test_default_backend_is_local_disk(tmp_path: Path) -> None:
    settings = StorageSettings(_env_file=None, local_root=tmp_path)

    assert settings.backend == "local"
    assert isinstance(create_storage(settings), LocalDiskStorage)


def test_backend_is_chosen_by_one_environment_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VOKAL_STORAGE_BACKEND", "s3")
    monkeypatch.setenv("VOKAL_STORAGE_LOCAL_ROOT", str(tmp_path))

    assert StorageSettings(_env_file=None).backend == "s3"


def test_unknown_backend_fails_loudly(tmp_path: Path) -> None:
    settings = StorageSettings(_env_file=None, backend="дискета", local_root=tmp_path)

    with pytest.raises(StorageConfigurationError) as error:
        create_storage(settings)
    assert "local" in str(error.value)


def test_local_root_comes_from_settings(tmp_path: Path) -> None:
    settings = StorageSettings(_env_file=None, local_root=tmp_path / "выбранный-корень")
    storage = create_storage(settings)

    assert isinstance(storage, LocalDiskStorage)
    assert storage.root == tmp_path / "выбранный-корень"


# --- S3-совместимое хранилище --------------------------------------------


def _s3_settings(**overrides: object) -> StorageSettings:
    values: dict[str, object] = {
        "_env_file": None,
        "backend": "s3",
        "s3_endpoint_url": "https://storage.yandexcloud.net",
        "s3_bucket": "vokal-test",
        "s3_region": "ru-central1",
        "s3_access_key_id": "TEST_KEY_ID",
        "s3_secret_access_key": "TEST_SECRET",
    }
    values.update(overrides)
    return StorageSettings(**values)  # type: ignore[arg-type]


def test_s3_without_settings_fails_at_construction() -> None:
    """Подключаться некуда — значит отказ сразу, а не притворство."""
    settings = StorageSettings(_env_file=None, backend="s3")

    with pytest.raises(StorageConfigurationError) as error:
        S3CompatibleStorage(settings)
    message = str(error.value)
    assert "VOKAL_STORAGE_S3_BUCKET" in message
    assert "VOKAL_STORAGE_S3_ENDPOINT_URL" in message


def test_s3_without_credentials_fails_at_construction() -> None:
    settings = _s3_settings(s3_access_key_id=None, s3_secret_access_key=None)

    with pytest.raises(StorageConfigurationError) as error:
        S3CompatibleStorage(settings)
    assert "VOKAL_STORAGE_S3_ACCESS_KEY_ID" in str(error.value)


def test_s3_without_boto3_fails_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Библиотеки нет — отказ с названием пакета, а не `ImportError` из недр."""
    monkeypatch.setitem(sys.modules, "boto3", None)

    with pytest.raises(StorageConfigurationError) as error:
        S3CompatibleStorage(_s3_settings())
    assert "boto3" in str(error.value)


@pytest.mark.asyncio
async def test_s3_signed_url_is_a_real_signature() -> None:
    """У S3 ссылка настоящая: подпись считается локально, сеть не нужна."""
    storage = S3CompatibleStorage(_s3_settings())
    key = build_key(ObjectKind.RESULTS, _project_id(), file_name="pack.zip")

    url = await storage.signed_url(key, 900)

    assert url is not None
    assert url.startswith("https://")
    assert "vokal-test" in url
    assert key in url
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Expires=900" in url


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["signed_url", "get", "delete", "exists", "put"])
async def test_s3_rejects_traversal_keys_before_any_request(operation: str) -> None:
    """Ключ отбраковывается до сети: иначе проверка зависит от доступности бакета."""
    storage = S3CompatibleStorage(_s3_settings())
    calls = {
        "signed_url": lambda: storage.signed_url("../../etc/passwd", 900),
        "get": lambda: storage.get("../../etc/passwd"),
        "delete": lambda: storage.delete("../../etc/passwd"),
        "exists": lambda: storage.exists("../../etc/passwd"),
        "put": lambda: storage.put("../../etc/passwd", b"x", WAV),
    }

    with pytest.raises(InvalidKeyError):
        await calls[operation]()


def test_s3_is_selected_by_settings() -> None:
    assert isinstance(create_storage(_s3_settings()), S3CompatibleStorage)
