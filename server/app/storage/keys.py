"""Схема ключей объектов.

Ключ выглядит так::

    {род}/{шард}/{идентификатор проекта}/{идентификатор объекта}[.расширение]
    source/3f/3f7a1c.../9b2e4d....mp3

Почему так, а не «имя файла в папке пользователя»:

- **Имя файла в ключ не попадает вовсе.** Два преподавателя грузят
  «Песня.mp3» — ключи обязаны разойтись, иначе второй перезапишет первого.
  Идентификатор объекта — свежий UUID, поэтому совпасть ключи не могут даже
  внутри одного проекта. Заодно по ключу нельзя прочитать, как пользователь
  назвал свою фонограмму: ключ утекает в логи и метрики легче, чем содержимое.
- **Род объекта — первый сегмент.** Исходник и производные материалы живут по
  разным срокам хранения (`retention.py`), и срок обязан читаться из самого
  ключа: уборщик по сроку не должен ходить в базу, чтобы понять, что он
  сметает.
- **Шард из двух символов** держит число подкаталогов на каждом уровне в
  пределах 256. Без него на локальном диске в одном каталоге оказываются все
  проекты сервиса разом, и обход каталога начинает стоить дороже чтения файла.
- **Проект, а не пользователь, в середине ключа.** Проект — единица удаления
  (`projects.retention_until`, `results_purged_at` в схеме базы), и удаление
  проекта обязано сноситься одним префиксом. Владелец проекта может смениться,
  а ключ, в котором записан прежний владелец, после этого врет.

Разрешенный алфавит сегмента узкий намеренно. Все, что можно принять за
переход по каталогам (`..`, `/`, `\\`, `%`, управляющие символы), отвергается
на входе, а не обезвреживается по дороге: обезвреживание где-то посередине
однажды забудут добавить в новый путь исполнения.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import StrEnum

from .errors import InvalidKeyError

#: Сегмент ключа: начинается с буквы или цифры, дальше точка, дефис и подчерк.
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: Идентификатор проекта — UUID без дефисов.
_PROJECT_ID = re.compile(r"^[0-9a-f]{32}$")

#: Расширение файла: короткое и латинское. Все прочее отбрасывается, а не
#: чинится: расширение здесь нужно человеку для опознания файла, а не системе.
_EXTENSION = re.compile(r"^[a-z0-9]{1,8}$")

#: Предел длины ключа. Ограничение не наше, а файловых систем и S3-провайдеров;
#: лучше отказать на входе, чем получить отказ от диска на середине записи.
MAX_KEY_LENGTH = 512

#: Длина шарда. Два символа шестнадцатеричного идентификатора — 256 каталогов.
SHARD_LENGTH = 2


class ObjectKind(StrEnum):
    """Род объекта. Значения совпадают с родами сроков хранения в `retention.py`.

    Совпадение обязательно: срок хранения вычисляется по первому сегменту
    ключа. Новый род без срока хранения — объект, который никто никогда не
    уберет.
    """

    SOURCE = "source"
    RESULTS = "results"


@dataclass(frozen=True)
class ParsedKey:
    """Разобранный ключ."""

    kind: ObjectKind
    project_id: str
    object_id: str
    extension: str | None


def validate_key(key: str) -> str:
    """Проверяет форму ключа. Возвращает его же или бросает `InvalidKeyError`.

    Проверка синтаксическая: она не знает про корень хранилища и не заменяет
    проверку итогового пути. Выйти за корень можно и через симлинк, у которого
    ключ безупречен, поэтому у реализаций есть второй рубеж.
    """
    if not isinstance(key, str):
        raise InvalidKeyError(f"ключ объекта должен быть строкой, получено {type(key).__name__}")
    if not key:
        raise InvalidKeyError("пустой ключ объекта")
    if key != key.strip():
        raise InvalidKeyError("ключ объекта не может начинаться или кончаться пробелом")
    if len(key) > MAX_KEY_LENGTH:
        raise InvalidKeyError(
            f"ключ объекта длиннее {MAX_KEY_LENGTH} символов (получено {len(key)})"
        )
    if "\\" in key:
        raise InvalidKeyError("обратный слеш в ключе объекта запрещен")
    if any(character < " " or character == "\x7f" for character in key):
        raise InvalidKeyError("управляющие символы в ключе объекта запрещены")

    for segment in key.split("/"):
        # Пустой сегмент — это ведущий, конечный или двойной слеш;
        # `.` и `..` ловятся тем же правилом, потому что не начинаются
        # с буквы или цифры.
        if not _SEGMENT.match(segment):
            raise InvalidKeyError(f"недопустимый сегмент ключа объекта: {segment!r}")
    return key


def key_kind(key: str) -> ObjectKind:
    """Род объекта по ключу. Нужен, чтобы узнать срок хранения без базы."""
    validate_key(key)
    head = key.split("/", 1)[0]
    try:
        return ObjectKind(head)
    except ValueError as error:
        known = ", ".join(kind.value for kind in ObjectKind)
        raise InvalidKeyError(
            f"неизвестный род объекта {head!r} в ключе; известные: {known}"
        ) from error


def normalize_project_id(project_id: str | uuid.UUID) -> str:
    """UUID проекта в том виде, в каком он ложится в ключ."""
    if isinstance(project_id, uuid.UUID):
        return project_id.hex
    normalized = str(project_id).replace("-", "").strip().lower()
    if not _PROJECT_ID.match(normalized):
        raise InvalidKeyError(f"идентификатор проекта не похож на UUID: {project_id!r}")
    return normalized


def extension_of(file_name: str | None) -> str | None:
    """Расширение из имени файла. Само имя нигде дальше не используется."""
    if not file_name or "." not in file_name:
        return None
    candidate = file_name.rsplit(".", 1)[-1].strip().lower()
    return candidate if _EXTENSION.match(candidate) else None


def build_key(
    kind: ObjectKind | str,
    project_id: str | uuid.UUID,
    *,
    object_id: str | None = None,
    file_name: str | None = None,
) -> str:
    """Собирает новый ключ.

    `file_name` берется только ради расширения — оно помогает человеку опознать
    файл в консоли провайдера. Само имя в ключ не попадает.
    """
    kind = ObjectKind(kind)
    project = normalize_project_id(project_id)
    identifier = (object_id or uuid.uuid4().hex).lower()
    if not _SEGMENT.match(identifier):
        raise InvalidKeyError(f"недопустимый идентификатор объекта: {object_id!r}")

    extension = extension_of(file_name)
    tail = f"{identifier}.{extension}" if extension else identifier
    return f"{kind.value}/{project[:SHARD_LENGTH]}/{project}/{tail}"


def parse_key(key: str) -> ParsedKey:
    """Разбирает ключ, собранный `build_key`.

    Ключ чужой формы — это `InvalidKeyError`, а не разбор «как получится»:
    домысленный род объекта означает домысленный срок хранения.
    """
    validate_key(key)
    parts = key.split("/")
    if len(parts) != 4:
        raise InvalidKeyError(f"ключ объекта не соответствует схеме из четырех частей: {key!r}")

    kind_value, shard, project, tail = parts
    kind = key_kind(kind_value)
    project = project.lower()
    if not _PROJECT_ID.match(project):
        raise InvalidKeyError(f"в ключе объекта не UUID проекта: {project!r}")
    if shard != project[:SHARD_LENGTH]:
        raise InvalidKeyError(
            f"шард {shard!r} не совпадает с началом идентификатора проекта {project!r}"
        )

    object_id, _, extension = tail.partition(".")
    if not object_id:
        raise InvalidKeyError(f"в ключе объекта пустой идентификатор: {key!r}")
    return ParsedKey(
        kind=kind,
        project_id=project,
        object_id=object_id,
        extension=extension or None,
    )
