"""Прием исходника: заявка, тело файла, факты о записи, качество, удаление.

Здесь лежит вся логика загрузки. Роутер только переводит отказы в коды HTTP,
а решения принимаются тут — так их можно проверить без поднятого приложения.

Три вещи, которые определяют устройство модуля.

**Файл идет через наше приложение, а не по подписанной ссылке.** Развилка
закрыта в `app/storage/base.py`: провайдер объектного хранения не выбран, и
выдавать presign против несуществующего провайдера значит показать снаружи
рабочую ссылку, за которой ничего нет. Поэтому тело файла принимает отдельный
адрес нашего API, а `UploadTarget` описывает именно его.

**Факт отличается от заявления клиента.** Браузер присылает длительность,
частоту и число каналов еще до отправки файла — это удобно, но это его слова.
Пока файла нет, они и записываются как слова браузера (`source_note` говорит
об этом прямо). Когда файл доехал, сервер читает те же величины из самого
файла, и они перекрывают заявленные. Если формат не читается, остаются слова
браузера — с указанием, чьи они.

**Состояние загрузки выводится из данных, а не хранится строкой.** В таблице
`uploads` колонки состояния нет, и заводить ее задним числом через текстовую
метку нельзя: продукт уже обжигался на подписи в роли ключа (комментарий к
`BandSetup` в `src/domain/types.ts`). Состояние читается из того, что видно:
есть ли ключ объекта, доехал ли файл (`size_bytes`), закрыта ли запись
(`deleted_at`). Таблица переходов — в `state_of` и `ALLOWED_TRANSITIONS`.
"""

from __future__ import annotations

import hashlib
import io
import sys
import uuid
import wave
from array import array
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.api.schemas.consent import ConsentAcceptance
from app.api.schemas.enums import UploadFormat, UploadQuality, UploadState
from app.api.schemas.uploads import (
    FORMAT_BY_EXTENSION,
    MAX_UPLOAD_BYTES,
    SUPPORTED_UPLOAD_EXTENSIONS,
    UploadCompleteRequest,
    UploadCreateRequest,
    UploadOut,
    extension_of,
)
from app.db import enums as db_enums
from app.db import models
from app.db.repositories import Repositories, UploadCreate, UploadPatch
from app.storage import ObjectKind, ObjectStorage, StorageError, build_key

#: Сколько живет заявка на загрузку, пока файл не доехал. Срок не украшение:
#: он уходит клиенту в `UploadTarget.expiresAt` и проверяется при приеме тела.
#: Обещать срок и не проверять его — то же самое, что не иметь срока.
UPLOAD_SLOT_TTL = timedelta(hours=24)

#: Шаг по выборкам при поиске пика. Тот же, что на фронтенде
#: (`browserDecoder` в `src/services/audioFile.ts`): на пятиминутной записи это
#: миллионы значений, и полный проход ничего не добавляет к оценке клиппинга.
PEAK_SAMPLE_STEP = 64

#: Тип содержимого по расширению — на случай, если клиент его не прислал.
#: Хранилищу тип нужен, чтобы отдать файл обратно с тем же заголовком.
CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
}

#: Допустимые переходы состояния. Все, чего здесь нет, — отказ `409`, а не
#: тихое ничего: «загрузил файл дважды в разные загрузки» и «дослал файл в
#: удаленную загрузку» это разные ошибки клиента, и молчать про них нельзя.
ALLOWED_TRANSITIONS: dict[UploadState, frozenset[UploadState]] = {
    UploadState.AWAITING_FILE: frozenset({UploadState.STORED, UploadState.REJECTED}),
    UploadState.STORED: frozenset({UploadState.PURGED}),
    UploadState.REJECTED: frozenset(),
    UploadState.PURGED: frozenset(),
}


class UploadRefusal(Exception):
    """Отказ, который клиент обязан увидеть кодом и текстом, а не как `500`.

    Код и текст задаются здесь, а не в роутере: причина отказа известна тому,
    кто отказал. Роутер только заворачивает это в общий конверт ошибки.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


# --- факты о записи ----------------------------------------------------------


@dataclass(frozen=True)
class AudioFacts:
    """Что удалось прочитать из файла.

    `peak` необязателен намеренно. Пик считается только там, где сервер
    действительно разбирает выборки (PCM WAV); для сжатых форматов декодера у
    нас нет, и подставлять сюда число значило бы выдумать факт.
    """

    duration_seconds: float
    sample_rate: int
    channels: int
    peak: float | None = None
    source: str = "файл"


def quality_from_audio(*, channels: int, sample_rate: int, peak: float | None) -> UploadQuality:
    """Та же оценка, что на фронтенде (`qualityFromAudio` в `audioFile.ts`).

    Правило повторено дословно, включая клиппинг: моно и низкая частота
    дискретизации мешают разбору по-настоящему, а пик у единицы — это обычный
    современный мастеринг, и считать его непригодностью значит забраковать
    песню, которую музыкант принес на репетицию.

    Один случай, которого на фронтенде нет: пик неизвестен. Браузер всегда
    декодирует запись и знает пик, сервер — не всегда. «Хорошо» здесь требует
    подтверждения, что клиппинга нет; неизвестное подтверждением не считается,
    поэтому такая запись остается «средней». Оценка вниз никого не введет в
    заблуждение, оценка вверх — введет.
    """
    if channels < 2 or sample_rate < 32000:
        return UploadQuality.LOW

    clipping = True if peak is None else peak >= 0.999
    return UploadQuality.GOOD if sample_rate >= 44100 and not clipping else UploadQuality.MEDIUM


def _pcm_peak(sample_width: int, frames: bytes) -> float | None:
    """Пиковая амплитуда 0..1 для несжатого PCM. `None` — разбирать нечем."""
    if not frames:
        return None
    if sample_width == 1:
        # 8-битный WAV беззнаковый: середина шкалы — 128.
        return min(max(abs(byte - 128) for byte in frames[::PEAK_SAMPLE_STEP]) / 127.0, 1.0)

    if sample_width == 2:
        samples = array("h")
        limit = 32767.0
    elif sample_width == 4:
        samples = array("i")
        limit = 2147483647.0
    else:
        # 24 бита и экзотика: без декодера пик неизвестен, и это честнее нуля.
        return None

    samples.frombytes(frames[: len(frames) - len(frames) % sample_width])
    if sys.byteorder == "big":
        # В WAV выборки лежат младшим байтом вперед, `frombytes` читает их в
        # порядке машины. На big-endian без этого получился бы чужой пик.
        samples.byteswap()
    if not samples:
        return None
    return min(max(abs(value) for value in samples[::PEAK_SAMPLE_STEP]) / limit, 1.0)


def _facts_from_wave(data: bytes) -> AudioFacts | None:
    """Несжатый WAV разбирается стандартной библиотекой — и только он.

    Ради него отдельная ветка: это единственный формат, где сервер видит сами
    выборки, а значит может честно ответить про клиппинг.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            frames_count = source.getnframes()
            sample_width = source.getsampwidth()
            frames = source.readframes(frames_count)
    except (wave.Error, EOFError, ValueError):
        return None

    if not channels or not sample_rate or not frames_count:
        return None

    return AudioFacts(
        duration_seconds=frames_count / sample_rate,
        sample_rate=sample_rate,
        channels=channels,
        peak=_pcm_peak(sample_width, frames),
    )


def _facts_from_tags(data: bytes) -> AudioFacts | None:
    """Заголовки сжатых форматов читает mutagen: MP3, FLAC, M4A.

    Выборки mutagen не декодирует, поэтому пик остается неизвестным — так и
    записываем, вместо того чтобы подставить ноль и объявить запись «хорошей».
    """
    try:
        import mutagen
    except ImportError:  # pragma: no cover - зависимость объявлена в pyproject
        return None

    try:
        parsed = mutagen.File(io.BytesIO(data))
    except Exception:
        # mutagen поднимает свои исключения на каждый формат; для нас все они
        # означают одно: фактов нет. Ошибкой загрузки это не является.
        return None

    info = getattr(parsed, "info", None)
    if info is None:
        return None

    duration = getattr(info, "length", None)
    sample_rate = getattr(info, "sample_rate", None)
    channels = getattr(info, "channels", None)
    if not duration or not sample_rate or not channels:
        return None

    return AudioFacts(
        duration_seconds=float(duration),
        sample_rate=int(sample_rate),
        channels=int(channels),
        peak=None,
    )


def read_audio_facts(data: bytes) -> AudioFacts | None:
    """Факты о записи из самого файла. `None` — прочитать не удалось.

    Нечитаемый формат не отменяет загрузку: файл принят, а фактов о нем нет,
    и в интерфейсе это видно по `source_note`. Отказать здесь значило бы не
    принять рабочий файл из-за того, что мы не умеем его разобрать.
    """
    return _facts_from_wave(data) or _facts_from_tags(data)


def _facts_from_client(request: UploadCreateRequest) -> AudioFacts | None:
    """Сведения, которые прислал браузер. Это заявление, а не факт."""
    if not request.sample_rate or not request.channels:
        return None
    return AudioFacts(
        duration_seconds=float(request.duration_seconds or 0),
        sample_rate=request.sample_rate,
        channels=request.channels,
        peak=None,
        source="браузер",
    )


def source_note_for(facts: AudioFacts | None, *, arrived: bool) -> str:
    """Пояснение о происхождении сведений — то, что увидит пользователь."""
    if facts is None:
        if not arrived:
            return "Файл еще не отправлен. Сведений о записи нет."
        return (
            "Файл принят. Разобрать формат не удалось: длительность, частота и каналы "
            "неизвестны, оценка качества не сделана."
        )
    if facts.source == "браузер":
        prefix = "Файл еще не отправлен. " if not arrived else "Файл принят. "
        return prefix + "Сведения о записи получены от браузера и сервером не проверены."
    return "Файл принят. Сведения о записи прочитаны сервером из самого файла."


# --- состояние загрузки ------------------------------------------------------


def state_of(upload: models.Upload) -> UploadState:
    """Состояние выводится из данных строки, а не хранится отдельным полем.

    Разбор случаев:

    - запись закрыта (`deleted_at`) и файл когда-то доехал (`size_bytes`) —
      исходник удален физически, это `purged`;
    - запись закрыта, а файл не доезжал — сервер отказался его принять,
      это `rejected`;
    - ключ объекта есть — файл лежит в хранилище, это `stored`;
    - иначе заявка есть, файла нет: `awaiting_file`.
    """
    if upload.deleted_at is not None:
        return UploadState.PURGED if upload.size_bytes is not None else UploadState.REJECTED
    return UploadState.STORED if upload.storage_key else UploadState.AWAITING_FILE


def _require_transition(upload: models.Upload, target: UploadState) -> None:
    current = state_of(upload)
    if target in ALLOWED_TRANSITIONS[current]:
        return
    raise UploadRefusal(
        409,
        "upload_state_conflict",
        _TRANSITION_MESSAGES.get(
            current, "Состояние загрузки не позволяет выполнить эту операцию."
        ),
        details={"state": current.value, "requested": target.value},
    )


_TRANSITION_MESSAGES: dict[UploadState, str] = {
    UploadState.STORED: "Файл для этой загрузки уже принят. Заведите новую загрузку.",
    UploadState.REJECTED: "Эта загрузка отклонена. Заведите новую и отправьте файл заново.",
    UploadState.PURGED: "Исходник удален без возможности восстановления.",
    UploadState.AWAITING_FILE: "Файл этой загрузки еще не принят.",
}


# --- заявка на загрузку ------------------------------------------------------


def check_consent(consent: ConsentAcceptance | None) -> ConsentAcceptance:
    """Без записанного согласия чужая фонограмма на диск не ложится.

    Версию формулировки проверяет схема (`ConsentAcceptance`): неизвестная
    версия — отказ, а не молчаливый прием. Здесь остается случай, когда
    согласия нет вовсе: принять файл «пока так» нельзя, потому что задним
    числом запись о согласии не восстанавливается.
    """
    if consent is None:
        raise UploadRefusal(
            422,
            "consent_required",
            "Файл не принимается без согласия. Запросите действующую версию "
            "у GET /api/consent/current и покажите ее пользователю.",
            details={"fields": [{"field": "body.consent", "reason": "обязательное поле"}]},
        )
    return consent


def check_new_upload(*, file_name: str, size_bytes: int) -> None:
    """Формат и размер проверяются до тела файла — в этом весь смысл заявки.

    Схема `UploadCreateRequest` проверяет то же самое и отвечает `422`. Проверка
    повторена здесь потому, что логика не должна зависеть от того, каким путем
    в нее пришли: вызов из другого места (перенос, повторная отправка) обязан
    получить тот же отказ.
    """
    extension = extension_of(file_name)
    if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
        raise UploadRefusal(
            415,
            "unsupported_format",
            f"Формат .{extension or '?'} не поддерживается. Подойдут MP3, WAV, FLAC или M4A.",
            details={"allowedExtensions": list(SUPPORTED_UPLOAD_EXTENSIONS)},
        )
    if size_bytes > MAX_UPLOAD_BYTES:
        raise UploadRefusal(
            413,
            "payload_too_large",
            f"Файл больше {MAX_UPLOAD_BYTES // 1024 // 1024} МБ.",
            details={"maxSizeBytes": MAX_UPLOAD_BYTES},
        )
    if size_bytes <= 0:
        raise UploadRefusal(
            422,
            "empty_file",
            "Файл пустой. Выберите запись со звуком.",
        )


def format_of(file_name: str) -> UploadFormat:
    return FORMAT_BY_EXTENSION[extension_of(file_name)]


async def create_upload(
    repos: Repositories,
    *,
    project_id: uuid.UUID,
    request: UploadCreateRequest,
) -> models.Upload:
    """Заводит заявку на загрузку: файла еще нет, состояние `awaiting_file`.

    В строку не записывается ничего, чего мы не знаем. Длительность остается
    нулем (контракт прямо разрешает ноль как «неизвестно»), а частота и каналы
    берутся из слов браузера — и `source_note` говорит, что это его слова.
    """
    check_consent(request.consent)
    check_new_upload(file_name=request.file_name, size_bytes=request.size_bytes)

    facts = _facts_from_client(request)
    # Колонка качества обязательна и в базе, и в контракте, а оценивать пока
    # нечего. Из трех значений берется то, которое ничего не обещает: оценка
    # вниз никого не введет в заблуждение, а «хорошо» на месте неизвестности —
    # введет. Что оценки еще нет, сказано состоянием и `source_note`.
    quality = (
        quality_from_audio(channels=facts.channels, sample_rate=facts.sample_rate, peak=facts.peak)
        if facts is not None
        else UploadQuality.LOW
    )

    return await repos.uploads.create(
        UploadCreate(
            project_id=project_id,
            file_name=request.file_name,
            file_format=db_enums.UploadFormat(format_of(request.file_name).value),
            # Ноль, а не заявленная браузером длительность: пока файла нет,
            # длительность нечем подтвердить.
            duration_seconds=0,
            quality=db_enums.UploadQuality(quality.value),
            source_note=source_note_for(facts, arrived=False),
            sample_rate=facts.sample_rate if facts else None,
            channels=facts.channels if facts else None,
        )
    )


def slot_expires_at(upload: models.Upload) -> datetime:
    created = upload.created_at
    if created.tzinfo is None:  # pragma: no cover - база отдает время с зоной
        created = created.replace(tzinfo=UTC)
    return created + UPLOAD_SLOT_TTL


# --- прием тела файла --------------------------------------------------------


def checksum_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def storage_key_for(upload: models.Upload) -> str:
    """Ключ объекта строится по схеме батча хранилища (`app/storage/keys.py`).

    Идентификатором объекта берется идентификатор загрузки, а не случайное
    число: ключ обязан быть воспроизводимым. Иначе повторная отправка того же
    файла положила бы в хранилище второй объект, а первый остался бы висеть
    без ссылки — и его никто уже не удалит.
    """
    return build_key(
        ObjectKind.SOURCE,
        upload.project_id,
        object_id=upload.id.hex,
        file_name=upload.file_name,
    )


async def _reject(repos: Repositories, upload: models.Upload, note: str) -> None:
    """Закрывает загрузку отказом. Необратимо: повторная отправка не примется."""
    await repos.uploads.update(upload.id, UploadPatch(source_note=note))
    await repos.uploads.soft_delete(upload.id)


async def store_file(
    repos: Repositories,
    upload: models.Upload,
    *,
    data: bytes,
    content_type: str | None,
    storage: ObjectStorage,
) -> models.Upload:
    """Принимает тело файла: пишет в хранилище, читает факты, ставит оценку.

    Повторная отправка того же файла в ту же загрузку дублей не создает: ключ
    объекта воспроизводим, и если по нему уже лежит тот же файл, второй записи
    не происходит. Другой файл в ту же загрузку — отказ `409`, а не тихая
    перезапись: перезапись означала бы, что материалы, посчитанные по первому
    файлу, молча относятся уже к другому.
    """
    current = state_of(upload)
    if current is UploadState.STORED:
        return await _store_again(upload, data=data, storage=storage)
    _require_transition(upload, UploadState.STORED)

    if datetime.now(tz=UTC) > slot_expires_at(upload):
        await _reject(repos, upload, "Загрузка отклонена: срок отправки файла истек.")
        raise UploadRefusal(
            409,
            "upload_slot_expired",
            "Срок отправки файла истек. Заведите загрузку заново.",
            details={"expiresAt": slot_expires_at(upload).isoformat()},
        )

    if not data:
        await _reject(repos, upload, "Загрузка отклонена: файл пустой.")
        raise UploadRefusal(422, "empty_file", "Файл пустой. Выберите запись со звуком.")

    # Второй рубеж по размеру. Первый — `BodySizeLimitMiddleware`, он режет
    # тело до обработчика по Content-Length. Но предел посредника задается
    # переменной окружения и может оказаться шире нашего, а на приложении без
    # посредника (сборка контракта) его нет вовсе.
    if len(data) > MAX_UPLOAD_BYTES:
        await _reject(repos, upload, "Загрузка отклонена: файл больше допустимого размера.")
        raise UploadRefusal(
            413,
            "payload_too_large",
            f"Файл больше {MAX_UPLOAD_BYTES // 1024 // 1024} МБ.",
            details={"maxSizeBytes": MAX_UPLOAD_BYTES},
        )

    key = storage_key_for(upload)
    checksum = checksum_of(data)
    try:
        stored = await storage.put(
            key,
            data,
            content_type or CONTENT_TYPE_BY_EXTENSION.get(
                extension_of(upload.file_name), "application/octet-stream"
            ),
        )
    except StorageError as error:
        raise UploadRefusal(
            503,
            "storage_unavailable",
            "Не удалось записать файл в хранилище. Повторите отправку.",
            details={"reason": type(error).__name__},
        ) from error

    if stored.checksum_sha256 != checksum:
        # Хранилище приняло не то, что мы отправили. Оставлять такой объект
        # нельзя: он неотличим от исправного, пока кто-нибудь не откроет файл.
        await storage.delete(key)
        raise UploadRefusal(
            409,
            "checksum_mismatch",
            "Хранилище приняло не тот файл, который был отправлен. Повторите отправку.",
        )

    return await _record_stored(repos, upload, stored_size=stored.size_bytes, key=key, data=data)


async def _store_again(
    upload: models.Upload,
    *,
    data: bytes,
    storage: ObjectStorage,
) -> models.Upload:
    """Повторная отправка в загрузку, где файл уже лежит.

    Тот же файл — успех без второй записи в хранилище (обрыв связи на ответе
    не должен превращаться в дубль). Другой файл — отказ.
    """
    key = upload.storage_key or storage_key_for(upload)
    try:
        existing = await storage.get(key)
    except StorageError:
        existing = b""

    if existing and checksum_of(existing) == checksum_of(data):
        return upload

    raise UploadRefusal(
        409,
        "upload_state_conflict",
        _TRANSITION_MESSAGES[UploadState.STORED],
        details={"state": UploadState.STORED.value, "requested": UploadState.STORED.value},
    )


async def _record_stored(
    repos: Repositories,
    upload: models.Upload,
    *,
    stored_size: int,
    key: str,
    data: bytes,
) -> models.Upload:
    facts = read_audio_facts(data)
    if facts is None:
        # Формат не разобран. Это не отказ: файл принят, а фактов о нем нет.
        # Если браузер что-то сообщил при заявке, оставляем его сведения и
        # прямо говорим, чьи они.
        client_facts = (
            AudioFacts(
                duration_seconds=float(upload.duration_seconds),
                sample_rate=upload.sample_rate,
                channels=upload.channels,
                source="браузер",
            )
            if upload.sample_rate and upload.channels
            else None
        )
        return await repos.uploads.update(
            upload.id,
            UploadPatch(
                storage_key=key,
                size_bytes=stored_size,
                source_note=source_note_for(client_facts, arrived=True),
            ),
        )

    quality = quality_from_audio(
        channels=facts.channels, sample_rate=facts.sample_rate, peak=facts.peak
    )
    updated = await repos.uploads.update(
        upload.id,
        UploadPatch(
            storage_key=key,
            size_bytes=stored_size,
            sample_rate=facts.sample_rate,
            channels=facts.channels,
            quality=db_enums.UploadQuality(quality.value),
            source_note=source_note_for(facts, arrived=True),
        ),
    )
    return await _set_duration(repos, updated, int(facts.duration_seconds))


async def _set_duration(
    repos: Repositories, upload: models.Upload, seconds: int
) -> models.Upload:
    """Длительность записывается в обход набора полей `UploadPatch`.

    В наборе такого поля нет, а завести его — правка `app/db/repositories.py`,
    то есть чужой зоны. Ставить вместо настоящей длительности ноль нельзя:
    ноль в контракте означает «неизвестно», и файл, который сервер прочитал,
    выглядел бы неразобранным.
    """
    upload.duration_seconds = max(0, seconds)
    await repos.uploads.session.flush()
    return upload


async def complete_upload(
    repos: Repositories,
    upload: models.Upload,
    payload: UploadCompleteRequest,
    *,
    storage: ObjectStorage,
) -> models.Upload:
    """Подтверждение приема: клиент называет размер и сумму, сервер сверяет.

    Шаг не формальный. Оборванная передача дает файл, который выглядит целым:
    размер меньше, а формат читается. Сверка с тем, что насчитал клиент, — это
    единственное место, где такой обрыв виден.
    """
    current = state_of(upload)
    if current is not UploadState.STORED:
        raise UploadRefusal(
            409,
            "upload_state_conflict",
            _TRANSITION_MESSAGES[current],
            details={"state": current.value},
        )

    if upload.size_bytes != payload.size_bytes:
        raise UploadRefusal(
            409,
            "size_mismatch",
            "Размер принятого файла не совпал с заявленным. Отправьте файл заново.",
            details={"storedBytes": upload.size_bytes, "reportedBytes": payload.size_bytes},
        )

    if payload.checksum:
        try:
            data = await storage.get(upload.storage_key or "")
        except StorageError as error:
            raise UploadRefusal(
                503,
                "storage_unavailable",
                "Не удалось перечитать файл в хранилище. Повторите подтверждение.",
                details={"reason": type(error).__name__},
            ) from error
        if checksum_of(data) != payload.checksum.lower():
            raise UploadRefusal(
                409,
                "checksum_mismatch",
                "Контрольная сумма принятого файла не совпала. Отправьте файл заново.",
            )

    return upload


# --- удаление исходника ------------------------------------------------------


async def purge_source(
    repos: Repositories,
    upload: models.Upload,
    *,
    storage: ObjectStorage,
) -> models.Upload:
    """Физически удаляет объект и закрывает запись. Необратимо.

    Порядок именно такой: сначала хранилище, потом отметка. Пометить удаленным
    то, что осталось лежать, значит сказать пользователю неправду о необратимой
    операции (`docs/DELETION_AND_RETENTION_DESIGN.md`).

    Ключ обнуляется вместе с отметкой: пока ключ лежит в базе, по нему можно
    выдать файл, которого, как мы уже сказали, нет.
    """
    _require_transition(upload, UploadState.PURGED)

    key = upload.storage_key
    if key:
        try:
            await storage.delete(key)
        except StorageError as error:
            raise UploadRefusal(
                503,
                "storage_unavailable",
                "Не удалось удалить файл из хранилища. Повторите запрос.",
                details={"reason": type(error).__name__},
            ) from error

    await repos.uploads.update(upload.id, UploadPatch(storage_key=None))
    return await repos.uploads.soft_delete(upload.id)


# --- представление -----------------------------------------------------------


def to_out(upload: models.Upload) -> UploadOut:
    """Строка таблицы в ответ контракта."""
    return UploadOut(
        id=str(upload.id),
        file_name=upload.file_name,
        format=UploadFormat(upload.file_format.value),
        state=state_of(upload),
        duration_seconds=upload.duration_seconds,
        quality=UploadQuality(upload.quality.value),
        source_note=upload.source_note or "",
        size_bytes=upload.size_bytes,
        sample_rate=upload.sample_rate,
        channels=upload.channels,
        created_at=upload.created_at,
    )
