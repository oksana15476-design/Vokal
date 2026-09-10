"""Тесты конвейера обработки песни.

Почему все в одном файле: зона батча — `app/pipeline/**` и этот файл. Делить
по модулям будет следующий батч, когда у конвейера появятся настоящие
провайдеры и очередь.

Главное, что проверяется здесь, — честность заглушки. Непрошедший шаг не имеет
права выглядеть как пройденный, а неподключенный провайдер не имеет права
вернуть правдоподобные аккорды. Ровно этой ошибкой продукт уже болел на
фронтенде: восемь шагов доходили до «готово» за несделанную работу.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.pipeline import (
    DEFAULT_STEP_DEFINITIONS,
    ArtifactKind,
    AudioRef,
    BeatGridResult,
    BeatTracker,
    ChordEvent,
    ChordRecognizer,
    ChordsResult,
    DemucsSeparator,
    KeyDetector,
    KeyResult,
    MidiPartDraft,
    NotConfiguredBeatTracker,
    NotConfiguredChordRecognizer,
    NotConfiguredKeyDetector,
    NotConfiguredSeparator,
    NotConfiguredTranscriber,
    PipelineError,
    PipelineOrchestrator,
    ProducedArtifact,
    ProviderAvailability,
    ProviderNotConfiguredError,
    ProviderSet,
    RetryScope,
    RunStatus,
    StageFailedError,
    StageNotImplementedError,
    StemSeparator,
    StemsResult,
    StemTrack,
    StepContext,
    StepDefinition,
    StepNotRetryableError,
    StepNotRunnableError,
    StepOutcome,
    StepRunner,
    StepStatus,
    Transcriber,
    TranscriptionResult,
    UnknownStepError,
    build_default_pipeline,
)

# --- Общая оснастка -----------------------------------------------------

SOURCE = AudioRef(
    artifact_id="upload-1",
    storage_key="projects/p1/source/original.wav",
    duration_seconds=222.0,
    sample_rate=44100,
    channels=2,
    audio_format="WAV",
)


def definition(step_id: str) -> StepDefinition:
    return StepDefinition(id=step_id, label=step_id, detail=f"Шаг {step_id}.")


class RecordingRunner(StepRunner):
    """Шаг-двойник: считает вызовы и делает то, что ему велели.

    Считать вызовы обязательно: идемпотентность — это утверждение «провайдера
    не дернули второй раз», и проверить его иначе нечем.
    """

    def __init__(
        self,
        step_id: str,
        *,
        available: bool = True,
        reason: str = "",
        outcome: StepOutcome | None = None,
        error: Exception | None = None,
        fail_times: int = 0,
    ) -> None:
        super().__init__(definition(step_id))
        self._available = available
        self._reason = reason
        self._outcome = outcome or StepOutcome(
            status=StepStatus.DONE,
            detail=f"{step_id}: готово",
            artifacts=(ProducedArtifact(name=step_id, kind=ArtifactKind.PART),),
        )
        self._error = error
        self._fail_times = fail_times
        self.calls = 0

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider_id=f"fake-{self.step.id}",
            available=self._available,
            reason=self._reason,
        )

    def run(self, context: StepContext) -> StepOutcome:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise StageFailedError(code="failed_separation", message="Шаг сорвался.")
        if self._error is not None:
            raise self._error
        return self._outcome


def orchestrator_for(*runners: StepRunner) -> PipelineOrchestrator:
    return PipelineOrchestrator(runners)


# --- Двойники подключенных провайдеров ----------------------------------
#
# Настоящих моделей нет, поэтому «подключенный провайдер» в тестах — это
# двойник. Он проверяет ровно то, ради чего конвейер и написан: подключение
# реализации должно быть подстановкой класса, а не правкой оркестратора.


class FakeSeparator(StemSeparator):
    provider_id = "fake-separator"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def separate(self, source: AudioRef, *, stems: tuple[str, ...]) -> StemsResult:
        return StemsResult(
            provider_id=self.provider_id,
            model_id="fake-model",
            stems=tuple(
                StemTrack(
                    name=name,
                    audio=AudioRef(
                        artifact_id=f"stem-{name}",
                        storage_key=f"projects/p1/stems/{name}.wav",
                        duration_seconds=222.0,
                        sample_rate=44100,
                        channels=2,
                        audio_format="WAV",
                    ),
                    confidence=0.5,
                )
                for name in stems
            ),
        )


class FakeBeatTracker(BeatTracker):
    provider_id = "fake-beats"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def track(self, source: AudioRef) -> BeatGridResult:
        return BeatGridResult(provider_id=self.provider_id, bpm=104.0, meter="4/4", confidence=0.9)


class FakeKeyDetector(KeyDetector):
    provider_id = "fake-key"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def detect(self, source: AudioRef) -> KeyResult:
        return KeyResult(provider_id=self.provider_id, key="Gm", confidence=0.8)


class FakeChordRecognizer(ChordRecognizer):
    provider_id = "fake-chords"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def recognize(self, source: AudioRef) -> ChordsResult:
        return ChordsResult(
            provider_id=self.provider_id,
            chords=(
                ChordEvent(bar=1, beat=1, chord="Gm", confidence=0.9),
                ChordEvent(bar=1, beat=3, chord="Eb", confidence=0.6),
            ),
        )


class FakeTranscriber(Transcriber):
    provider_id = "fake-transcriber"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def transcribe(self, source: AudioRef, *, part: str) -> TranscriptionResult:
        self.seen.append(source.artifact_id)
        return TranscriptionResult(
            provider_id=self.provider_id,
            parts=(
                MidiPartDraft(
                    part=part,
                    midi=ProducedArtifact(name=part, kind=ArtifactKind.MIDI),
                    confidence=0.4,
                ),
            ),
        )


# --- Задачи 1-5: интерфейсы и честные заглушки --------------------------


def test_interfaces_cannot_be_instantiated() -> None:
    """Интерфейс — контракт, а не готовый объект."""
    for interface in (StemSeparator, BeatTracker, KeyDetector, ChordRecognizer, Transcriber):
        with pytest.raises(TypeError):
            interface()  # type: ignore[abstract]


def test_not_configured_separator_says_it_is_not_connected() -> None:
    availability = NotConfiguredSeparator().availability()

    assert availability.available is False
    assert availability.reason  # причина обязательна: «нет» без объяснения бесполезно


def test_not_configured_separator_refuses_instead_of_inventing_stems() -> None:
    with pytest.raises(ProviderNotConfiguredError) as error:
        NotConfiguredSeparator().separate(SOURCE, stems=("vocals", "drums"))

    assert error.value.retryable is False
    assert error.value.retry_scope is RetryScope.NONE


def test_demucs_separator_is_marked_not_implemented() -> None:
    availability = DemucsSeparator().availability()

    assert availability.available is False
    assert availability.provider_id == "demucs"

    with pytest.raises(StageNotImplementedError):
        DemucsSeparator().separate(SOURCE, stems=("vocals",))


NOT_CONFIGURED_CALLS: tuple[tuple[str, object, Callable[[object], object]], ...] = (
    ("stems", NotConfiguredSeparator(), lambda p: p.separate(SOURCE, stems=("vocals",))),
    ("beats", NotConfiguredBeatTracker(), lambda p: p.track(SOURCE)),
    ("key", NotConfiguredKeyDetector(), lambda p: p.detect(SOURCE)),
    ("chords", NotConfiguredChordRecognizer(), lambda p: p.recognize(SOURCE)),
    ("midi", NotConfiguredTranscriber(), lambda p: p.transcribe(SOURCE, part="bass")),
)


@pytest.mark.parametrize(("name", "provider", "call"), NOT_CONFIGURED_CALLS)
def test_every_not_configured_provider_refuses_to_answer(
    name: str, provider: object, call: Callable[[object], object]
) -> None:
    """Ни одна заглушка не возвращает правдоподобные данные."""
    assert provider.availability().available is False  # type: ignore[attr-defined]

    with pytest.raises(ProviderNotConfiguredError):
        call(provider)


def test_availability_without_reason_is_rejected() -> None:
    """«Не подключено» без причины — это молчание, а не честный ответ."""
    with pytest.raises(ValueError):
        ProviderAvailability(provider_id="x", available=False, reason="")


def test_chord_confidence_is_required_per_chord() -> None:
    result = ChordsResult(
        provider_id="fake",
        chords=(
            ChordEvent(bar=1, beat=1, chord="Gm", confidence=0.91),
            ChordEvent(bar=1, beat=3, chord="Eb", confidence=0.62),
        ),
    )

    assert [chord.confidence for chord in result.chords] == [0.91, 0.62]


def test_confidence_outside_zero_one_is_rejected() -> None:
    with pytest.raises(ValueError):
        ChordEvent(bar=1, beat=1, chord="Gm", confidence=1.4)


def test_beat_and_key_results_carry_meter_and_key() -> None:
    beats = BeatGridResult(provider_id="fake", bpm=104.0, meter="4/4", confidence=0.8)
    key = KeyResult(provider_id="fake", key="Gm", confidence=0.7)

    assert (beats.bpm, beats.meter, key.key) == (104.0, "4/4", "Gm")


def test_transcription_result_points_at_midi() -> None:
    result = TranscriptionResult(
        provider_id="fake",
        parts=(
            MidiPartDraft(
                part="bass",
                midi=ProducedArtifact(name="bass", kind=ArtifactKind.MIDI),
                confidence=0.55,
            ),
        ),
    )

    assert result.parts[0].midi.kind is ArtifactKind.MIDI


def test_audio_ref_repr_hides_storage_key() -> None:
    """Ключ объекта не попадает в логи: требование DELETION_AND_RETENTION_DESIGN."""
    assert "original.wav" not in repr(SOURCE)
    assert SOURCE.artifact_id in repr(SOURCE)


# --- Задача 6: оркестратор, статусы, частичный результат ----------------


def test_new_run_is_queued_and_has_no_artifacts() -> None:
    run = orchestrator_for(RecordingRunner("a"), RecordingRunner("b")).create_run("run-1", SOURCE)

    assert run.status is RunStatus.QUEUED
    assert [state.status for state in run.step_states] == [StepStatus.QUEUED, StepStatus.QUEUED]
    assert run.artifacts == {}


def test_full_pass_marks_every_runnable_step_done() -> None:
    orchestrator = orchestrator_for(RecordingRunner("a"), RecordingRunner("b"))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.status is RunStatus.READY
    assert [state.status for state in run.step_states] == [StepStatus.DONE, StepStatus.DONE]
    assert run.progress_percent == 100
    assert len(run.artifacts) == 2


def test_step_can_finish_with_warning_and_run_reports_it() -> None:
    warned = RecordingRunner(
        "b",
        outcome=StepOutcome(
            status=StepStatus.WARNING,
            detail="Форма собрана частично.",
            warnings=("Границы припева определены неуверенно.",),
        ),
    )
    orchestrator = orchestrator_for(RecordingRunner("a"), warned)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.status is RunStatus.WARNING
    assert run.progress_percent == 100
    assert run.warnings == ("Границы припева определены неуверенно.",)


def test_outcome_cannot_claim_failure_status() -> None:
    """Сбой сообщается исключением. Иначе шаг может «упасть в готово»."""
    with pytest.raises(ValueError):
        StepOutcome(status=StepStatus.ERROR, detail="сломалось")


def test_run_is_running_while_queued_steps_remain() -> None:
    orchestrator = orchestrator_for(RecordingRunner("a"), RecordingRunner("b"))
    run = orchestrator.create_run("run-1", SOURCE)
    orchestrator.run_step(run, "a")

    assert run.status is RunStatus.RUNNING
    assert run.progress_percent == 50


def test_failure_in_the_middle_keeps_earlier_result() -> None:
    first = RecordingRunner("a")
    second = RecordingRunner(
        "b", error=StageFailedError(code="failed_separation", message="Слои не собрались.")
    )
    third = RecordingRunner("c")
    orchestrator = orchestrator_for(first, second, third)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.status is RunStatus.ERROR
    assert [state.status for state in run.step_states] == [
        StepStatus.DONE,
        StepStatus.ERROR,
        StepStatus.QUEUED,
    ]
    assert list(run.artifacts) == ["run-1:a:a"]  # результат первого шага уцелел
    assert third.calls == 0  # после сбоя дальше не идем


def test_non_runnable_step_is_skipped_with_reason() -> None:
    skipped = RecordingRunner("b", available=False, reason="Разделение на слои не подключено.")
    orchestrator = orchestrator_for(RecordingRunner("a"), skipped)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    state = run.state_of("b")
    assert state.status is StepStatus.SKIPPED
    assert state.skip_reason == "Разделение на слои не подключено."
    assert skipped.calls == 0


def test_default_pipeline_runs_nothing_and_says_so() -> None:
    """Сегодня не подключен ни один провайдер. Значит, разбор не создается."""
    orchestrator = build_default_pipeline()
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.nothing_runs is True
    assert run.artifacts == {}
    assert {state.status for state in run.step_states} == {StepStatus.SKIPPED}
    assert all(state.skip_reason for state in run.step_states)
    assert [state.step_id for state in run.step_states] == [
        step.id for step in DEFAULT_STEP_DEFINITIONS
    ]


def test_default_pipeline_step_ids_match_frontend() -> None:
    """Один и тот же список шагов, что у пользователя на экране."""
    assert [step.id for step in DEFAULT_STEP_DEFINITIONS] == [
        "normalize",
        "stems",
        "tempo",
        "structure",
        "chords",
        "midi",
        "notation",
        "director",
    ]


def test_connecting_one_provider_makes_its_step_runnable() -> None:
    """Подключение настоящей реализации — замена одного класса в наборе."""
    orchestrator = build_default_pipeline(ProviderSet(separator=FakeSeparator()))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.state_of("stems").status is StepStatus.DONE
    assert run.state_of("chords").status is StepStatus.SKIPPED
    assert run.nothing_runs is False
    assert run.progress_percent == 100  # единственный выполняемый шаг прошел
    assert len(run.artifacts) >= 1


# --- Задача 7: идемпотентность ------------------------------------------


def test_second_full_run_does_not_call_runners_again() -> None:
    first = RecordingRunner("a")
    second = RecordingRunner("b")
    orchestrator = orchestrator_for(first, second)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    orchestrator.run_all(run)

    assert (first.calls, second.calls) == (1, 1)
    assert len(run.artifacts) == 2


def test_repeated_step_returns_saved_result_without_duplicates() -> None:
    runner = RecordingRunner("a")
    orchestrator = orchestrator_for(runner)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    before = dict(run.artifacts)

    orchestrator.run_step(run, "a")

    assert runner.calls == 1
    assert run.artifacts == before
    assert run.state_of("a").attempts == 1


def test_forced_rerun_replaces_artifacts_instead_of_adding_second_copy() -> None:
    runner = RecordingRunner("a")
    orchestrator = orchestrator_for(runner)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    orchestrator.run_step(run, "a", force=True)

    assert runner.calls == 2
    assert len(run.artifacts) == 1
    assert run.state_of("a").attempts == 2


def test_retry_of_failed_step_does_not_restart_the_whole_run() -> None:
    first = RecordingRunner("a")
    flaky = RecordingRunner("b", fail_times=1)
    third = RecordingRunner("c")
    orchestrator = orchestrator_for(first, flaky, third)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    assert run.status is RunStatus.ERROR

    orchestrator.retry_step(run, "b")

    assert first.calls == 1  # пройденный шаг не переигрывается
    assert flaky.calls == 2
    assert run.state_of("b").status is StepStatus.DONE
    assert run.state_of("b").attempts == 2

    orchestrator.run_all(run)

    assert (first.calls, flaky.calls, third.calls) == (1, 2, 1)
    assert run.status is RunStatus.READY
    assert len(run.artifacts) == 3


def test_retry_after_failure_leaves_no_duplicate_artifacts() -> None:
    flaky = RecordingRunner("a", fail_times=1)
    orchestrator = orchestrator_for(flaky)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    orchestrator.retry_step(run, "a")

    assert len(run.artifacts) == 1


def test_run_all_after_failure_does_not_replay_the_failed_step() -> None:
    """Упавший шаг чинят повтором, а не тем, что прогон запустили еще раз."""
    failing = RecordingRunner(
        "a", error=StageFailedError(code="failed_separation", message="Сбой.")
    )
    orchestrator = orchestrator_for(failing, RecordingRunner("b"))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    orchestrator.run_all(run)

    assert failing.calls == 1
    assert run.status is RunStatus.ERROR


def test_unknown_step_is_a_loud_error() -> None:
    orchestrator = orchestrator_for(RecordingRunner("a"))
    run = orchestrator.create_run("run-1", SOURCE)

    with pytest.raises(UnknownStepError):
        orchestrator.run_step(run, "нет-такого")


# --- Задача 8: прогресс по выполняемым шагам ----------------------------


def test_progress_counts_only_runnable_steps() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a"),
        RecordingRunner("b", available=False, reason="Провайдер не подключен."),
        RecordingRunner("c"),
    )
    run = orchestrator.create_run("run-1", SOURCE)
    orchestrator.run_step(run, "a")

    # Знаменатель — два выполняемых шага из трех, а не три.
    assert run.runnable_step_ids == ("a", "c")
    assert run.progress_percent == 50


def test_progress_is_100_when_nothing_runs() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a", available=False, reason="Не подключено."),
        RecordingRunner("b", available=False, reason="Не подключено."),
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.runnable_step_ids == ()
    assert run.progress_percent == 100
    assert run.nothing_runs is True
    assert run.status is RunStatus.READY


def test_skipped_step_cannot_be_forced_to_done() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a", available=False, reason="Не подключено."),
    )
    run = orchestrator.create_run("run-1", SOURCE)

    with pytest.raises(StepNotRunnableError):
        orchestrator.run_step(run, "a", force=True)

    assert run.state_of("a").status is StepStatus.SKIPPED


def test_progress_does_not_move_on_failure() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a"),
        RecordingRunner("b", error=StageFailedError(code="failed_separation", message="Сбой.")),
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.progress_percent == 50  # засчитан только пройденный шаг


def test_progress_is_deterministic_for_the_same_state() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a"), RecordingRunner("b"), RecordingRunner("c")
    )
    run = orchestrator.create_run("run-1", SOURCE)
    orchestrator.run_step(run, "a")

    assert [run.progress_percent for _ in range(5)] == [33, 33, 33, 33, 33]


# --- Задача 9: модель ошибок --------------------------------------------


def test_failure_report_says_what_survived_and_what_is_blocked() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a"),
        RecordingRunner("b", available=False, reason="Не подключено."),
        RecordingRunner("c", error=StageFailedError(code="failed_transcription", message="Сбой.")),
        RecordingRunner("d"),
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    report = run.failure

    assert report is not None
    assert report.failure.step_id == "c"
    assert report.failure.code == "failed_transcription"
    assert report.completed_steps == ("a",)
    assert report.preserved_artifacts == ("run-1:a:a",)
    assert report.blocked_steps == ("d",)
    assert report.skipped_steps == ("b",)
    assert report.resumable is True


def test_not_configured_failure_is_not_retryable() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner(
            "a",
            error=ProviderNotConfiguredError(
                provider_id="demucs", message="Разделение на слои не подключено."
            ),
        )
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    report = run.failure

    assert report is not None
    assert report.failure.retryable is False
    assert report.failure.retry_scope is RetryScope.NONE
    assert report.resumable is False

    with pytest.raises(StepNotRetryableError):
        orchestrator.retry_step(run, "a")


def test_unexpected_exception_does_not_leak_its_text() -> None:
    """В тексте исключения может оказаться ключ объекта. В отчет он не идет."""
    orchestrator = orchestrator_for(
        RecordingRunner("a", error=RuntimeError("projects/p1/source/original.wav недоступен"))
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    report = run.failure

    assert report is not None
    assert report.failure.code == "stage_crashed"
    assert "original.wav" not in report.failure.message
    assert report.failure.retryable is True


def test_retry_is_refused_for_a_step_that_did_not_fail() -> None:
    orchestrator = orchestrator_for(RecordingRunner("a"))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    with pytest.raises(StepNotRetryableError):
        orchestrator.retry_step(run, "a")


def test_pipeline_errors_carry_machine_code_and_scope() -> None:
    error = StageFailedError(code="failed_separation", message="Слои не собрались.")

    assert isinstance(error, PipelineError)
    assert (error.code, error.retryable, error.retry_scope) == (
        "failed_separation",
        True,
        RetryScope.STEP,
    )


# --- Задача 10: снимок для интерфейса и общие правила -------------------


def test_snapshot_repeats_the_shape_the_screen_needs() -> None:
    orchestrator = orchestrator_for(
        RecordingRunner("a"),
        RecordingRunner("b", available=False, reason="Не подключено."),
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    snapshot = run.snapshot()

    assert snapshot.run_id == "run-1"
    assert snapshot.progress_percent == 100
    assert [step.status for step in snapshot.steps] == [StepStatus.DONE, StepStatus.SKIPPED]
    assert snapshot.nothing_runs is False


def test_step_statuses_match_the_frontend_contract() -> None:
    """Статусы конвейера обязаны совпадать со слоем хранения и с types.ts."""
    from app.db import enums as db_enums

    assert {status.value for status in StepStatus} == {
        status.value for status in db_enums.JobStepStatus
    }
    assert {status.value for status in RunStatus} == {status.value for status in db_enums.JobStatus}
    assert {kind.value for kind in ArtifactKind} == {kind.value for kind in db_enums.ArtifactType}


def test_user_texts_avoid_the_letter_yo() -> None:
    """Дом-стиль: в пользовательском тексте буквы «ё» нет."""
    orchestrator = build_default_pipeline()
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    texts = [state.skip_reason or "" for state in run.step_states]
    texts += [state.detail for state in run.step_states]
    texts += [definition.label for definition in DEFAULT_STEP_DEFINITIONS]
    texts += [definition.detail for definition in DEFAULT_STEP_DEFINITIONS]

    assert [text for text in texts if "ё" in text] == []


def test_run_records_when_a_step_finished() -> None:
    started = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    orchestrator = PipelineOrchestrator([RecordingRunner("a")], clock=lambda: started)
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.state_of("a").finished_at == started


# --- Подключенные провайдеры: темп, тональность, аккорды, MIDI ----------


def test_connected_beat_and_key_providers_fill_the_tempo_step() -> None:
    orchestrator = build_default_pipeline(
        ProviderSet(beat_tracker=FakeBeatTracker(), key_detector=FakeKeyDetector())
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    state = run.state_of("tempo")

    assert state.status is StepStatus.DONE
    assert (state.data["bpm"], state.data["meter"], state.data["key"]) == (104.0, "4/4", "Gm")


def test_tempo_step_needs_both_providers() -> None:
    """Размер без тональности — половина шага, а половину шага не показывают."""
    orchestrator = build_default_pipeline(ProviderSet(beat_tracker=FakeBeatTracker()))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.state_of("tempo").status is StepStatus.SKIPPED


def test_connected_chord_provider_keeps_confidence_of_every_chord() -> None:
    orchestrator = build_default_pipeline(ProviderSet(chord_recognizer=FakeChordRecognizer()))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    chords = run.state_of("chords").data["chords"]

    assert [chord.confidence for chord in chords] == [0.9, 0.6]


def test_transcription_works_on_stems_not_on_the_mix() -> None:
    transcriber = FakeTranscriber()
    orchestrator = build_default_pipeline(
        ProviderSet(separator=FakeSeparator(), transcriber=transcriber)
    )
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))

    assert run.state_of("midi").status is StepStatus.DONE
    assert SOURCE.artifact_id not in transcriber.seen  # микс в транскрипцию не уходит
    assert transcriber.seen == ["stem-vocals", "stem-bass", "stem-guitar", "stem-keys"]
    assert "run-1:midi:midi-bass" in run.artifacts


def test_transcription_is_skipped_without_a_separator() -> None:
    """Транскрипция без аудиослоев не выполняется, а не падает по ходу."""
    orchestrator = build_default_pipeline(ProviderSet(transcriber=FakeTranscriber()))
    run = orchestrator.run_all(orchestrator.create_run("run-1", SOURCE))
    state = run.state_of("midi")

    assert state.status is StepStatus.SKIPPED
    assert "Разделение на аудиослои" in (state.skip_reason or "")


def test_step_without_source_reports_missing_source() -> None:
    orchestrator = build_default_pipeline(ProviderSet(separator=FakeSeparator()))
    run = orchestrator.run_all(orchestrator.create_run("run-1"))
    report = run.failure

    assert report is not None
    assert report.failure.code == "missing_source"
    assert report.failure.retry_scope is RetryScope.RUN

    with pytest.raises(StepNotRetryableError):
        orchestrator.retry_step(run, "stems")
