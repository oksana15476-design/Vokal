"""Схемы песни: цель обработки и разбор.

Разбор отдается вместе с признаком происхождения (`source`). Промежуточного
состояния нет: либо разбор относится к этому файлу, либо его нет вовсе.
Подставлять чужой разбор к своему файлу нельзя — пользователь увидит
тональность и аккорды другой песни и поверит им.
"""

from __future__ import annotations

from pydantic import Field

from app.api.schemas.common import ApiModel
from app.api.schemas.enums import AnalysisSource, ProcessingGoalId, Scenario


class ProcessingGoalOut(ApiModel):
    """Цель обработки вместе с подписями для интерфейса."""

    id: ProcessingGoalId
    scenario: Scenario
    label: str = Field(description="Подпись для экрана")
    description: str = Field(description="Пояснение, что получится")
    expected_outputs: list[str] = Field(description="Что войдет в Stage Pack при этой цели")


class SongSectionOut(ApiModel):
    """Секция формы: куплет, припев, проигрыш."""

    id: str
    label: str
    start_bar: int = Field(ge=1)
    end_bar: int = Field(ge=1)
    note: str = Field(default="", description="Замечание к секции")


class ChordEventOut(ApiModel):
    """Аккорд в конкретном такте и доле."""

    bar: int = Field(ge=1)
    beat: int = Field(ge=1)
    chord: str
    confidence: float = Field(ge=0, le=1, description="Уверенность модели: 0..1")


class SongAnalysisOut(ApiModel):
    """Разбор песни.

    Пустые значения (`bpm = 0`, пустые списки) при `source = none` — не потеря
    данных, а честное «звук не анализировался».
    """

    source: AnalysisSource
    title: str
    artist: str
    bpm: int = Field(ge=0, description="0, если темп не определялся")
    key: str = Field(description="Пустая строка, если тональность не определялась")
    meter: str
    duration: str = Field(description="Длительность в виде мм:сс для показа")
    genre: str
    sections: list[SongSectionOut]
    chords: list[ChordEventOut]
    confidence_by_part: dict[str, float] = Field(
        description="Уверенность по партиям: имя партии -> 0..1"
    )
    summary: str
