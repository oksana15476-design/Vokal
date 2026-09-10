"""Реестр версий согласия на стороне сервера.

Зеркало `src/domain/consent.ts`. Дублирование здесь осознанное: сервер обязан
уметь отказать в неизвестной версии согласия, а для этого список версий должен
быть у сервера, а не только на экране.

Задним числом это не чинится. Если принять согласие с версией, которой сервер
не знает, запись «согласие получено» останется без предмета: текст на экране
меняется, а прочитать старое согласие потом неоткуда.

Правила ровно те же, что во фронтенде:

1. Текст действующей версии **не редактируется**. Любая правка формулировки —
   новая версия с новым `id` и новой датой.
2. Старые версии остаются в файле навсегда: по ним читаются старые записи.
3. `fingerprint` записан числом, а не только вычисляется. Тест сверяет число с
   текстом и текст — с `src/domain/consent.ts`, поэтому правку формулировки
   нельзя внести, не тронув версию сразу с обеих сторон.

Формулировки — предмет разговора с юристом (`docs/LEGAL_BRIEF.md`),
не редактуры и не разработки.
"""

from __future__ import annotations

from dataclasses import dataclass

_UINT32 = 0xFFFFFFFF
_SIGN_BIT = 0x80000000


@dataclass(frozen=True)
class ConsentVersion:
    id: str
    effective_from: str
    text: str
    fingerprint: int


def fingerprint_of(text: str) -> int:
    """Та же контрольная сумма, что в `consent.ts`: `hash * 31 + код символа`.

    Не криптография: задача — заметить правку текста, а не защититься от
    подделки. Считается по кодовым единицам UTF-16, как `charCodeAt` в
    браузере; для кириллицы и латиницы это совпадает с `ord`.
    """
    value = 0
    for char in text:
        value = (value * 31 + ord(char)) & _UINT32
    # JS хранит результат знаковым 32-битным числом (оператор `|0`).
    return value - 0x100000000 if value >= _SIGN_BIT else value


CONSENT_TEXT_1 = (
    "Я вправе обработать этот материал для приватной репетиции, урока или внутренней подготовки."
)

#: Все версии, от старых к новым. Удалять записи отсюда нельзя.
consent_versions: tuple[ConsentVersion, ...] = (
    ConsentVersion(
        id="consent-2026-09-10",
        effective_from="2026-09-10",
        text=CONSENT_TEXT_1,
        fingerprint=210796805,
    ),
)


def current_consent() -> ConsentVersion:
    """Версия, действующая сейчас."""
    return consent_versions[-1]


def consent_text_by_id(version_id: str) -> str | None:
    """Текст по идентификатору версии: по нему читаются старые записи."""
    for version in consent_versions:
        if version.id == version_id:
            return version.text
    return None
