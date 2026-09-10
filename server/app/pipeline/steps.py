"""Шаги конвейера: описание, контекст, результат и исполнители.

Шаг знает две вещи: выполняется ли он вообще (`availability`) и что делает
(`run`). Первое спрашивается ДО запуска, потому что от этого зависит
знаменатель прогресса: шаг, которого не будет, не имеет права в него попасть.

Исполнитель шага — отдельный класс, а не ветка внутри оркестратора. Так
подключение настоящей модели остается заменой одного класса, а оркестратор
не знает, кто именно считает аккорды.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.pipeline.contracts import (
    AudioRef,
    BeatTracker,
    ChordRecognizer,
    KeyDetector,
    ProducedArtifact,
    ProviderAvailability,
    StemSeparator,
    Transcriber,
)
from app.pipeline.enums import ArtifactKind, RetryScope, StepStatus
from app.pipeline.errors import SourceMissingError, StageFailedError

# Слои, которые запрашиваем у разделения, и партии, которые переводим в MIDI.
# Список продуктовый, а не технический: он задан в `docs/architecture.md`.
DEFAULT_STEMS: tuple[str, ...] = ("vocals", "drums", "bass", "guitar", "keys", "other")
DEFAULT_MIDI_PARTS: tuple[str, ...] = ("vocals", "bass", "guitar", "keys")

# Ключ, под которым шаг разделения кладет ссылки на слои для транскрипции.
# Договоренность двух шагов названа один раз, а не повторена строкой в каждом.
STEMS_DATA_KEY = "stems"


@dataclass(frozen=True)
class StepDefinition:
    """Паспорт шага: то, что видит пользователь, плюс зависимости."""

    id: str
    label: str
    detail: str
    # Шаги, без результата которых этот запускать нечем. Если требуемый шаг не
    # выполняется, не выполняется и этот: транскрипция без аудиослоев — не
    # «попробуем и посмотрим», а заведомо несделанная работа.
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class StepContext:
    """Все, что исполнитель шага получает на вход."""

    run_id: str
    step_id: str
    attempt: int
    source: AudioRef | None = None
    # Данные завершенных шагов: идентификатор шага -> его `data`.
    results: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def require_source(self) -> AudioRef:
        if self.source is None:
            raise SourceMissingError()
        return self.source


@dataclass(frozen=True)
class StepOutcome:
    """Успешный итог шага.

    Статуса «ошибка» здесь нет намеренно: сбой сообщается исключением. Если бы
    исполнитель мог вернуть «ошибку» как обычный результат, шаг умел бы
    завершаться и падать одновременно, а оркестратору пришлось бы гадать,
    засчитывать ли его в прогресс.
    """

    status: StepStatus
    detail: str
    artifacts: tuple[ProducedArtifact, ...] = ()
    warnings: tuple[str, ...] = ()
    data: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in (StepStatus.DONE, StepStatus.WARNING):
            raise ValueError(
                "Шаг завершается либо «готово», либо «предупреждение». Сбой сообщается исключением."
            )
        names = [artifact.name for artifact in self.artifacts]
        if len(names) != len(set(names)):
            # Идентификатор материала считается из имени. Два одинаковых имени
            # в одном шаге молча схлопнулись бы в один материал.
            raise ValueError("Имена материалов внутри шага должны быть разными.")


class StepRunner(ABC):
    """Исполнитель одного шага."""

    def __init__(self, step: StepDefinition) -> None:
        self.step = step

    @abstractmethod
    def availability(self) -> ProviderAvailability:
        """Выполняется ли шаг на этом пути и почему нет."""

    @abstractmethod
    def run(self, context: StepContext) -> StepOutcome:
        """Сделать работу шага или упасть с `PipelineError`."""


class NotConnectedRunner(StepRunner):
    """Шаг, за которым пока нет ничего.

    Нужен там, где своего сервиса еще нет вовсе (нормализация, структура,
    нотный вывод, ревью директора). Такой шаг честно не выполняется, а не
    делает вид, что прошел.
    """

    def __init__(self, step: StepDefinition, *, reason: str, provider_id: str = "none") -> None:
        super().__init__(step)
        self._reason = reason
        self._provider_id = provider_id

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider_id=self._provider_id,
            available=False,
            reason=self._reason,
        )

    def run(self, context: StepContext) -> StepOutcome:
        # Досюда доходить не должно: оркестратор не запускает невыполняемые шаги.
        raise StageFailedError(
            code="stage_not_implemented",
            message=self._reason,
            retryable=False,
            retry_scope=RetryScope.NONE,
        )


class SeparateStemsRunner(StepRunner):
    """Шаг «Разделение на аудиослои»."""

    def __init__(self, step: StepDefinition, separator: StemSeparator) -> None:
        super().__init__(step)
        self._separator = separator

    def availability(self) -> ProviderAvailability:
        return self._separator.availability()

    def run(self, context: StepContext) -> StepOutcome:
        result = self._separator.separate(context.require_source(), stems=DEFAULT_STEMS)
        artifacts = tuple(
            ProducedArtifact(
                name=f"stem-{track.name}",
                kind=ArtifactKind.STEM,
                storage_key=track.audio.storage_key,
                confidence=track.confidence,
                meta={"stem": track.name, "provider": result.provider_id, "model": result.model_id},
            )
            for track in result.stems
        )
        return StepOutcome(
            status=StepStatus.DONE,
            detail=f"Слоев получено: {len(result.stems)}.",
            artifacts=artifacts,
            # Ссылки на слои нужны транскрипции: она работает по слоям, а не по миксу.
            data={STEMS_DATA_KEY: {track.name: track.audio for track in result.stems}},
        )


class TempoAndKeyRunner(StepRunner):
    """Шаг «BPM, тональность и размер»: два адаптера на один шаг экрана."""

    def __init__(self, step: StepDefinition, beats: BeatTracker, key: KeyDetector) -> None:
        super().__init__(step)
        self._beats = beats
        self._key = key

    def availability(self) -> ProviderAvailability:
        beats = self._beats.availability()
        if not beats.available:
            return beats
        key = self._key.availability()
        if not key.available:
            return key
        return ProviderAvailability(
            provider_id=f"{beats.provider_id}+{key.provider_id}",
            available=True,
        )

    def run(self, context: StepContext) -> StepOutcome:
        source = context.require_source()
        beats = self._beats.track(source)
        key = self._key.detect(source)
        return StepOutcome(
            status=StepStatus.DONE,
            detail=f"BPM {beats.bpm:g}, размер {beats.meter}, тональность {key.key}.",
            data={
                "bpm": beats.bpm,
                "meter": beats.meter,
                "beat_confidence": beats.confidence,
                "key": key.key,
                "key_confidence": key.confidence,
            },
        )


class ChordsRunner(StepRunner):
    """Шаг «Аккорды»."""

    def __init__(self, step: StepDefinition, recognizer: ChordRecognizer) -> None:
        super().__init__(step)
        self._recognizer = recognizer

    def availability(self) -> ProviderAvailability:
        return self._recognizer.availability()

    def run(self, context: StepContext) -> StepOutcome:
        result = self._recognizer.recognize(context.require_source())
        return StepOutcome(
            status=StepStatus.DONE,
            detail=f"Аккордов размечено: {len(result.chords)}.",
            data={"chords": result.chords},
        )


class TranscribeRunner(StepRunner):
    """Шаг «MIDI-черновики»: работает по аудиослоям, а не по миксу."""

    def __init__(
        self,
        step: StepDefinition,
        transcriber: Transcriber,
        *,
        stems_step_id: str = "stems",
    ) -> None:
        super().__init__(step)
        self._transcriber = transcriber
        self._stems_step_id = stems_step_id

    def availability(self) -> ProviderAvailability:
        return self._transcriber.availability()

    def run(self, context: StepContext) -> StepOutcome:
        stems = context.results.get(self._stems_step_id, {}).get(STEMS_DATA_KEY)
        if not isinstance(stems, dict) or not stems:
            raise StageFailedError(
                code="failed_transcription",
                message="Шаг разделения не передал аудиослои: транскрибировать нечего.",
                retryable=False,
                retry_scope=RetryScope.NONE,
            )

        artifacts: list[ProducedArtifact] = []
        for part in DEFAULT_MIDI_PARTS:
            stem = stems.get(part)
            if stem is None:
                continue
            result = self._transcriber.transcribe(stem, part=part)
            artifacts.extend(
                ProducedArtifact(
                    name=f"midi-{draft.part}",
                    kind=ArtifactKind.MIDI,
                    storage_key=draft.midi.storage_key,
                    confidence=draft.confidence,
                    meta={"part": draft.part, "provider": result.provider_id},
                )
                for draft in result.parts
            )

        return StepOutcome(
            status=StepStatus.DONE,
            detail=f"Партий переведено в MIDI: {len(artifacts)}.",
            artifacts=tuple(artifacts),
        )


# Список шагов повторяет тот, что пользователь видит на экране обработки
# (`baseSteps` в `src/domain/mockData.ts`). Один и тот же перечень на обеих
# сторонах нужен, чтобы экран показывал ход настоящей обработки, а не свой.
DEFAULT_STEP_DEFINITIONS: tuple[StepDefinition, ...] = (
    StepDefinition(
        id="normalize",
        label="Нормализация аудио",
        detail="Проверка формата и уровня громкости.",
    ),
    StepDefinition(
        id="stems",
        label="Разделение на аудиослои",
        detail="Вокал, барабаны, бас, гитара и клавиши.",
    ),
    StepDefinition(
        id="tempo",
        label="BPM, тональность и размер",
        detail="Пульс, тональный центр и метр.",
    ),
    StepDefinition(
        id="structure",
        label="Структура песни",
        detail="Intro, куплеты, припевы, bridge и coda.",
        requires=("tempo",),
    ),
    StepDefinition(
        id="chords",
        label="Аккорды",
        detail="Черновая сетка с уверенностью по каждому аккорду.",
    ),
    StepDefinition(
        id="midi",
        label="MIDI-черновики",
        detail="Перевод аудиослоев в MIDI-партии.",
        requires=("stems",),
    ),
    StepDefinition(
        id="notation",
        label="MusicXML и PDF",
        detail="Ноты и карточки страниц.",
        requires=("midi",),
    ),
    StepDefinition(
        id="director",
        label="Ревью AI-директора",
        detail="Проверка состава, уровня и выдачи материалов.",
    ),
)

STEP_BY_ID: dict[str, StepDefinition] = {step.id: step for step in DEFAULT_STEP_DEFINITIONS}
