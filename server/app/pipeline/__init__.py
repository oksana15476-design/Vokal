"""Конвейер обработки песни.

Каркас с честными заглушками: интерфейсы моделей, шаги, оркестратор задания.
Настоящих моделей за адаптерами пока нет, и каждый из них об этом говорит.
Подключение реализации — подстановка класса в `ProviderSet`, править шаги и
оркестратор для этого не нужно.

Слои: `enums` -> `errors`/`contracts` -> `providers`/`steps` -> `orchestrator`
-> `factory`. Импорт снизу вверх, колец нет.
"""

from __future__ import annotations

from app.pipeline.contracts import (
    AudioRef,
    AudioStage,
    BeatGridResult,
    BeatTracker,
    ChordEvent,
    ChordRecognizer,
    ChordsResult,
    KeyDetector,
    KeyResult,
    MidiPartDraft,
    ProducedArtifact,
    ProviderAvailability,
    StemSeparator,
    StemsResult,
    StemTrack,
    Transcriber,
    TranscriptionResult,
)
from app.pipeline.enums import ArtifactKind, RetryScope, RunStatus, StepStatus
from app.pipeline.errors import (
    PipelineError,
    ProviderNotConfiguredError,
    SourceMissingError,
    StageFailedError,
    StageNotImplementedError,
    StepNotRetryableError,
    StepNotRunnableError,
    UnknownStepError,
)
from app.pipeline.factory import build_default_pipeline
from app.pipeline.orchestrator import (
    FailureReport,
    PipelineOrchestrator,
    PipelineRun,
    RunArtifact,
    RunSnapshot,
    StepFailure,
    StepState,
    StepView,
)
from app.pipeline.providers import (
    DemucsSeparator,
    NotConfiguredBeatTracker,
    NotConfiguredChordRecognizer,
    NotConfiguredKeyDetector,
    NotConfiguredSeparator,
    NotConfiguredTranscriber,
    ProviderSet,
)
from app.pipeline.steps import (
    DEFAULT_MIDI_PARTS,
    DEFAULT_STEMS,
    DEFAULT_STEP_DEFINITIONS,
    STEMS_DATA_KEY,
    STEP_BY_ID,
    ChordsRunner,
    NotConnectedRunner,
    SeparateStemsRunner,
    StepContext,
    StepDefinition,
    StepOutcome,
    StepRunner,
    TempoAndKeyRunner,
    TranscribeRunner,
)

__all__ = [
    "DEFAULT_MIDI_PARTS",
    "DEFAULT_STEMS",
    "DEFAULT_STEP_DEFINITIONS",
    "STEMS_DATA_KEY",
    "STEP_BY_ID",
    "ArtifactKind",
    "AudioRef",
    "AudioStage",
    "BeatGridResult",
    "BeatTracker",
    "ChordEvent",
    "ChordRecognizer",
    "ChordsResult",
    "ChordsRunner",
    "DemucsSeparator",
    "FailureReport",
    "KeyDetector",
    "KeyResult",
    "MidiPartDraft",
    "NotConfiguredBeatTracker",
    "NotConfiguredChordRecognizer",
    "NotConfiguredKeyDetector",
    "NotConfiguredSeparator",
    "NotConfiguredTranscriber",
    "NotConnectedRunner",
    "PipelineError",
    "PipelineOrchestrator",
    "PipelineRun",
    "ProducedArtifact",
    "ProviderAvailability",
    "ProviderNotConfiguredError",
    "ProviderSet",
    "RetryScope",
    "RunArtifact",
    "RunSnapshot",
    "RunStatus",
    "SeparateStemsRunner",
    "SourceMissingError",
    "StageFailedError",
    "StageNotImplementedError",
    "StemSeparator",
    "StemTrack",
    "StemsResult",
    "StepContext",
    "StepDefinition",
    "StepFailure",
    "StepNotRetryableError",
    "StepNotRunnableError",
    "StepOutcome",
    "StepRunner",
    "StepState",
    "StepStatus",
    "StepView",
    "TempoAndKeyRunner",
    "TranscribeRunner",
    "Transcriber",
    "TranscriptionResult",
    "UnknownStepError",
    "build_default_pipeline",
]
