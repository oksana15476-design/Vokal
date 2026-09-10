"""Сборка конвейера по умолчанию.

Отдельный модуль, потому что он единственный знает и про шаги, и про
оркестратор, и про набор адаптеров. Держать эту сборку внутри `steps.py`
нельзя: получилась бы кольцевая зависимость с оркестратором.

Сегодня по умолчанию не подключен ни один провайдер, поэтому собранный
конвейер не выполняет ни одного шага и говорит об этом по каждому. Это не
недоделка сборки, а точное состояние продукта: настоящей обработки звука нет.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.pipeline.orchestrator import PipelineOrchestrator, utc_now
from app.pipeline.providers import ProviderSet
from app.pipeline.steps import (
    STEP_BY_ID,
    ChordsRunner,
    NotConnectedRunner,
    SeparateStemsRunner,
    StepRunner,
    TempoAndKeyRunner,
    TranscribeRunner,
)

# Шаги, за которыми нет даже интерфейса: свой сервис для них еще не собран.
# Текст причины идет прямо в интерфейс, поэтому он объясняет, а не отписывается.
NOT_CONNECTED_REASONS: dict[str, str] = {
    "normalize": "Нормализация аудио не подключена: сервиса обработки звука еще нет.",
    "structure": "Разбор структуры песни не подключен: своего StructureDetector еще нет.",
    "notation": "Нотный вывод не подключен: рендер MusicXML и PDF еще не собран.",
    "director": "Ревью AI-директора не подключено: адаптера модели еще нет.",
}


def build_default_pipeline(
    providers: ProviderSet | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
) -> PipelineOrchestrator:
    """Собрать конвейер продукта на переданном наборе адаптеров."""
    resolved = providers or ProviderSet()

    runners: list[StepRunner] = [
        NotConnectedRunner(STEP_BY_ID["normalize"], reason=NOT_CONNECTED_REASONS["normalize"]),
        SeparateStemsRunner(STEP_BY_ID["stems"], resolved.separator),
        TempoAndKeyRunner(STEP_BY_ID["tempo"], resolved.beat_tracker, resolved.key_detector),
        NotConnectedRunner(STEP_BY_ID["structure"], reason=NOT_CONNECTED_REASONS["structure"]),
        ChordsRunner(STEP_BY_ID["chords"], resolved.chord_recognizer),
        TranscribeRunner(STEP_BY_ID["midi"], resolved.transcriber),
        NotConnectedRunner(STEP_BY_ID["notation"], reason=NOT_CONNECTED_REASONS["notation"]),
        NotConnectedRunner(STEP_BY_ID["director"], reason=NOT_CONNECTED_REASONS["director"]),
    ]
    return PipelineOrchestrator(runners, clock=clock)
