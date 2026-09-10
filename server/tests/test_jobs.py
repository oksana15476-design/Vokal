"""Тесты обработки: модель статусов, переходы и честный отказ запуска.

Написаны до реализации. Три обещания под проверкой.

1. **Недопустимый переход — отказ, а не тихое присвоение.** Статус задания
   двигают правила, а не тот, кто первым дошел до строки. Готовое задание не
   возвращается в работу, упавшее не становится готовым само собой. На каждую
   недопустимую пару статусов есть свой тест: перечень допустимых переходов
   выписан здесь заново и не читает таблицу из модуля, иначе тест повторял бы
   ошибку реализации.

2. **Запускать нечего — так и говорим.** Ни один шаг конвейера не подключен и
   очереди нет. Задание, которое в этих условиях рождается «готовым» со
   стопроцентным прогрессом, — это муляж обработки: экран покажет зеленую
   галочку за работу, которой не было. Правильный ответ — `501` с перечнем
   того, чего не хватает.

3. **Обрабатывать без файла нельзя.** Песню теперь заводят до загрузки, и
   запуск обработки на песне без исходника обязан отказать своим кодом, а не
   создать задание ни над чем.

Провайдер в тестах подставной ровно там, где проверяется путь «шаг подключен»:
настоящих моделей в проекте нет, и без подстановки этот путь не существует
вовсе. Работу он не выполняет — только отвечает «я доступен».
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.db import enums, models
from app.db.repositories import (
    JobCreate,
    ProjectCreate,
    Repositories,
    UploadCreate,
    UserCreate,
)
from app.pipeline import build_default_pipeline
from app.pipeline.contracts import AudioRef, ProviderAvailability, StemSeparator, StemsResult
from app.pipeline.providers import ProviderSet
from app.services import jobs as service

pytestmark = pytest.mark.asyncio


# --- вспомогательное ---------------------------------------------------------


class AvailableSeparator(StemSeparator):
    """Провайдер, который отвечает «подключен». Работу не делает и не обещает."""

    provider_id = "test-separator"

    def availability(self) -> ProviderAvailability:
        return ProviderAvailability(provider_id=self.provider_id, available=True)

    def separate(self, source: AudioRef, *, stems: Sequence[str]) -> StemsResult:
        raise AssertionError("Шаг не должен выполняться: тест проверяет только план.")


def connected_pipeline():
    """Конвейер, в котором есть хотя бы один выполняемый шаг."""
    return build_default_pipeline(ProviderSet(separator=AvailableSeparator()))


async def make_project(
    session: AsyncSession, *, contact: str = "band@example.test"
) -> models.Project:
    repos = Repositories(session)
    user = await repos.users.create(UserCreate(contact=contact))
    return await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Late Train Home: подготовка",
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
        )
    )


async def make_upload(session: AsyncSession, project: models.Project) -> models.Upload:
    return await Repositories(session).uploads.create(
        UploadCreate(
            project_id=project.id,
            file_name="track.wav",
            file_format=enums.UploadFormat.WAV,
            duration_seconds=180,
            quality=enums.UploadQuality.GOOD,
            size_bytes=4096,
            sample_rate=44100,
            channels=2,
            storage_key=f"source/{project.id}/track.wav",
        )
    )


async def make_job(
    session: AsyncSession, project: models.Project, *, status: enums.JobStatus
) -> models.Job:
    return await Repositories(session).jobs.create(
        JobCreate(
            project_id=project.id,
            idempotency_key=f"job:{uuid.uuid4()}",
            status=status,
        )
    )


def build_app(session: AsyncSession, user_id: object):
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


# --- Задача 3: модель статусов ----------------------------------------------

QUEUED = enums.JobStatus.QUEUED
RUNNING = enums.JobStatus.RUNNING
READY = enums.JobStatus.READY
WARNING = enums.JobStatus.WARNING
ERROR = enums.JobStatus.ERROR

#: Перечень допустимых переходов выписан здесь заново, а не прочитан из модуля.
#: Тест, который читает таблицу реализации, повторяет ее ошибку вместе с ней.
EXPECTED_ALLOWED: frozenset[tuple[enums.JobStatus, enums.JobStatus]] = frozenset(
    {
        (QUEUED, RUNNING),
        (QUEUED, ERROR),
        (RUNNING, READY),
        (RUNNING, WARNING),
        (RUNNING, ERROR),
        (ERROR, QUEUED),
    }
)

FORBIDDEN: list[tuple[enums.JobStatus, enums.JobStatus]] = [
    (current, target)
    for current in enums.JobStatus
    for target in enums.JobStatus
    if (current, target) not in EXPECTED_ALLOWED
]


async def test_transition_table_covers_every_status() -> None:
    """Статус без строки в таблице — дыра, через которую проходит что угодно."""
    assert set(service.ALLOWED_TRANSITIONS) == set(enums.JobStatus)


async def test_allowed_transitions_are_exactly_the_expected_ones() -> None:
    actual = {
        (current, target)
        for current, targets in service.ALLOWED_TRANSITIONS.items()
        for target in targets
    }
    assert actual == set(EXPECTED_ALLOWED)


@pytest.mark.parametrize(
    ("current", "target"),
    FORBIDDEN,
    ids=[f"{current.value}->{target.value}" for current, target in FORBIDDEN],
)
async def test_forbidden_transition_is_refused(
    current: enums.JobStatus, target: enums.JobStatus
) -> None:
    """Каждая недопустимая пара отвечает отказом с названной причиной."""
    with pytest.raises(service.JobRefusal) as raised:
        service.check_transition(current, target)

    refusal = raised.value
    assert refusal.status_code == 409
    assert refusal.code == "invalid_job_transition"
    assert refusal.details == {"from": current.value, "to": target.value}


ALLOWED = sorted(EXPECTED_ALLOWED, key=lambda pair: (pair[0].value, pair[1].value))


@pytest.mark.parametrize(
    ("current", "target"),
    ALLOWED,
    ids=[f"{current.value}->{target.value}" for current, target in ALLOWED],
)
async def test_allowed_transition_passes(current: enums.JobStatus, target: enums.JobStatus) -> None:
    service.check_transition(current, target)


@pytest.mark.parametrize(
    "status",
    [RUNNING, READY, WARNING, ERROR],
    ids=[status.value for status in (RUNNING, READY, WARNING, ERROR)],
)
async def test_job_cannot_be_born_in_a_worked_status(status: enums.JobStatus) -> None:
    """Задание, рожденное не в очереди, отчитывается о работе, которой не было."""
    with pytest.raises(service.JobRefusal) as raised:
        service.check_initial_status(status)

    assert raised.value.status_code == 409
    assert raised.value.code == "invalid_job_start"


async def test_job_is_born_in_the_queue() -> None:
    service.check_initial_status(QUEUED)


async def test_transition_writes_new_status(session: AsyncSession) -> None:
    project = await make_project(session)
    job = await make_job(session, project, status=QUEUED)

    updated = await service.transition_job(Repositories(session), job=job, target=RUNNING)

    assert updated.status is RUNNING


async def test_forbidden_transition_leaves_the_row_untouched(session: AsyncSession) -> None:
    """Отказ приходит до записи, а не после: иначе «нельзя» уже случилось."""
    repos = Repositories(session)
    project = await make_project(session)
    job = await make_job(session, project, status=READY)

    with pytest.raises(service.JobRefusal):
        await service.transition_job(repos, job=job, target=RUNNING)

    assert (await repos.jobs.get(job.id)).status is READY


# --- Задача 3: запуск отказывает, пока обрабатывать нечем --------------------


async def test_start_refuses_project_without_file(session: AsyncSession) -> None:
    """Песня заводится до файла, но обрабатывать без него нечего."""
    repos = Repositories(session)
    project = await make_project(session)

    with pytest.raises(service.JobRefusal) as raised:
        await service.start_job(
            repos,
            project=project,
            upload=None,
            goal_id=None,
            force_restart=False,
            idempotency_key=None,
            orchestrator=connected_pipeline(),
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "source_missing"


async def test_start_refuses_while_no_step_is_connected(session: AsyncSession) -> None:
    """Задание, рожденное «готовым» без единой выполненной работы, — муляж."""
    repos = Repositories(session)
    project = await make_project(session)
    upload = await make_upload(session, project)

    with pytest.raises(service.JobRefusal) as raised:
        await service.start_job(
            repos,
            project=project,
            upload=upload,
            goal_id=None,
            force_restart=False,
            idempotency_key=None,
        )

    refusal = raised.value
    assert refusal.status_code == 501
    assert refusal.code == "not_implemented"
    assert refusal.details is not None
    assert refusal.details["missing"], "отказ обязан называть, чего не хватает"
    # И ни одного задания в базе: отказ не оставляет следа обработки.
    assert await repos.jobs.list_for_project(project.id) == []


async def test_started_job_is_born_queued(session: AsyncSession) -> None:
    """Задание рождается в очереди, а не сразу готовым."""
    repos = Repositories(session)
    project = await make_project(session)
    upload = await make_upload(session, project)

    job, steps = await service.start_job(
        repos,
        project=project,
        upload=upload,
        goal_id=None,
        force_restart=False,
        idempotency_key=None,
        orchestrator=connected_pipeline(),
    )

    assert job.status is QUEUED
    assert steps, "план задания обязан быть записан"
    assert service.progress_from_steps(steps) == 0


async def test_started_job_keeps_skipped_steps_out_of_progress(session: AsyncSession) -> None:
    repos = Repositories(session)
    project = await make_project(session)
    upload = await make_upload(session, project)

    _, steps = await service.start_job(
        repos,
        project=project,
        upload=upload,
        goal_id=None,
        force_restart=False,
        idempotency_key=None,
        orchestrator=connected_pipeline(),
    )

    skipped = [step for step in steps if step.status is enums.JobStepStatus.SKIPPED]
    assert skipped, "шаги без реализации обязаны остаться пропущенными"
    assert all(step.detail for step in skipped), "пропуск обязан назвать причину"


# --- Задача 3: повтор --------------------------------------------------------


async def test_retry_refuses_job_that_did_not_fail(session: AsyncSession) -> None:
    repos = Repositories(session)
    project = await make_project(session)
    job = await make_job(session, project, status=READY)

    with pytest.raises(service.JobRefusal) as raised:
        await service.retry_job(repos, job=job, steps=[], from_step_id=None)

    assert raised.value.status_code == 409
    assert raised.value.code == "job_not_failed"


async def test_retry_returns_failed_job_to_the_queue(session: AsyncSession) -> None:
    repos = Repositories(session)
    project = await make_project(session)
    job = await make_job(session, project, status=ERROR)

    updated, _ = await service.retry_job(repos, job=job, steps=[], from_step_id=None)

    assert updated.status is QUEUED
    assert updated.retry_count == 1
    assert updated.error_code is None


# --- Задача 3: то же самое через HTTP ---------------------------------------


async def test_http_start_says_processing_is_not_connected(session: AsyncSession) -> None:
    repos = Repositories(session)
    project = await make_project(session)
    await make_upload(session, project)

    async with client_for(build_app(session, project.user_id)) as client:
        response = await client.post(f"/api/projects/{project.id}/jobs", json={})

    assert response.status_code == 501, response.text
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert error["details"]["missing"]
    assert await repos.jobs.list_for_project(project.id) == []


async def test_http_start_refuses_foreign_project(session: AsyncSession) -> None:
    project = await make_project(session)
    stranger = await make_project(session, contact="other@example.test")

    async with client_for(build_app(session, stranger.user_id)) as client:
        response = await client.post(f"/api/projects/{project.id}/jobs", json={})

    assert response.status_code == 403, response.text
    assert error_of(response)["code"] == "forbidden"
