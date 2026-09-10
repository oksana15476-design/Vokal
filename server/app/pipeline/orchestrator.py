"""Оркестратор задания: ведет шаги, считает прогресс и отвечает за сбои.

Три правила, ради которых он написан именно так.

1. Состав выполняемых шагов известен ДО запуска. Ровно как `runnableStepIds`
   на фронтенде: шаг, за которым нет провайдера, не выполняется, и знаменатель
   прогресса — только выполняемые шаги. Иначе полоса рисует проценты за работу,
   которой не будет.
2. Повтор ничего не задваивает. Идентификатор материала считается из задания,
   шага и имени, поэтому вторая попытка перезаписывает запись, а не добавляет
   вторую копию. Пройденный шаг второй раз не запускается вовсе.
3. Сбой не отменяет сделанного. Материалы пройденных шагов остаются, а отчет
   называет: что уцелело, что заблокировано и можно ли вообще повторять.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.pipeline.contracts import AudioRef
from app.pipeline.enums import ArtifactKind, RetryScope, RunStatus, StepStatus
from app.pipeline.errors import (
    PipelineError,
    StageFailedError,
    StepNotRetryableError,
    StepNotRunnableError,
    UnknownStepError,
)
from app.pipeline.steps import StepContext, StepOutcome, StepRunner

TERMINAL_OK = (StepStatus.DONE, StepStatus.WARNING)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, repr=False)
class RunArtifact:
    """Запись о материале, созданном шагом."""

    artifact_id: str
    step_id: str
    name: str
    kind: ArtifactKind
    storage_key: str | None = None
    confidence: float | None = None
    meta: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        # Ключ объекта в логи не идет: DELETION_AND_RETENTION_DESIGN.md.
        return f"RunArtifact(artifact_id={self.artifact_id!r}, kind={self.kind.value!r})"


@dataclass(frozen=True)
class StepFailure:
    """Сбой одного шага в разобранном виде."""

    step_id: str
    code: str
    message: str
    retryable: bool
    retry_scope: RetryScope
    attempts: int
    occurred_at: datetime


@dataclass(frozen=True)
class FailureReport:
    """Что произошло и что с этим делать.

    Отвечает на вопросы, ради которых модель ошибок и заводилась: что
    сохранилось на момент сбоя, что перезапускать, что перезапускать
    бесполезно.
    """

    failure: StepFailure
    completed_steps: tuple[str, ...]
    preserved_artifacts: tuple[str, ...]
    blocked_steps: tuple[str, ...]
    skipped_steps: tuple[str, ...]
    resumable: bool


@dataclass
class StepState:
    """Состояние шага внутри задания."""

    step_id: str
    label: str
    detail: str
    status: StepStatus
    runnable: bool
    skip_reason: str | None = None
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    artifact_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    failure: StepFailure | None = None
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StepView:
    id: str
    label: str
    status: StepStatus
    detail: str
    skip_reason: str | None


@dataclass(frozen=True)
class RunSnapshot:
    """Срез задания в той форме, которая нужна экрану обработки."""

    run_id: str
    status: RunStatus
    progress_percent: int
    nothing_runs: bool
    steps: tuple[StepView, ...]
    warnings: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    failure: FailureReport | None


@dataclass
class PipelineRun:
    """Задание: состояние шагов и накопленные материалы.

    Объект изменяемый: оркестратор ведет его по шагам, а слой хранения потом
    сохраняет. Все производные величины — свойства, а не поля, чтобы прогресс
    и статус нельзя было выставить руками мимо правил.
    """

    run_id: str
    source: AudioRef | None
    steps: dict[str, StepState]
    artifacts: dict[str, RunArtifact] = field(default_factory=dict)

    @property
    def step_states(self) -> tuple[StepState, ...]:
        return tuple(self.steps.values())

    def state_of(self, step_id: str) -> StepState:
        state = self.steps.get(step_id)
        if state is None:
            raise UnknownStepError(step_id=step_id)
        return state

    @property
    def runnable_step_ids(self) -> tuple[str, ...]:
        return tuple(state.step_id for state in self.step_states if state.runnable)

    @property
    def nothing_runs(self) -> bool:
        return not self.runnable_step_ids

    @property
    def progress_percent(self) -> int:
        """Прогресс по выполняемым шагам.

        Пустой набор — это 100: работа окончена, а не застряла. Так же считает
        экран обработки, и расхождение здесь было бы расхождением с тем, что
        видит пользователь.
        """
        runnable = self.runnable_step_ids
        if not runnable:
            return 100
        completed = sum(
            1 for state in self.step_states if state.runnable and state.status in TERMINAL_OK
        )
        return min(100, round(completed / len(runnable) * 100))

    @property
    def status(self) -> RunStatus:
        states = self.step_states
        if any(state.status is StepStatus.ERROR for state in states):
            return RunStatus.ERROR

        runnable = [state for state in states if state.runnable]
        if not runnable:
            # Выполнять нечего. Это не «готов результат», а «работа окончена»;
            # отличает одно от другого флаг `nothing_runs`.
            return RunStatus.READY

        if all(state.status in TERMINAL_OK for state in runnable):
            if any(state.status is StepStatus.WARNING for state in runnable):
                return RunStatus.WARNING
            return RunStatus.READY

        if any(state.status is StepStatus.RUNNING for state in runnable) or any(
            state.status in TERMINAL_OK for state in runnable
        ):
            return RunStatus.RUNNING

        return RunStatus.QUEUED

    @property
    def warnings(self) -> tuple[str, ...]:
        collected: list[str] = []
        for state in self.step_states:
            collected.extend(state.warnings)
        return tuple(collected)

    @property
    def failure(self) -> FailureReport | None:
        failed = next(
            (state for state in self.step_states if state.status is StepStatus.ERROR),
            None,
        )
        if failed is None or failed.failure is None:
            return None

        order = [state.step_id for state in self.step_states]
        failed_at = order.index(failed.step_id)
        completed = tuple(
            state.step_id for state in self.step_states if state.status in TERMINAL_OK
        )
        preserved: list[str] = []
        for state in self.step_states:
            if state.status in TERMINAL_OK:
                preserved.extend(state.artifact_ids)
        blocked = tuple(
            state.step_id
            for index, state in enumerate(self.step_states)
            if index > failed_at and state.runnable and state.status not in TERMINAL_OK
        )
        skipped = tuple(
            state.step_id for state in self.step_states if state.status is StepStatus.SKIPPED
        )
        return FailureReport(
            failure=failed.failure,
            completed_steps=completed,
            preserved_artifacts=tuple(preserved),
            blocked_steps=blocked,
            skipped_steps=skipped,
            resumable=failed.failure.retryable,
        )

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot(
            run_id=self.run_id,
            status=self.status,
            progress_percent=self.progress_percent,
            nothing_runs=self.nothing_runs,
            steps=tuple(
                StepView(
                    id=state.step_id,
                    label=state.label,
                    status=state.status,
                    detail=state.detail,
                    skip_reason=state.skip_reason,
                )
                for state in self.step_states
            ),
            warnings=self.warnings,
            artifact_ids=tuple(self.artifacts),
            failure=self.failure,
        )


class PipelineOrchestrator:
    """Ведет задание по шагам."""

    def __init__(
        self,
        runners: Sequence[StepRunner],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._runners = tuple(runners)
        self._clock = clock
        seen: set[str] = set()
        for runner in self._runners:
            step = runner.step
            if step.id in seen:
                raise ValueError(f"Шаг «{step.id}» описан в плане дважды.")
            for required in step.requires:
                if required not in seen:
                    # Зависимость от шага, который идет позже (или которого нет
                    # вовсе), — ошибка плана. Молча она превратилась бы в вечно
                    # невыполняемый шаг.
                    raise ValueError(
                        f"Шаг «{step.id}» требует шаг «{required}», которого нет раньше в плане."
                    )
            seen.add(step.id)
        self._by_id = {runner.step.id: runner for runner in self._runners}

    # --- Создание задания ------------------------------------------------

    def create_run(self, run_id: str, source: AudioRef | None = None) -> PipelineRun:
        """Собрать задание и один раз решить, какие шаги выполняются.

        Решение принимается заранее и не пересматривается по ходу: иначе
        знаменатель прогресса менялся бы на лету и полоса ездила бы назад.
        """
        states: dict[str, StepState] = {}
        for runner in self._runners:
            step = runner.step
            availability = runner.availability()
            blocking = next(
                (required for required in step.requires if not states[required].runnable),
                None,
            )

            if not availability.available:
                runnable = False
                skip_reason: str | None = availability.reason
            elif blocking is not None:
                runnable = False
                skip_reason = (
                    f"Не выполняется шаг «{states[blocking].label}», "
                    "без него этот шаг запускать не с чем."
                )
            else:
                runnable = True
                skip_reason = None

            states[step.id] = StepState(
                step_id=step.id,
                label=step.label,
                detail=step.detail,
                status=StepStatus.QUEUED if runnable else StepStatus.SKIPPED,
                runnable=runnable,
                skip_reason=skip_reason,
            )

        return PipelineRun(run_id=run_id, source=source, steps=states)

    # --- Выполнение ------------------------------------------------------

    def run_all(self, run: PipelineRun) -> PipelineRun:
        """Пройти план до конца или до первого сбоя.

        Повторный вызов на завершенном задании ничего не делает: пройденные
        шаги пропускаются по статусу, а не запускаются заново.
        """
        for runner in self._runners:
            state = run.state_of(runner.step.id)
            if not state.runnable or state.status in TERMINAL_OK:
                continue
            if state.status is StepStatus.ERROR:
                # Упавший шаг чинится через `retry_step`: молча переигрывать
                # его внутри общего прогона — значит скрыть сбой от вызывающего.
                break
            self._execute(run, runner, state)
            if state.status is StepStatus.ERROR:
                break
        return run

    def run_step(self, run: PipelineRun, step_id: str, *, force: bool = False) -> PipelineRun:
        """Выполнить один шаг.

        `force` переигрывает уже пройденный шаг. Невыполняемый шаг не запускает
        даже он: у такого шага результата не будет, и притворяться нечем.
        """
        runner = self._runner_for(step_id)
        state = run.state_of(step_id)

        if not state.runnable:
            raise StepNotRunnableError(step_id=step_id, reason=state.skip_reason or "")

        if state.status is StepStatus.ERROR:
            self._require_retryable(state)
        elif state.status in TERMINAL_OK and not force:
            return run

        self._execute(run, runner, state)
        return run

    def retry_step(self, run: PipelineRun, step_id: str) -> PipelineRun:
        """Повторить упавший шаг, не трогая остальные."""
        runner = self._runner_for(step_id)
        state = run.state_of(step_id)

        if not state.runnable:
            raise StepNotRunnableError(step_id=step_id, reason=state.skip_reason or "")
        if state.status is not StepStatus.ERROR:
            raise StepNotRetryableError(step_id=step_id, reason="Шаг не падал.")
        self._require_retryable(state)

        self._execute(run, runner, state)
        return run

    # --- Внутреннее ------------------------------------------------------

    def _runner_for(self, step_id: str) -> StepRunner:
        runner = self._by_id.get(step_id)
        if runner is None:
            raise UnknownStepError(step_id=step_id)
        return runner

    @staticmethod
    def _require_retryable(state: StepState) -> None:
        if state.failure is not None and not state.failure.retryable:
            raise StepNotRetryableError(step_id=state.step_id, reason=state.failure.message)

    def _execute(self, run: PipelineRun, runner: StepRunner, state: StepState) -> None:
        state.status = StepStatus.RUNNING
        state.started_at = self._clock()
        state.attempts += 1

        context = StepContext(
            run_id=run.run_id,
            step_id=state.step_id,
            attempt=state.attempts,
            source=run.source,
            results={
                other.step_id: other.data
                for other in run.step_states
                if other.status in TERMINAL_OK
            },
        )

        try:
            outcome = runner.run(context)
        except PipelineError as error:
            self._record_failure(state, error)
            return
        except Exception as error:  # noqa: BLE001 — чужой код падает как угодно
            # Текст чужого исключения в отчет не переносится: в нем может
            # оказаться ключ объекта в хранилище, а он не должен попадать ни в
            # логи, ни в ответ API (DELETION_AND_RETENTION_DESIGN.md).
            self._record_failure(
                state,
                StageFailedError(
                    code="stage_crashed",
                    message=(
                        "Шаг прервался неожиданной ошибкой "
                        f"({type(error).__name__}). Подробности — в логах задания."
                    ),
                ),
            )
            return

        self._record_success(run, state, outcome)

    def _record_failure(self, state: StepState, error: PipelineError) -> None:
        state.status = StepStatus.ERROR
        state.finished_at = self._clock()
        state.failure = StepFailure(
            step_id=state.step_id,
            code=error.code,
            message=error.message,
            retryable=error.retryable,
            retry_scope=error.retry_scope,
            attempts=state.attempts,
            occurred_at=state.finished_at,
        )

    def _record_success(self, run: PipelineRun, state: StepState, outcome: StepOutcome) -> None:
        artifact_ids: list[str] = []
        for produced in outcome.artifacts:
            # Идентификатор детерминирован. Поэтому вторая попытка перезаписывает
            # свою же запись, а не заводит вторую копию того же материала.
            artifact_id = f"{run.run_id}:{state.step_id}:{produced.name}"
            run.artifacts[artifact_id] = RunArtifact(
                artifact_id=artifact_id,
                step_id=state.step_id,
                name=produced.name,
                kind=produced.kind,
                storage_key=produced.storage_key,
                confidence=produced.confidence,
                meta=dict(produced.meta),
            )
            artifact_ids.append(artifact_id)

        # Материалы прошлой попытки, которых в новой нет, снимаются: иначе
        # после повтора в задании остался бы след несуществующего файла.
        for stale in set(state.artifact_ids) - set(artifact_ids):
            run.artifacts.pop(stale, None)

        state.status = outcome.status
        state.detail = outcome.detail
        state.warnings = outcome.warnings
        state.data = outcome.data
        state.artifact_ids = tuple(artifact_ids)
        state.failure = None
        state.finished_at = self._clock()
