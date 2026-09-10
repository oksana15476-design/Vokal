"""Задания обработки: запуск, статус, повтор.

Одно правило определяет здесь почти все: **прогресс считается по выполняемым
шагам**. Шаг, за которым нет подключенной реализации, получает статус
`skipped` и не может дойти до `done` — ни при запуске, ни при повторе. То же
самое уже сделано в двух местах, и третьего мнения тут быть не должно:

- на экране обработки (`runnableStepIds` в `src/App.tsx`);
- в оркестраторе конвейера (`PipelineRun.progress_percent`).

Состав выполняемых шагов решается один раз, до запуска. Пересматривать его по
ходу нельзя: знаменатель прогресса менялся бы на лету, и полоса ездила бы
назад.

Очереди у нас нет, и синхронно гонять обработку звука внутри HTTP-запроса
нельзя. Поэтому запуск задания **создает план и фиксирует его**, а не
выполняет работу. Когда появится первый настоящий провайдер, вместе с ним
обязана появиться очередь — иначе запрос будет держать соединение весь разбор
песни.

Второе правило: **статус двигают переходы, а не присвоение**. Раньше статус
писался туда, куда его положил вызывающий, и задание могло уехать из
«готово» обратно в «в очереди», а из «в очереди» — сразу в «готово», минуя
работу. Теперь допустимые пары перечислены в `ALLOWED_TRANSITIONS`, а
недопустимая отвечает отказом `invalid_job_transition` **до** записи в базу.
Переход в тот же статус тоже недопустим: повторная запись ничего не меняет и
прячет ошибку вызывающего.

Третье: **задание не заводится, пока обрабатывать нечем**. Ни один шаг
конвейера не подключен, и задание в этих условиях рождалось сразу «готовым»
со стопроцентным прогрессом — экран показывал зеленую галочку за работу,
которой не было, а повтор был недостижим (`retry_job` требует статус
`error`). Вместо муляжа запуск отвечает `501` и называет, чего не хватает.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import select

from app.api.not_implemented import CONTRACT_DOC, NOT_IMPLEMENTED_CODE
from app.api.schemas.enums import JobStatus, ProcessingGoalId, ProcessingStepStatus
from app.api.schemas.jobs import ProcessingJobOut, ProcessingStepOut
from app.db import enums, models
from app.db.repositories import (
    JobCreate,
    JobPatch,
    JobStepCreate,
    JobStepPatch,
    ProjectPatch,
    Repositories,
)
from app.pipeline import AudioRef, PipelineRun, build_default_pipeline
from app.pipeline.orchestrator import PipelineOrchestrator
from app.services.projects import ProjectRefusal

#: Через сколько миллисекунд спрашивать статус снова. Интервал называет сервер,
#: а не клиент: иначе он становится случайной константой в интерфейсе, и
#: очередь получает либо шквал запросов, либо задержку показа результата.
POLL_INTERVAL_MS = 1000

#: Статусы, после которых спрашивать больше не о чем.
TERMINAL_STATUSES: frozenset[enums.JobStatus] = frozenset(
    {enums.JobStatus.READY, enums.JobStatus.WARNING, enums.JobStatus.ERROR}
)

#: Статусы, при которых задание считается идущим.
LIVE_STATUSES: frozenset[enums.JobStatus] = frozenset(
    {enums.JobStatus.QUEUED, enums.JobStatus.RUNNING}
)

#: Шаги, дошедшие до конца благополучно. Совпадает с `TERMINAL_OK` оркестратора.
STEP_OK: frozenset[enums.JobStepStatus] = frozenset(
    {enums.JobStepStatus.DONE, enums.JobStepStatus.WARNING}
)

#: Статус, в котором задание рождается. Единственный: работа еще не начиналась,
#: и любой другой статус на старте — это отчет о несделанном.
INITIAL_STATUS = enums.JobStatus.QUEUED

#: Допустимые переходы статуса задания. Все, чего здесь нет, — отказ.
#:
#: Смысл каждой строки:
#: `queued` — либо взяли в работу, либо не смогли даже начать;
#: `running` — работа кончилась одним из трех исходов;
#: `ready` и `warning` — конец пути: повторная обработка это новое задание,
#: а не воскрешение старого, иначе история запусков теряется;
#: `error` — упавшее задание возвращается в очередь повтором, и только так.
ALLOWED_TRANSITIONS: dict[enums.JobStatus, frozenset[enums.JobStatus]] = {
    enums.JobStatus.QUEUED: frozenset({enums.JobStatus.RUNNING, enums.JobStatus.ERROR}),
    enums.JobStatus.RUNNING: frozenset(
        {enums.JobStatus.READY, enums.JobStatus.WARNING, enums.JobStatus.ERROR}
    ),
    enums.JobStatus.READY: frozenset(),
    enums.JobStatus.WARNING: frozenset(),
    enums.JobStatus.ERROR: frozenset({enums.JobStatus.QUEUED}),
}

#: Чего не хватает, чтобы обработка заработала. Идет прямо в `details.missing`
#: отказа: по этому перечню видно, чей это батч, а не «когда-нибудь потом».
PIPELINE_MISSING = (
    "провайдеры шагов конвейера (app/pipeline/providers.py: подключено ноль из восьми)",
    "исполнитель заданий: очередь и воркер (в pyproject нет ни celery, ни arq, ни dramatiq)",
)

#: Ответ на запуск обработки, пока выполнять нечего.
NOTHING_RUNS_MESSAGE = (
    "Обработка звука не выполняется: ни один шаг конвейера не подключен. "
    "Задание не заводится, чтобы не показывать «готово» за несделанную работу."
)


class JobRefusal(ProjectRefusal):
    """Отказ задания. Отдельный тип, общий перевод в HTTP.

    Наследование не ради иерархии: роутеры ловят один тип и одинаково
    превращают отказ в общий конверт ошибки, а по имени класса в логе видно,
    чей это отказ.
    """


# --- план и его хранение -----------------------------------------------------


def audio_ref_for(upload: models.Upload) -> AudioRef | None:
    """Ссылка на исходник для конвейера.

    Без ключа объекта ссылки нет: обрабатывать нечего, и подставлять сюда
    выдуманный ключ нельзя — шаг упал бы уже внутри провайдера, где причина
    видна хуже.
    """
    if not upload.storage_key:
        return None
    return AudioRef(
        artifact_id=str(upload.id),
        storage_key=upload.storage_key,
        duration_seconds=float(upload.duration_seconds),
        sample_rate=upload.sample_rate or 0,
        channels=upload.channels or 0,
        audio_format=upload.file_format.value,
    )


def plan_run(
    run_id: str,
    upload: models.Upload | None,
    *,
    orchestrator: PipelineOrchestrator | None = None,
) -> PipelineRun:
    """Собрать задание конвейера и один раз решить, какие шаги выполняются.

    `orchestrator` подставляется снаружи, когда набор адаптеров отличается от
    продуктового: сегодня это тесты пути «шаг подключен», завтра — сборка с
    первым настоящим провайдером. Умолчание остается честным состоянием
    продукта: не подключено ничего.
    """
    resolved = orchestrator or build_default_pipeline()
    return resolved.create_run(run_id, audio_ref_for(upload) if upload else None)


async def _persist_run(
    repos: Repositories,
    *,
    project: models.Project,
    run: PipelineRun,
    idempotency_key: str,
) -> tuple[models.Job, list[models.JobStep]]:
    snapshot = run.snapshot()
    # Сюда доходит только план, в котором есть что выполнять: пустой отсеян в
    # `start_job` отказом, а не записан заданием с прогрессом 100.
    check_initial_status(enums.JobStatus(snapshot.status.value))
    warnings = list(snapshot.warnings)

    credits = None
    if isinstance(project.cost_estimate, dict):
        raw = project.cost_estimate.get("credits")
        credits = int(raw) if isinstance(raw, int) else None

    job = await repos.jobs.create(
        JobCreate(
            project_id=project.id,
            idempotency_key=idempotency_key,
            status=enums.JobStatus(snapshot.status.value),
            progress_percent=snapshot.progress_percent,
            warnings=warnings,
            cost_credits=credits,
            # Версии модели нет, и писать сюда что-либо нельзя: по этому полю
            # потом определяют, какой запуск какой модели создал материал
            # (`docs/architecture.md`).
            model_version=None,
        )
    )
    await repos.session.flush()

    steps: list[models.JobStep] = []
    for position, view in enumerate(snapshot.steps):
        steps.append(
            await repos.job_steps.create(
                JobStepCreate(
                    job_id=job.id,
                    step_key=view.id,
                    label=view.label,
                    status=enums.JobStepStatus(view.status.value),
                    # Причина пропуска важнее описания шага: пользователю нужно
                    # знать, почему работа не будет сделана, а не что она была бы.
                    detail=view.skip_reason or view.detail,
                    position=position,
                )
            )
        )
    await repos.session.flush()
    return job, steps


# --- чтение ------------------------------------------------------------------


async def steps_of(repos: Repositories, job: models.Job) -> list[models.JobStep]:
    return list(await repos.job_steps.list_for_job(job.id))


async def latest_job(repos: Repositories, project_id: uuid.UUID) -> models.Job | None:
    """Последнее задание песни. Порядок — по времени создания."""
    jobs = await repos.jobs.list_for_project(project_id)
    return jobs[-1] if jobs else None


async def latest_jobs_for_projects(
    repos: Repositories, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[models.Job, list[models.JobStep]]]:
    """Последние задания сразу для всей страницы списка.

    Двумя запросами, а не по одному на песню: список открывается часто, и
    запрос на строку превращает его в десятки обращений к базе.
    """
    if not project_ids:
        return {}

    rows = await repos.session.execute(
        select(models.Job)
        .where(models.Job.project_id.in_(project_ids), models.Job.deleted_at.is_(None))
        .order_by(models.Job.project_id, models.Job.created_at, models.Job.id)
    )
    by_project: dict[uuid.UUID, models.Job] = {}
    for job in rows.scalars().all():
        by_project[job.project_id] = job

    job_ids = [job.id for job in by_project.values()]
    if not job_ids:
        return {}

    step_rows = await repos.session.execute(
        select(models.JobStep)
        .where(models.JobStep.job_id.in_(job_ids), models.JobStep.deleted_at.is_(None))
        .order_by(models.JobStep.job_id, models.JobStep.position, models.JobStep.id)
    )
    steps_by_job: dict[uuid.UUID, list[models.JobStep]] = {}
    for step in step_rows.scalars().all():
        steps_by_job.setdefault(step.job_id, []).append(step)

    return {
        project_id: (job, steps_by_job.get(job.id, [])) for project_id, job in by_project.items()
    }


async def owned_job(repos: Repositories, job_id: str, user_id: str) -> models.Job:
    """Задание вместе с проверкой прав через песню, которой оно принадлежит."""
    try:
        parsed = uuid.UUID(job_id)
    except ValueError as error:
        raise JobRefusal(404, "not_found", "Задание не найдено.") from error

    job = await repos.jobs.get(parsed)
    if job is None:
        raise JobRefusal(404, "not_found", "Задание не найдено.")
    project = await repos.projects.get(job.project_id)
    if project is None:
        raise JobRefusal(404, "not_found", "Задание не найдено.")
    if str(project.user_id) != str(user_id):
        raise JobRefusal(403, "forbidden", "Доступ к этому заданию закрыт.")
    return job


# --- правила переходов -------------------------------------------------------


def _transition_message(current: enums.JobStatus, target: enums.JobStatus) -> str:
    """Текст отказа. Разный, потому что причины разные, и обе видит человек."""
    if current is target:
        return (
            "Задание уже в этом состоянии. Повторная запись статуса ничего не меняет "
            "и прячет ошибку вызывающего."
        )
    if not ALLOWED_TRANSITIONS[current]:
        return (
            "Задание уже завершено: вернуть его в работу нельзя. "
            "Повторная обработка — это новый запуск, а не воскрешение старого."
        )
    return f"Из состояния «{current.value}» задание не переходит в «{target.value}»."


def check_transition(current: enums.JobStatus, target: enums.JobStatus) -> None:
    """Пропустить допустимый переход и отказать в остальных.

    Отказ, а не молчаливое присвоение: статус задания — это то, что показано
    пользователю, и запись «готово» поверх «упало» стирает сам факт сбоя.
    Проверка идет **до** записи, поэтому отказ не оставляет следа.
    """
    if target in ALLOWED_TRANSITIONS[current]:
        return
    raise JobRefusal(
        409,
        "invalid_job_transition",
        _transition_message(current, target),
        details={"from": current.value, "to": target.value},
    )


def check_initial_status(status: enums.JobStatus) -> None:
    """Задание рождается только в очереди.

    Любой другой статус на старте — отчет о работе, которой не было: `ready`
    без единого выполненного шага читается экраном как разобранная песня.
    """
    if status is INITIAL_STATUS:
        return
    raise JobRefusal(
        409,
        "invalid_job_start",
        f"Задание не может начаться в состоянии «{status.value}»: работа еще не шла.",
        details={"status": status.value, "expected": INITIAL_STATUS.value},
    )


async def transition_job(
    repos: Repositories,
    *,
    job: models.Job,
    target: enums.JobStatus,
    patch: JobPatch | None = None,
) -> models.Job:
    """Перевести задание в новый статус, если переход допустим.

    `patch` несет то, что меняется вместе со статусом (прогресс, счетчик
    повторов, код ошибки). Статус в нем не задается: его называет `target`, и
    двух источников статуса в одной записи быть не должно.
    """
    check_transition(job.status, target)
    return await repos.jobs.update(job.id, replace(patch or JobPatch(), status=target))


# --- правила прогресса -------------------------------------------------------


def progress_from_steps(steps: Sequence[models.JobStep]) -> int:
    """Прогресс по выполняемым шагам.

    Знаменатель — шаги, которые вообще будут выполняться. Пропущенный шаг в
    знаменатель не попадает: иначе полоса рисует проценты за работу, которой
    не будет. Пустой набор — это 100: работа окончена, а не застряла.

    Правило повторяет `PipelineRun.progress_percent` и `runnableStepIds` на
    фронтенде. Совпадение с оркестратором закреплено тестом, а не доверием.
    """
    runnable = [step for step in steps if step.status is not enums.JobStepStatus.SKIPPED]
    if not runnable:
        return 100
    completed = sum(1 for step in runnable if step.status in STEP_OK)
    return min(100, round(completed / len(runnable) * 100))


def poll_after_ms(status: enums.JobStatus) -> int | None:
    return None if status in TERMINAL_STATUSES else POLL_INTERVAL_MS


def job_out(job: models.Job, steps: Sequence[models.JobStep]) -> ProcessingJobOut:
    """Задание в форме контракта.

    Прогресс пересчитывается из шагов, а не читается из колонки. Колонка —
    снимок на момент записи; шаги — то, что есть сейчас. Две точки правды
    расходятся молча, и расходится всегда та, которую показывают.
    """
    return ProcessingJobOut(
        id=str(job.id),
        project_id=str(job.project_id),
        status=JobStatus(job.status.value),
        steps=[
            ProcessingStepOut(
                id=step.step_key,
                label=step.label,
                status=ProcessingStepStatus(step.status.value),
                detail=step.detail or "",
            )
            for step in steps
        ],
        warnings=list(job.warnings or []),
        progress_percent=progress_from_steps(steps),
        error_code=job.error_code,
        retry_count=job.retry_count,
        created_at=job.created_at,
        updated_at=job.updated_at,
        poll_after_ms=poll_after_ms(job.status),
    )


# --- запуск ------------------------------------------------------------------


async def start_job(
    repos: Repositories,
    *,
    project: models.Project,
    upload: models.Upload | None,
    goal_id: ProcessingGoalId | None,
    force_restart: bool,
    idempotency_key: str | None,
    orchestrator: PipelineOrchestrator | None = None,
) -> tuple[models.Job, list[models.JobStep]]:
    """Завести задание обработки для песни.

    Отказывает в шести случаях, и каждый называет себя: цель не от этого
    сценария, файла у песни еще нет, задание уже идет, результат уже есть
    (нужен явный перезапуск), ключ повтора занят чужим заданием, выполнять
    нечего — ни один шаг конвейера не подключен.
    """
    if goal_id is not None:
        expected = "band-" if project.scenario is enums.Scenario.BAND else "lesson-"
        if not goal_id.value.startswith(expected):
            raise JobRefusal(
                422,
                "goal_mismatch",
                "Цель обработки не относится к сценарию этой песни.",
                details={"goalId": goal_id.value, "scenario": project.scenario.value},
            )
        if goal_id.value != project.processing_goal_id.value:
            await repos.projects.update(
                project.id,
                ProjectPatch(processing_goal_id=enums.ProcessingGoalId(goal_id.value)),
            )

    if upload is None or not upload.storage_key:
        # Песня заводится раньше файла (`app/services/projects.py`), поэтому
        # «песни без исходника» теперь бывают. Задание над пустотой создавать
        # нельзя: оно тут же оказалось бы завершенным, ничего не сделав.
        raise JobRefusal(
            409,
            "source_missing",
            "Файл этой песни еще не загружен: обрабатывать нечего.",
            details={"projectId": str(project.id)},
        )

    if idempotency_key:
        existing = await repos.jobs.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            if existing.project_id != project.id:
                raise JobRefusal(
                    409,
                    "idempotency_key_reused",
                    "Этот ключ повтора уже занят другим заданием.",
                )
            # Повтор с тем же ключом возвращает то же задание и не списывает
            # стоимость дважды.
            return existing, await steps_of(repos, existing)

    running = await latest_job(repos, project.id)
    if running is not None and running.status in LIVE_STATUSES:
        raise JobRefusal(
            409,
            "job_already_running",
            "Обработка этой песни уже идет.",
            details={"jobId": str(running.id)},
        )
    if running is not None and not force_restart:
        raise JobRefusal(
            409,
            "job_already_finished",
            "Обработка этой песни уже выполнялась. Для повторной нужен явный перезапуск.",
            details={"jobId": str(running.id), "status": running.status.value},
        )

    run = plan_run(str(uuid.uuid4()), upload, orchestrator=orchestrator)
    if run.nothing_runs:
        # Ни один шаг не выполняется. Записать такое задание значит завести
        # запись со статусом «готово» и прогрессом 100 над нетронутым звуком.
        raise JobRefusal(
            501,
            NOT_IMPLEMENTED_CODE,
            NOTHING_RUNS_MESSAGE,
            details={
                "endpoint": "POST /api/projects/{project_id}/jobs",
                "missing": list(PIPELINE_MISSING),
                "docs": CONTRACT_DOC,
            },
        )

    # Ключ повтора обязателен в базе. Без заголовка он собирается из
    # идентификатора задания: своего ключа клиент не назвал, и придумывать
    # ему устойчивый — значит склеить два разных запуска в один.
    key = idempotency_key or f"job:{run.run_id}"
    return await _persist_run(repos, project=project, run=run, idempotency_key=key)


# --- повтор ------------------------------------------------------------------


async def retry_job(
    repos: Repositories,
    *,
    job: models.Job,
    steps: Sequence[models.JobStep],
    from_step_id: str | None,
) -> tuple[models.Job, list[models.JobStep]]:
    """Повторить упавшее задание.

    Повторяется только то, что падало. Пропущенный шаг повтор не воскрешает:
    реализации за ним как не было, так и нет, и «повторить» его значило бы
    обещать работу, которой не будет.
    """
    if job.status is not enums.JobStatus.ERROR:
        # Отдельный отказ до проверки перехода: «повторять нечего» объясняет
        # больше, чем «из ready нельзя в queued», хотя запрещает то же самое.
        raise JobRefusal(
            409,
            "job_not_failed",
            "Повторять нечего: это задание не падало.",
            details={"status": job.status.value},
        )

    keys = [step.step_key for step in steps]
    if from_step_id is not None and from_step_id not in keys:
        raise JobRefusal(
            422,
            "unknown_step",
            "Такого шага в этом задании нет.",
            details={"stepId": from_step_id, "steps": keys},
        )

    start_at = keys.index(from_step_id) if from_step_id is not None else 0
    for position, step in enumerate(steps):
        if position < start_at:
            continue
        if step.status is enums.JobStepStatus.SKIPPED:
            continue
        if from_step_id is None and step.status is not enums.JobStepStatus.ERROR:
            continue
        await repos.job_steps.update(
            step.id, JobStepPatch(status=enums.JobStepStatus.QUEUED, detail=step.detail)
        )

    refreshed = await steps_of(repos, job)
    updated = await transition_job(
        repos,
        job=job,
        target=enums.JobStatus.QUEUED,
        patch=JobPatch(
            progress_percent=progress_from_steps(refreshed),
            retry_count=job.retry_count + 1,
            error_code=None,
        ),
    )
    return updated, refreshed
