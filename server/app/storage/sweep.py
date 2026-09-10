"""Уборка по сроку хранения: поиск просроченного.

Функция только **находит**. Удаление вызывает планировщик, а планировщика в
проекте еще нет — ни очереди, ни периодических задач. Это осознанное деление,
а не недоделка.

Почему нельзя было заодно и удалить. Сроки в `retention.py` — инженерные
умолчания, а не согласованная политика хранения. Автоматический сметатель,
запущенный по умолчанию, снесет пользователю материалы репетиции ровно на
тридцать первый день, и узнает он об этом, когда придет за ними. Поиск же
безопасен в любой момент: он читает и печатает, а решение — отдельный шаг,
у которого должен быть журнал и подтвержденный статус (требование
`docs/DELETION_AND_RETENTION_DESIGN.md`: «подтвержденный статус вместо флага»).

Отдельно про осиротевшие объекты: обход идет по хранилищу, а не по базе.
Файл, о котором строка в базе потерялась, — это чужая фонограмма, которую
никто не удалит, потому что про нее забыли. Хранилище про нее помнит.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .metadata import ObjectMetadata


@runtime_checkable
class SupportsScan(Protocol):
    """Хранилище, по которому можно пройтись.

    Метода нет в `ObjectStorage`: обход нужен уборщику, а не выдаче файлов,
    и требовать его от всякой реализации незачем.
    """

    def iter_objects(self) -> AsyncIterator[ObjectMetadata]: ...


async def find_expired(
    storage: SupportsScan,
    *,
    now: datetime | None = None,
) -> list[ObjectMetadata]:
    """Объекты, у которых `retention_until` уже позади.

    Ничего не удаляет и не помечает. Возвращает список, отсортированный от
    самого давнего срока: удалять начинают с того, что просрочено дольше.

    Испорченная запись метаданных обрывает обход исключением, а не
    пропускается. Пропуск означал бы объект с неизвестным сроком, который
    никто уже не найдет: уборка тихо перестала бы выполнять обещание о
    хранении. Обрыв виден оператору сразу.
    """
    moment = now or datetime.now(UTC)
    expired: list[ObjectMetadata] = []
    async for record in storage.iter_objects():
        deadline = record.retention_until
        if deadline.tzinfo is None:
            # Запись без часового пояса сравнивать с моментом времени нельзя.
            # Считаем такую запись UTC: именно в UTC ее и писали, а падать
            # на уборке из-за формы записи — хуже, чем принять умолчание.
            deadline = deadline.replace(tzinfo=UTC)
        if deadline <= moment:
            expired.append(record)
    expired.sort(key=lambda record: (record.retention_until, record.key))
    return expired
