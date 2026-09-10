"""Модель ошибок конвейера.

Одного текста ошибки мало. Чтобы после сбоя можно было ответить на три
вопроса — что уцелело, что перезапускать и что перезапускать бесполезно —
у каждой ошибки есть машинный код, признак повторяемости и область повтора.

Коды совпадают с перечнем в `docs/architecture.md` («Ошибки»): по ним
интерфейс и поддержка узнают случай, не разбирая русский текст.
"""

from __future__ import annotations

from app.pipeline.enums import RetryScope


class PipelineError(Exception):
    """Общий предок всех ошибок конвейера."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        retryable: bool,
        retry_scope: RetryScope,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_scope = retry_scope


class ProviderNotConfiguredError(PipelineError):
    """Провайдера нет. Повтор не поможет: сначала его надо подключить."""

    def __init__(self, *, provider_id: str, message: str) -> None:
        super().__init__(
            code="provider_not_configured",
            message=message,
            retryable=False,
            retry_scope=RetryScope.NONE,
        )
        self.provider_id = provider_id


class StageNotImplementedError(PipelineError):
    """Адаптер есть, реализации за ним нет. Тоже не лечится повтором."""

    def __init__(self, *, provider_id: str, message: str) -> None:
        super().__init__(
            code="stage_not_implemented",
            message=message,
            retryable=False,
            retry_scope=RetryScope.NONE,
        )
        self.provider_id = provider_id


class StageFailedError(PipelineError):
    """Шаг сорвался. По умолчанию повторяемый: сбои провайдеров чаще временные."""

    def __init__(
        self,
        *,
        code: str = "stage_failed",
        message: str,
        retryable: bool = True,
        retry_scope: RetryScope = RetryScope.STEP,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            retryable=retryable,
            retry_scope=retry_scope,
        )


class SourceMissingError(PipelineError):
    """Шагу нужен исходник, а его нет. Чинится новым заданием, не повтором шага."""

    def __init__(self, *, message: str = "У задания нет исходного аудио.") -> None:
        super().__init__(
            code="missing_source",
            message=message,
            retryable=False,
            retry_scope=RetryScope.RUN,
        )


class UnknownStepError(PipelineError):
    """Обращение к шагу, которого нет в плане. Молчать здесь опаснее, чем упасть."""

    def __init__(self, *, step_id: str) -> None:
        super().__init__(
            code="unknown_step",
            message=f"В плане обработки нет шага «{step_id}».",
            retryable=False,
            retry_scope=RetryScope.NONE,
        )
        self.step_id = step_id


class StepNotRunnableError(PipelineError):
    """Попытка выполнить шаг, который на этом пути не выполняется.

    Именно здесь держится главное правило прогресса: у шага со статусом
    «не выполняется» результата не будет, и никакой флаг не имеет права
    довести его до «готово».
    """

    def __init__(self, *, step_id: str, reason: str) -> None:
        super().__init__(
            code="step_not_runnable",
            message=f"Шаг «{step_id}» не выполняется. {reason}",
            retryable=False,
            retry_scope=RetryScope.NONE,
        )
        self.step_id = step_id
        self.reason = reason


class StepNotRetryableError(PipelineError):
    """Повтор шага невозможен: он не падал или его сбой повтором не лечится."""

    def __init__(self, *, step_id: str, reason: str) -> None:
        super().__init__(
            code="step_not_retryable",
            message=f"Шаг «{step_id}» повторить нельзя. {reason}",
            retryable=False,
            retry_scope=RetryScope.NONE,
        )
        self.step_id = step_id
        self.reason = reason
