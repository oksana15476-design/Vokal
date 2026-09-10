"""Схемы людей и учебного контекста.

`Musician` — отдельная сущность, а не поле состава, потому что ограничения
принадлежат людям, а не группе: диапазон — вокалиста, число струн — басиста,
уровень — каждого свой. В плоском составе этого не выразить, и директор
предлагал транспонирование, не зная, чей это диапазон.

Про ученика собирается минимум (`docs/DATA_MAP.md`): отображаемое имя,
инструмент, уровень, возрастная группа. Дата рождения не собирается — только
диапазон возраста, и это осознанное решение, а не упрощение.
"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import (
    AssignmentStatus,
    BassStrings,
    LessonDifficulty,
    MusicianLevel,
    MusicianRole,
    NotationReading,
    StudentLevel,
    TeacherFormat,
)


class MusicianOut(ApiModel):
    """Человек в составе со своими ограничениями."""

    id: str
    name: str
    role: MusicianRole
    instrument_note: str = Field(description="Чем играет: «5 струн · E1», «2 слоя · Nord Stage»")
    constraint: str = Field(description="Что ограничивает: диапазон, строй, каподастр")
    level: MusicianLevel


class BandLineupOut(ApiModel):
    """Состав группы целиком."""

    lead_vocal: bool
    vocal_range: str
    guitars: int = Field(ge=0, le=8)
    guitar_tuning: str
    capo: str
    bass: BassStrings
    keys: bool
    keys_can_cover_layers: bool
    drums: bool
    backing_vocals: bool
    musician_level: MusicianLevel
    target_style: str


class StudentProfileOut(ApiModel):
    """Ученик. Имя — отображаемое, соответствия документам не требуется."""

    name: str
    instrument: str
    level: StudentLevel
    age_group: str = Field(description="Диапазон возраста, не дата рождения")
    notation_reading: NotationReading
    chord_knowledge: str
    home_instrument: str


class TeacherProfileOut(ApiModel):
    name: str
    format: TeacherFormat
    focus: str


class ClassGroupOut(ApiModel):
    name: str
    students_count: int = Field(ge=0)
    instruments: list[str]


class LessonOut(ApiModel):
    goal: str
    homework_format: str
    desired_difficulty: LessonDifficulty


class AssignmentOut(ApiModel):
    """Задание ученику или музыканту."""

    id: str
    title: str
    recipient: str
    status: AssignmentStatus
