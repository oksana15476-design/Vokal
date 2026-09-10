"""Хранилище на локальном диске.

Для чего оно нужно, если в проде будет S3. Затем, чтобы сквозной срез
«загрузил песню — получил материалы» работал на машине разработчика и в CI без
бакета, ключей и сети. Второе назначение — эталон поведения: тесты проверяют
контракт хранилища именно здесь, потому что здесь можно испортить файл руками
и посмотреть, что будет.

Три решения, которые стоит знать, прежде чем править этот файл.

**Файлы и метаданные лежат в двух деревьях.** `{корень}/objects/{ключ}` —
содержимое, `{корень}/meta/{ключ}.json` — сумма, тип и срок хранения. Соблазн
положить метаданные рядом файлом `{ключ}.json` есть, но тогда ключ, честно
оканчивающийся на `.json`, накрывает чужие метаданные, а обход дерева
объектов начинает натыкаться на служебные файлы и должен их угадывать.

**Запись идет во временный файл, потом жесткая ссылка.** Не `os.replace`:
`replace` перезаписывает молча, а перезапись ключа контракт запрещает.
`os.link` на POSIX атомарен и падает, если имя занято, — это единственный
способ проверить «занято ли» и занять одной операцией. Проверка `exists()`
отдельным шагом оставляет щель, в которую успевает второй процесс.

**Блокирующий ввод-вывод уходит в поток.** Метод объявлен `async`, но
`open().read()` держит событийный цикл, и на пятидесятимегабайтной фонограмме
это заметно всему процессу. Поэтому каждая операция с диском —
`asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

from .base import ObjectStorage, StoredObject
from .errors import (
    ChecksumMismatchError,
    InvalidKeyError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
    StorageError,
)
from .keys import key_kind, validate_key
from .metadata import ObjectMetadata, build_metadata, checksum_of, dumps, loads

#: Подкаталоги корня. Разделение дает еще одно удобство: `objects/` можно
#: отдать наружу как есть (например, синхронизацией), не выдав вместе с ним
#: служебные записи.
OBJECTS_DIR = "objects"
META_DIR = "meta"

#: Файл, которым корень хранилища закрывает себя от git.
GITIGNORE_NAME = ".gitignore"


class LocalDiskStorage(ObjectStorage):
    """`ObjectStorage` поверх файловой системы."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Корень хранилища в том виде, в каком он задан настройками."""
        return self._root

    # --- Пути ------------------------------------------------------------

    def path_for(self, key: str) -> Path:
        """Путь к содержимому объекта."""
        return self._safe_path(self._objects_dir, key)

    def metadata_path_for(self, key: str) -> Path:
        """Путь к записи метаданных объекта."""
        return self._safe_path(self._meta_dir, f"{key}.json")

    @property
    def _objects_dir(self) -> Path:
        return self._root / OBJECTS_DIR

    @property
    def _meta_dir(self) -> Path:
        return self._root / META_DIR

    def _safe_path(self, base: Path, relative: str) -> Path:
        """Собирает путь и проверяет, что он остался под своим деревом.

        Второй рубеж после `validate_key`. Синтаксически безупречный ключ
        все равно уводит наружу, если по дороге стоит симлинк: сегмент
        `source` может оказаться ссылкой на `/etc`. Поэтому путь еще и
        разрешается целиком и сверяется с корнем — без этого проверка ключа
        защищает от строки `..`, но не от файловой системы.
        """
        validate_key(relative.removesuffix(".json"))
        resolved_base = base.resolve()
        candidate = (base / relative).resolve()
        if candidate != resolved_base and resolved_base not in candidate.parents:
            raise InvalidKeyError(
                f"ключ объекта выводит за пределы хранилища: {relative.removesuffix('.json')!r}"
            )
        return candidate

    # --- Контракт --------------------------------------------------------

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        validate_key(key)
        # Род объекта нужен, чтобы вычислить срок хранения. Объект без рода
        # означает объект без срока — такой никто и никогда не уберет.
        key_kind(key)
        metadata = build_metadata(key, data, content_type)
        await asyncio.to_thread(self._put_sync, metadata, data)
        return metadata.as_stored_object()

    async def get(self, key: str) -> bytes:
        validate_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    async def delete(self, key: str) -> bool:
        validate_key(key)
        return await asyncio.to_thread(self._delete_sync, key)

    async def exists(self, key: str) -> bool:
        """Есть ли объект, который можно прочитать.

        Требуются оба файла — содержимое и метаданные. Иначе `exists()`
        отвечает «да» там, где `get()` откажет, и вызывающий код получает
        исключение ровно после проверки, которая должна была его уберечь.
        """
        validate_key(key)
        return await asyncio.to_thread(self._exists_sync, key)

    async def signed_url(self, key: str, expires_seconds: int) -> None:
        """Локальный диск так не умеет — и говорит об этом прямо.

        Правило записано в `base.py`: сгенерированный адрес, который никуда не
        ведет, снаружи неотличим от рабочего. Файл отдает API.
        """
        validate_key(key)
        return None

    # --- Сверх контракта -------------------------------------------------

    async def stat(self, key: str) -> ObjectMetadata:
        """Метаданные объекта без чтения содержимого."""
        validate_key(key)
        return await asyncio.to_thread(self._read_metadata, key)

    async def iter_objects(self) -> AsyncIterator[ObjectMetadata]:
        """Перебирает объекты хранилища. Нужен уборщику по сроку хранения.

        Обход идет по дереву метаданных, а не объектов: у объекта без
        метаданных не известен ни срок, ни сумма, и решать его судьбу
        перебором нельзя.
        """
        paths = await asyncio.to_thread(self._list_metadata_paths)
        for path in paths:
            key = str(path.relative_to(self._meta_dir.resolve())).removesuffix(".json")
            try:
                yield await asyncio.to_thread(self._read_metadata, key)
            except ObjectNotFoundError:
                # Запись исчезла между составлением списка и чтением —
                # обычная гонка с параллельным удалением, не повод падать.
                continue

    # --- Синхронная работа с диском --------------------------------------

    def _ensure_root(self) -> None:
        """Создает корень и закрывает его от git.

        Корень по умолчанию относительный (`var/object-storage`), то есть
        запросто оказывается внутри рабочего дерева репозитория. Чужая
        фонограмма, попавшая в историю git, оттуда уже не убирается — история
        необратима, и это отдельным правилом записано в CLAUDE.md. Полагаться
        на то, что строку в `.gitignore` кто-то не забудет, здесь нельзя:
        цена забывчивости — не сломанная сборка, а утечка.
        """
        marker = self._root / GITIGNORE_NAME
        if marker.is_file():
            return
        self._root.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "# Содержимое хранилища объектов в git не попадает никогда:\n"
            "# это загруженные пользователями фонограммы.\n"
            "*\n",
            encoding="utf-8",
        )

    def _put_sync(self, metadata: ObjectMetadata, data: bytes) -> None:
        self._ensure_root()
        object_path = self.path_for(metadata.key)
        meta_path = self.metadata_path_for(metadata.key)

        # Файл без метаданных — след оборванной укладки: сверить его сумму
        # нечем, отдать его нельзя, значит и скачать его никто не мог.
        # Перезапись такого остатка ничего не разрушает и чинит хранилище
        # сама; запрет перезаписи защищает целые объекты, а не мусор.
        orphaned = object_path.is_file() and not meta_path.is_file()
        if object_path.is_file() and not orphaned:
            raise ObjectAlreadyExistsError(
                f"объект {metadata.key!r} уже существует; перезапись запрещена"
            )

        object_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        # Сначала содержимое, потом метаданные. Порядок важен: между проверкой
        # выше и записью успевает вклиниться второй процесс, и защищает от
        # этого только эксклюзивная запись самого объекта. Обратный порядок
        # означал бы, что отвергнутая перезапись успела подменить сумму уже
        # лежащего объекта и сделала его нечитаемым.
        try:
            self._write_atomic(object_path, data, overwrite=orphaned)
        except FileExistsError as error:
            raise ObjectAlreadyExistsError(
                f"объект {metadata.key!r} уже существует; перезапись запрещена"
            ) from error

        self._write_atomic(meta_path, dumps(metadata).encode("utf-8"), overwrite=True)

    def _write_atomic(self, path: Path, payload: bytes, *, overwrite: bool) -> None:
        """Кладет файл целиком или не кладет вовсе.

        Половина файла на диске после обрыва — это испорченный объект, который
        пройдет проверку существования и не пройдет проверку суммы. Дешевле не
        допускать такого состояния.
        """
        temporary = path.parent / f".tmp-{uuid.uuid4().hex}"
        try:
            with open(temporary, "wb") as handle:
                handle.write(payload)
                handle.flush()
                # fsync до переименования: без него после отключения питания
                # остается видимое имя с пустым содержимым.
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                # Жесткая ссылка занимает имя и падает, если оно занято.
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _exists_sync(self, key: str) -> bool:
        return self.path_for(key).is_file() and self.metadata_path_for(key).is_file()

    def _get_sync(self, key: str) -> bytes:
        metadata = self._read_metadata(key)
        path = self.path_for(key)
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise ObjectNotFoundError(f"объекта {key!r} нет в хранилище") from error

        actual = checksum_of(data)
        if actual != metadata.checksum_sha256:
            raise ChecksumMismatchError(
                f"содержимое объекта {key!r} не совпадает с записанной суммой: "
                f"ожидалось {metadata.checksum_sha256}, получено {actual}"
            )
        return data

    def _read_metadata(self, key: str) -> ObjectMetadata:
        path = self.metadata_path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ObjectNotFoundError(
                f"метаданных объекта {key!r} нет; сверить сумму нечем, "
                "поэтому объект считается отсутствующим"
            ) from error

        metadata = loads(key, raw)
        # Запись обязана называть свой ключ. Скопированная или переехавшая
        # запись сходится по сумме с чужим содержимым, и уборщик по сроку
        # хранения получит от нее чужое имя — то есть удалит не тот файл.
        if metadata.key != key:
            raise StorageError(
                f"метаданные по пути объекта {key!r} записаны для другого ключа: {metadata.key!r}"
            )
        return metadata

    def _delete_sync(self, key: str) -> bool:
        object_path = self.path_for(key)
        meta_path = self.metadata_path_for(key)

        existed = object_path.is_file()
        object_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

        # Пустые каталоги убираются сразу. Иначе после удаления проекта в
        # хранилище остается скелет из каталогов, по которому видно, сколько
        # у пользователя было проектов, — сведения, которые обещали удалить.
        self._prune(object_path.parent, self._objects_dir.resolve())
        self._prune(meta_path.parent, self._meta_dir.resolve())
        return existed

    def _prune(self, directory: Path, stop_at: Path) -> None:
        current = directory
        while current != stop_at and stop_at in current.parents:
            try:
                current.rmdir()
            except OSError:
                # Каталог не пуст или уже снесен параллельным удалением.
                return
            current = current.parent

    def _list_metadata_paths(self) -> list[Path]:
        meta_root = self._meta_dir
        if not meta_root.is_dir():
            return []
        return sorted(self._walk_json(meta_root.resolve()))

    def _walk_json(self, directory: Path) -> Iterator[Path]:
        for entry in directory.iterdir():
            if entry.is_dir():
                yield from self._walk_json(entry)
            elif entry.suffix == ".json":
                yield entry
