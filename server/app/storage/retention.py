"""Сроки хранения по умолчанию.

Юридический трек закрыт решением владельца от 2026-09-10 (юрлицо и документы
есть), поэтому величины ниже — **инженерные умолчания**, а не результат
согласования. Они выбраны так, чтобы продукт работал и не хранил лишнего;
владелец меняет их через переменные окружения, не трогая код.

Почему именно так:

- Исходник живёт 30 дней. Этого хватает, чтобы пересобрать материалы после
  правок и разобрать жалобу на качество, и мало, чтобы копить чужие
  фонограммы бессрочно.
- Результаты живут 180 дней. Пакет к репетиции нужен весь сезон, а не неделю.
- Аудит-лог живёт дольше остального: он и существует затем, чтобы установить
  объём инцидента задним числом.
- Технические логи короткие: в них нет содержимого, только обращения.
- Запрос на удаление исполняется за сутки, а не «в течение месяца»: удаление,
  которое можно ждать месяц, пользователь не считает удалением.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

SOURCE_DAYS = 30
RESULTS_DAYS = 180
AUDIT_LOG_DAYS = 365
TECH_LOG_DAYS = 30
DELETION_SLA_HOURS = 24


def retention_until(kind: str, since: datetime | None = None) -> datetime:
    """Докуда хранить объект этого рода."""
    days = {
        "source": SOURCE_DAYS,
        "results": RESULTS_DAYS,
        "audit": AUDIT_LOG_DAYS,
        "tech_log": TECH_LOG_DAYS,
    }
    if kind not in days:
        raise ValueError(f"неизвестный род объекта: {kind}")
    return (since or datetime.now(UTC)) + timedelta(days=days[kind])


def deletion_deadline(requested_at: datetime | None = None) -> datetime:
    """Докуда обязаны физически удалить по запросу пользователя."""
    return (requested_at or datetime.now(UTC)) + timedelta(hours=DELETION_SLA_HOURS)
