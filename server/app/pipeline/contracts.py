"""Контракты аудио-шагов: что конвейер спрашивает у моделей и что получает.

Здесь только интерфейсы и формы ответов. Ни одна реализация в этом модуле не
живет, и это принципиально: подключение настоящей модели должно сводиться к
подстановке другого класса в `ProviderSet`, а не к правке конвейера.

Про уверенность отдельно. Она есть в каждом ответе, потому что продукт обещает
не «идеальный разбор», а честный черновик с отметками, что проверить руками
(`docs/architecture.md`, Confidence and Review Engine). Ответ без уверенности
такой отметки сделать не позволяет.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from app.pipeline.enums import ArtifactKind


def _check_confidence(value: float, *, field_name: str) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name}: уверенность задается долей от 0 до 1, получено {value}.")


@dataclass(frozen=True, repr=False)
class AudioRef:
    """Ссылка на аудио в хранилище.

    `__repr__` намеренно скрывает ключ объекта. `DELETION_AND_RETENTION_DESIGN.md`
    требует, чтобы ключ и подпись ссылки не попадали в логи: строка в логе живет
    дольше файла и превращает удаление в ложное обещание. Логируется
    идентификатор материала, по нему поддержка и ищет.
    """

    artifact_id: str
    storage_key: str
    duration_seconds: float
    sample_rate: int
    channels: int
    audio_format: str

    def __repr__(self) -> str:
        return (
            f"AudioRef(artifact_id={self.artifact_id!r}, "
            f"duration_seconds={self.duration_seconds!r}, storage_key=<скрыт>)"
        )


@dataclass(frozen=True)
class ProviderAvailability:
    """Ответ адаптера на вопрос «ты вообще работаешь».

    Причина обязательна для недоступного провайдера: «нет» без объяснения
    нельзя ни показать пользователю, ни разобрать в поддержке.
    """

    provider_id: str
    available: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.available and not self.reason.strip():
            raise ValueError("Недоступный провайдер обязан назвать причину.")


@dataclass(frozen=True, repr=False)
class ProducedArtifact:
    """Материал, который шаг создал: файл в хранилище или запись для выдачи."""

    name: str
    kind: ArtifactKind
    storage_key: str | None = None
    confidence: float | None = None
    meta: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence is not None:
            _check_confidence(self.confidence, field_name=f"ProducedArtifact({self.name})")

    def __repr__(self) -> str:
        # Ключ объекта в логи не идет по той же причине, что и у AudioRef.
        return f"ProducedArtifact(name={self.name!r}, kind={self.kind.value!r})"


@dataclass(frozen=True)
class StemTrack:
    name: str
    audio: AudioRef
    confidence: float

    def __post_init__(self) -> None:
        _check_confidence(self.confidence, field_name=f"StemTrack({self.name})")


@dataclass(frozen=True)
class StemsResult:
    provider_id: str
    model_id: str
    stems: tuple[StemTrack, ...]


@dataclass(frozen=True)
class BeatGridResult:
    provider_id: str
    bpm: float
    meter: str
    confidence: float
    downbeats: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        _check_confidence(self.confidence, field_name="BeatGridResult")


@dataclass(frozen=True)
class KeyResult:
    provider_id: str
    key: str
    confidence: float
    alternatives: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_confidence(self.confidence, field_name="KeyResult")


@dataclass(frozen=True)
class ChordEvent:
    """Аккорд с привязкой к такту и долей. Повторяет `ChordEvent` из types.ts."""

    bar: int
    beat: float
    chord: str
    confidence: float

    def __post_init__(self) -> None:
        _check_confidence(self.confidence, field_name=f"ChordEvent({self.chord})")


@dataclass(frozen=True)
class ChordsResult:
    provider_id: str
    chords: tuple[ChordEvent, ...]


@dataclass(frozen=True)
class MidiPartDraft:
    part: str
    midi: ProducedArtifact
    confidence: float

    def __post_init__(self) -> None:
        _check_confidence(self.confidence, field_name=f"MidiPartDraft({self.part})")


@dataclass(frozen=True)
class TranscriptionResult:
    provider_id: str
    parts: tuple[MidiPartDraft, ...]


class AudioStage(ABC):
    """Общий предок адаптеров: у каждого спрашивают, работает ли он."""

    provider_id: ClassVar[str] = "unknown"

    @abstractmethod
    def availability(self) -> ProviderAvailability:
        """Работает ли адаптер и почему нет.

        Спрашивается ДО запуска: план обработки должен знать состав выполняемых
        шагов заранее, иначе прогресс считается по шагам, которых не будет.
        """

    def is_available(self) -> bool:
        return self.availability().available


class StemSeparator(AudioStage):
    """Аудио -> аудиослои."""

    @abstractmethod
    def separate(self, source: AudioRef, *, stems: Sequence[str]) -> StemsResult:
        """Разделить запись на названные слои."""


class BeatTracker(AudioStage):
    """Аудио -> пульс и размер."""

    @abstractmethod
    def track(self, source: AudioRef) -> BeatGridResult:
        """Найти BPM, размер и сильные доли."""


class KeyDetector(AudioStage):
    """Аудио -> тональность."""

    @abstractmethod
    def detect(self, source: AudioRef) -> KeyResult:
        """Определить тональный центр."""


class ChordRecognizer(AudioStage):
    """Аудио -> аккордовая сетка с уверенностью по каждому аккорду."""

    @abstractmethod
    def recognize(self, source: AudioRef) -> ChordsResult:
        """Построить черновую аккордовую сетку."""


class Transcriber(AudioStage):
    """Аудио -> MIDI."""

    @abstractmethod
    def transcribe(self, source: AudioRef, *, part: str) -> TranscriptionResult:
        """Перевести партию в MIDI."""
