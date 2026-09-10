"""Заглушки провайдеров и набор адаптеров конвейера.

Правило всего модуля: заглушка выглядит заглушкой. Неподключенный провайдер
отвечает «не подключен» и отказывается работать; он не возвращает ни пустой
результат, ни правдоподобные аккорды. Пустой результат хуже отказа — он
неотличим от честного «в записи нет аккордов» и уезжает в SongGraph как факт.

Подключение настоящей модели — подстановка другого класса в `ProviderSet`:
`ProviderSet(separator=DemucsSeparator())`. Ни оркестратор, ни шаги при этом
не меняются.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, NoReturn

from app.pipeline.contracts import (
    AudioRef,
    BeatGridResult,
    BeatTracker,
    ChordRecognizer,
    ChordsResult,
    KeyDetector,
    KeyResult,
    ProviderAvailability,
    StemSeparator,
    StemsResult,
    Transcriber,
    TranscriptionResult,
)
from app.pipeline.errors import ProviderNotConfiguredError, StageNotImplementedError


class NotConfiguredStage:
    """Смесь для «провайдер не выбран»: одна причина и на вопрос, и на отказ."""

    provider_id: ClassVar[str] = "not-configured"
    reason: ClassVar[str] = "Провайдер не подключен."

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider_id=self.provider_id,
            available=False,
            reason=self.reason,
        )

    def _refuse(self) -> NoReturn:
        raise ProviderNotConfiguredError(provider_id=self.provider_id, message=self.reason)


class NotImplementedStage:
    """Смесь для «адаптер есть, модели за ним нет»."""

    provider_id: ClassVar[str] = "not-implemented"
    reason: ClassVar[str] = "Реализация не собрана."

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider_id=self.provider_id,
            available=False,
            reason=self.reason,
        )

    def _refuse(self) -> NoReturn:
        raise StageNotImplementedError(provider_id=self.provider_id, message=self.reason)


# --- Разделение на аудиослои --------------------------------------------


class NotConfiguredSeparator(NotConfiguredStage, StemSeparator):
    provider_id = "not-configured-separator"
    reason = "Разделение на аудиослои не подключено: провайдер не выбран."

    def separate(self, source: AudioRef, *, stems: Sequence[str]) -> StemsResult:
        self._refuse()


class DemucsSeparator(NotImplementedStage, StemSeparator):
    """Заготовка self-hosted Demucs.

    Существует как место, куда придет реализация: `docs/DATA_MAP.md` считает
    Demucs на своем сервере тем вариантом, при котором аудио вообще не покидает
    нашу инфраструктуру. Пока за адаптером ничего нет, и он об этом говорит.
    """

    provider_id = "demucs"
    reason = "Demucs не реализован: адаптер есть, модели за ним нет."

    def separate(self, source: AudioRef, *, stems: Sequence[str]) -> StemsResult:
        self._refuse()


# --- Темп, тональность, аккорды, MIDI -----------------------------------


class NotConfiguredBeatTracker(NotConfiguredStage, BeatTracker):
    provider_id = "not-configured-beat-tracker"
    reason = "Определение темпа и размера не подключено: провайдер не выбран."

    def track(self, source: AudioRef) -> BeatGridResult:
        self._refuse()


class NotConfiguredKeyDetector(NotConfiguredStage, KeyDetector):
    provider_id = "not-configured-key-detector"
    reason = "Определение тональности не подключено: провайдер не выбран."

    def detect(self, source: AudioRef) -> KeyResult:
        self._refuse()


class NotConfiguredChordRecognizer(NotConfiguredStage, ChordRecognizer):
    provider_id = "not-configured-chord-recognizer"
    reason = "Распознавание аккордов не подключено: провайдер не выбран."

    def recognize(self, source: AudioRef) -> ChordsResult:
        self._refuse()


class NotConfiguredTranscriber(NotConfiguredStage, Transcriber):
    provider_id = "not-configured-transcriber"
    reason = "Перевод аудио в MIDI не подключен: провайдер не выбран."

    def transcribe(self, source: AudioRef, *, part: str) -> TranscriptionResult:
        self._refuse()


@dataclass(frozen=True)
class ProviderSet:
    """Все адаптеры конвейера в одном месте.

    Умолчание — честное состояние продукта на сегодня: не подключено ничего.
    """

    separator: StemSeparator = field(default_factory=NotConfiguredSeparator)
    beat_tracker: BeatTracker = field(default_factory=NotConfiguredBeatTracker)
    key_detector: KeyDetector = field(default_factory=NotConfiguredKeyDetector)
    chord_recognizer: ChordRecognizer = field(default_factory=NotConfiguredChordRecognizer)
    transcriber: Transcriber = field(default_factory=NotConfiguredTranscriber)
