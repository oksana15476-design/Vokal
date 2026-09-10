"""Общая база моделей: соглашения об именах, отметки времени, мягкое удаление."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import TIMESTAMP, MetaData, func
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Имена ограничений задаются соглашением, а не автогенератором Postgres.
# Иначе Alembic не может сослаться на ограничение в миграции вниз: имя,
# которое придумала база, в коде неизвестно.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Единая точка получения времени: везде UTC с явной зоной."""
    return datetime.now(tz=UTC)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def domain_enum(python_enum: type[Any], name: str) -> PgEnum:
    """Тип-перечисление Postgres со значениями домена, а не именами Python.

    По умолчанию SQLAlchemy пишет в базу **имена** членов перечисления
    (`ORIGINAL_LIKE`), а не значения (`original-like`). Тогда база расходится
    с контрактом фронтенда, и расхождение видно только в дампе.
    """
    return PgEnum(
        python_enum,
        name=name,
        values_callable=lambda enum_type: [member.value for member in enum_type],
        create_type=False,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


class SoftDeleteMixin:
    """Мягкое удаление и срок хранения.

    `deleted_at` заполняется один раз и не обнуляется: необратимость держится
    триггером базы, а не аккуратностью вызывающего кода (см. миграцию).
    `retention_until` — момент, после которого строку можно снести физически;
    пока сроки хранения не определены юристом, поле остается пустым, и это
    честнее выдуманного числа.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, default=None
    )
    retention_until: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True, default=None
    )
