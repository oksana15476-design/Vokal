"""Проекты: создание из загрузки, список, карточка целиком.

Три вещи, объясняющие форму этого модуля.

**Первое. Песня заводится раньше файла, и этим разорван круг.** Раньше
`uploads.project_id` был обязателен (`app/db/models.py`), а
`ProjectCreateRequest.upload_id` — тоже обязателен: клиент не мог создать
первым ни песню, ни загрузку, и первый же пользовательский сценарий был
непроходим. Круг разрезан со стороны песни: `create_project` заводит строку
`projects` сам, без файла, а файл приходит в нее вторым запросом
(`POST /api/uploads` с `projectId`).

Почему с этой стороны, а не через nullable `uploads.project_id`: загрузка без
песни — это объект в хранилище, за который никто не отвечает. Его нечем
показать, некому удалить по запросу пользователя и не с чем связать согласие,
а колонка `project_id` в базе перестала бы гарантировать, что у каждого файла
есть хозяин. Пустая песня, наоборот, — обычное состояние экрана: песня
заведена, файл еще не выбран. Схема базы при этом не менялась, и миграция не
нужна.

Второй путь создания сохранен: `adopt_upload` оформляет песню поверх строки,
которая уже держит принятый файл. Так устроены демо-данные (`app/db/seed.py`),
и так же будет выглядеть импорт со стороны.

**Второе. Согласие пишется вместе с текстом.** Не только версия: запись должна
читаться, даже если реестр версий когда-нибудь потеряют (`types.ts`).

**Третье. Разбор чужой песни не подставляется никогда.** У загруженного файла
разбора нет, и `source = none` с пустыми значениями честнее, чем тональность и
аккорды другой записи, которым пользователь поверит.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import Select, func, select

from app.api.consent_versions import consent_text_by_id
from app.api.schemas.artifacts import ArtifactOut, ArtifactPreviewOut, StagePackOut
from app.api.schemas.consent import LegalConsentOut
from app.api.schemas.deletion import DataRetentionStateOut
from app.api.schemas.enums import (
    ArtifactAudience,
    ArtifactFormat,
    ArtifactStatus,
    ArtifactType,
    AssignmentStatus,
    BassStrings,
    CostComplexity,
    CostTier,
    DeletionState,
    LessonDifficulty,
    MusicianLevel,
    MusicianRole,
    NotationReading,
    ProcessingGoalId,
    ReviewStatus,
    Scenario,
    ShareRecipientRole,
    ShareRecipientStatus,
    StudentLevel,
    TeacherFormat,
    UploadState,
    VersionKind,
    VersionStatus,
)
from app.api.schemas.jobs import ProcessingJobOut
from app.api.schemas.people import (
    AssignmentOut,
    BandLineupOut,
    ClassGroupOut,
    LessonOut,
    MusicianOut,
    StudentProfileOut,
    TeacherProfileOut,
)
from app.api.schemas.projects import (
    CostEstimateOut,
    ProjectCreateRequest,
    ProjectOut,
    ProjectSetup,
    ProjectSummary,
    SetupSnapshot,
)
from app.api.schemas.review import ReviewCommentOut, ReviewIssueOut
from app.api.schemas.sharing import ShareRecipientOut
from app.api.schemas.song import ProcessingGoalOut, SongAnalysisOut
from app.api.schemas.uploads import UploadOut
from app.api.schemas.versions import ArrangementVersionOut
from app.db import enums, models
from app.db.repositories import (
    EntityNotFound,
    ProjectCreate,
    ProjectPatch,
    Repositories,
    VersionCreate,
)
from app.services import uploads as uploads_service

_SETUP_ADAPTER: TypeAdapter[Any] = TypeAdapter(ProjectSetup)


class ProjectRefusal(Exception):
    """Отказ с кодом HTTP и машинным кодом ошибки.

    Тот же прием, что в загрузке (`app/services/uploads.py`): сервис не знает
    про FastAPI и не собирает ответ, но и не теряет причину отказа. Роутер
    переводит его в общий конверт ошибки.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


# --- каталог целей обработки -------------------------------------------------

# Тексты перенесены дословно из `src/domain/mockData.ts`: они уже прошли
# продуктовую приемку и показываются пользователю сегодня. Сочинять здесь
# вторую формулировку того же — верный способ развести экран и сервер.
#
# Развилка владельца (`docs/api/README.md`, пункт 2): кто владеет этими
# текстами — сервер или фронтенд. Пока `ProjectOut.processingGoal` требует
# подписи, их обязан отдавать сервер.
_GOAL_TEXTS: dict[ProcessingGoalId, tuple[str, str, tuple[str, ...]]] = {
    ProcessingGoalId.BAND_ANALYSIS: (
        "Разобрать песню",
        "Понять форму, тональность, аккорды, партии и сомнительные места.",
        ("Форма", "Аккорды", "Партии", "Сомнительные такты"),
    ),
    ProcessingGoalId.BAND_REHEARSAL: (
        "Подготовить репетицию",
        "Собрать материалы для всей группы и репетиционные треки.",
        ("Stage Pack", "Партии", "Минус", "Клик"),
    ),
    ProcessingGoalId.BAND_PERFORMANCE: (
        "Подготовить выступление",
        "Сделать концертную версию с акцентами, концовкой и выдачей материалов.",
        ("Концертная версия", "Партии", "ZIP", "История правок"),
    ),
    ProcessingGoalId.BAND_MINUS: (
        "Сделать минус",
        "Подготовить аудиослои, минус и треки без выбранного инструмента.",
        ("Аудиослои", "Минус", "Репетиционные треки"),
    ),
    ProcessingGoalId.BAND_PARTS: (
        "Разложить на партии",
        "Собрать ноты, TAB, MIDI и материалы по инструментам.",
        ("Ноты", "TAB", "MIDI", "PDF"),
    ),
    ProcessingGoalId.BAND_TRANSPOSE: (
        "Транспонировать под вокал",
        "Подогнать тональность под диапазон вокалиста.",
        ("Новая тональность", "Обновленные партии"),
    ),
    ProcessingGoalId.BAND_ADAPT_LINEUP: (
        "Адаптировать под состав",
        "Перенести недоступные партии на реальные инструменты группы.",
        ("План адаптации", "Новые партии"),
    ),
    ProcessingGoalId.BAND_BOOST: (
        "Усилить припев",
        "Добавить энергию в припев или концертную концовку.",
        ("Усиленный припев", "Концертная концовка"),
    ),
    ProcessingGoalId.LESSON_ANALYSIS: (
        "Разобрать на уроке",
        "Показать форму, аккорды, трудные места и что слушать в оригинале.",
        ("Разбор", "Заметки преподавателя", "Домашка"),
    ),
    ProcessingGoalId.LESSON_EASY: (
        "Сделать простую версию",
        "Снизить сложность партии под уровень ученика.",
        ("Easy", "Партия ученика", "Домашка"),
    ),
    ProcessingGoalId.LESSON_ORIGINAL: (
        "Близко к оригиналу",
        "Сохранить характер песни и убрать только лишнюю сложность.",
        ("Original-like", "Разбор", "Партия ученика"),
    ),
    ProcessingGoalId.LESSON_ADVANCED: (
        "Усложнить для сильного ученика",
        "Добавить выразительность, вариации и более богатую партию.",
        ("Advanced", "Вариации", "Проверочные такты"),
    ),
    ProcessingGoalId.LESSON_CONCERT: (
        "Усилить для концерта",
        "Сделать школьную концертную версию с несколькими ролями.",
        ("Концертная версия", "Ансамбль", "Минус"),
    ),
    ProcessingGoalId.LESSON_ENSEMBLE: (
        "Разложить на ансамбль",
        "Раздать материал нескольким ученикам по уровню и инструментам.",
        ("Ансамблевые партии", "Версии учеников"),
    ),
    ProcessingGoalId.LESSON_HOMEWORK: (
        "Домашнее задание",
        "Подготовить короткие упражнения и трек для самостоятельной практики.",
        ("Задания", "Клик", "Минус"),
    ),
    ProcessingGoalId.LESSON_PRACTICE_TRACKS: (
        "Минус и подсказки",
        "Собрать фонограмму, клик и подсказки по форме.",
        ("Минус", "Клик", "Cue track"),
    ),
}


def goal_out(goal_id: enums.ProcessingGoalId | ProcessingGoalId) -> ProcessingGoalOut:
    contract_id = ProcessingGoalId(goal_id.value)
    label, description, outputs = _GOAL_TEXTS[contract_id]
    scenario = Scenario.BAND if contract_id.value.startswith("band-") else Scenario.EDUCATION
    return ProcessingGoalOut(
        id=contract_id,
        scenario=scenario,
        label=label,
        description=description,
        expected_outputs=list(outputs),
    )


# --- соответствие подписей и ключей ------------------------------------------

# Таблица из `docs/api/README.md`. Нужна потому, что демо-данные записаны
# подписями из моков («начальный», «индивидуальный урок»), а контракт говорит
# латинскими ключами. Принимаем оба написания: ключ уже верный — оставляем как
# есть, подпись — переводим. Неизвестное значение не подменяем умолчанием
# молча, а падаем на схеме: тихая подмена настройки пользователя — ошибка,
# которая уже случалась (комментарий к `BandSetup` в `types.ts`).
_STUDENT_LEVELS: dict[str, StudentLevel] = {
    "начальный": StudentLevel.STARTER,
    "средний": StudentLevel.MIDDLE,
    "сильный": StudentLevel.STRONG,
}
_NOTATION_READING: dict[str, NotationReading] = {
    "не читает": NotationReading.NONE,
    "простые ноты": NotationReading.SIMPLE,
    "уверенно": NotationReading.CONFIDENT,
}
_TEACHER_FORMATS: dict[str, TeacherFormat] = {
    "индивидуальный урок": TeacherFormat.INDIVIDUAL,
    "группа": TeacherFormat.GROUP,
    "школьный ансамбль": TeacherFormat.SCHOOL_ENSEMBLE,
}
_LESSON_DIFFICULTY: dict[str, LessonDifficulty] = {
    "проще оригинала": LessonDifficulty.EASIER,
    "близко к оригиналу": LessonDifficulty.ORIGINAL_LIKE,
    "сложнее оригинала": LessonDifficulty.HARDER,
}
_BASS_STRINGS: dict[str, BassStrings] = {
    "4 strings": BassStrings.FOUR,
    "5 strings": BassStrings.FIVE,
    "4 струны": BassStrings.FOUR,
    "5 струн": BassStrings.FIVE,
}
_MUSICIAN_LEVELS: dict[str, MusicianLevel] = {
    "начинающий": MusicianLevel.BEGINNER,
    "средний": MusicianLevel.MIDDLE,
    "продвинутый": MusicianLevel.ADVANCED,
}


def _mapped(raw: Any, table: dict[str, Any], enum_type: type, field: str) -> Any:
    """Ключ контракта из того, что лежит в базе.

    Сначала пробуем прочитать значение как ключ (оно уже верное), потом — как
    подпись из таблицы соответствия. Не подошло ни то, ни другое — отказ с
    названием поля, а не молчаливое умолчание.
    """
    if isinstance(raw, enum_type):
        return raw
    text = str(raw or "").strip()
    try:
        return enum_type(text)
    except ValueError:
        pass
    mapped = table.get(text.lower())
    if mapped is None:
        raise ProjectRefusal(
            409,
            "unmapped_value",
            "Данные песни записаны в старом виде и не читаются контрактом.",
            details={"field": field, "value": text},
        )
    return mapped


# --- оценка стоимости и пустой разбор ----------------------------------------

#: Признаки дорогой обработки. Перенесены из `estimateFromSetup`
#: (`src/services/mockServices.ts`): одна и та же оценка на экране и на сервере.
_HIGH_COMPLEXITY_SIGNALS: tuple[str, ...] = ("сложнее", "ансамб", "концерт", "плотнее", "сцен")

_COST_NOTES: tuple[str, ...] = (
    "Оценка демонстрационная.",
    "Учтены цель обработки и настройки сценария.",
)


def estimate_cost(scenario: Scenario, snapshot: SetupSnapshot | None) -> CostEstimateOut:
    """Оценка стоимости обработки по настройкам сценария."""
    text = " ".join(field.value.lower() for field in snapshot.fields) if snapshot else ""
    if any(signal in text for signal in _HIGH_COMPLEXITY_SIGNALS):
        complexity = CostComplexity.HIGH
    elif scenario is Scenario.EDUCATION:
        complexity = CostComplexity.LOW
    else:
        complexity = CostComplexity.MEDIUM

    credits = {CostComplexity.HIGH: 10, CostComplexity.MEDIUM: 7, CostComplexity.LOW: 4}[complexity]
    return CostEstimateOut(
        tier=CostTier.MULTI_VERSION if complexity is CostComplexity.HIGH else CostTier.FAST_DRAFT,
        complexity=complexity,
        credits=credits,
        notes=list(_COST_NOTES),
    )


def title_from_file_name(file_name: str) -> str:
    stem, _, _ = file_name.rpartition(".")
    return stem or file_name


def format_duration(seconds: int) -> str:
    """Длительность в виде мм:сс — так ее показывает экран."""
    minutes, rest = divmod(max(0, seconds), 60)
    return f"{minutes}:{rest:02d}"


#: Текст пустого разбора. Дословно тот же, что во фронтенде (`emptyAnalysis`):
#: пользователь читает одно и то же обещание на обоих путях.
EMPTY_ANALYSIS_SUMMARY = (
    "Звук не анализируется. Форма, аккорды и партии появятся с настоящей обработкой."
)


def empty_analysis(file_name: str, duration_seconds: int) -> SongAnalysisOut:
    """Разбор, которого нет.

    Пустые значения — не потеря данных. Подставить сюда разбор демо-песни
    значит показать пользователю тональность и аккорды чужой записи.
    """
    return SongAnalysisOut(
        source="none",
        title=title_from_file_name(file_name),
        artist="",
        bpm=0,
        key="",
        meter="",
        duration=format_duration(duration_seconds),
        genre="",
        sections=[],
        chords=[],
        confidence_by_part={},
        summary=EMPTY_ANALYSIS_SUMMARY,
    )


def analysis_out(project: models.Project, upload: models.Upload | None) -> SongAnalysisOut:
    """Разбор проекта: подготовленный заранее у демо, пустой у своего файла."""
    if project.analysis:
        return SongAnalysisOut.model_validate(project.analysis)
    return empty_analysis(
        upload.file_name if upload else project.name,
        upload.duration_seconds if upload else 0,
    )


# --- создание ----------------------------------------------------------------


def _version_kind_for(scenario: enums.Scenario) -> enums.VersionKind:
    return enums.VersionKind.BAND if scenario is enums.Scenario.BAND else enums.VersionKind.EASY


#: Подпись и запись первой версии. Те же, что на экране загрузки.
FIRST_VERSION_LABEL = "Черновик"
FIRST_VERSION_CHANGE = "Проект создан из выбранного файла."
#: Запись версии у песни, заведенной до файла. Отдельная строка, а не общая:
#: «создан из выбранного файла» там, где файла еще нет, — запись о том, чего
#: не было, и история изменений начиналась бы с неправды.
FIRST_VERSION_CHANGE_EMPTY = "Песня заведена. Файл еще не загружен."
FIRST_VERSION_AUTHOR = "Пользователь"


def _consent_text_or_refuse(payload: ProjectCreateRequest) -> str:
    """Текст согласия по версии из запроса.

    Схема это уже проверила. Повтор здесь — не перестраховка: сервис
    вызывается и из тестов, и из будущего импорта, а согласие без текста
    восстановить нечем.
    """
    consent_text = consent_text_by_id(payload.consent.version_id)
    if consent_text is None:
        raise ProjectRefusal(
            422,
            "unknown_consent_version",
            "Неизвестная версия согласия.",
            details={"versionId": payload.consent.version_id},
        )
    return consent_text


def _snapshot_of(payload: ProjectCreateRequest) -> SetupSnapshot:
    return payload.setup_snapshot or SetupSnapshot(
        scenario=payload.scenario,
        title="Состав группы" if payload.scenario is Scenario.BAND else "Учебная задача",
        fields=[],
    )


async def _with_first_version(
    repos: Repositories,
    project: models.Project,
    *,
    scenario: enums.Scenario,
    now: datetime,
    change: str,
) -> models.Project:
    """Завести первую версию аранжировки и сделать ее текущей.

    Одной транзакцией запроса вместе с самой песней: песня без версии и версия
    без песни одинаково бесполезны.
    """
    version = await repos.versions.create(
        VersionCreate(
            project_id=project.id,
            label=FIRST_VERSION_LABEL,
            kind=_version_kind_for(scenario),
            created_by=FIRST_VERSION_AUTHOR,
            status=enums.VersionStatus.DRAFT,
            created_at=now,
            changes=[change],
        )
    )
    return await repos.projects.update(project.id, ProjectPatch(current_version_id=version.id))


async def create_project(
    repos: Repositories,
    *,
    owner_id: uuid.UUID,
    payload: ProjectCreateRequest,
    now: datetime,
) -> models.Project:
    """Завести песню до файла.

    Это и есть разрыв круга (см. докстринг модуля): строка `projects`
    создается здесь, а не достается готовой. Файл приходит следующим запросом
    в уже существующую песню.

    Название обязательно и проверяется дважды — схемой и здесь. Без файла
    собирать его не из чего, а подставить «Без названия» значит придумать за
    пользователя данные, которые он потом будет искать в списке.
    """
    consent_text = _consent_text_or_refuse(payload)

    owner = await repos.users.get(owner_id)
    if owner is None:
        # Иначе запрос упал бы на внешнем ключе и превратился в `500`
        # «внутренняя ошибка». Причина при этом ровно одна и она внятная:
        # такого пользователя нет.
        raise ProjectRefusal(
            401, "unauthorized", "Вход в аккаунт не распознан: такого пользователя нет."
        )

    name = (payload.name or "").strip()
    if not name:
        raise ProjectRefusal(
            422,
            "name_required",
            "Без загрузки название песни обязательно: собрать его не из чего.",
        )

    snapshot = _snapshot_of(payload)
    scenario = enums.Scenario(payload.scenario.value)
    project = await repos.projects.create(
        ProjectCreate(
            user_id=owner_id,
            name=name,
            scenario=scenario,
            processing_goal_id=enums.ProcessingGoalId(payload.goal_id.value),
            last_opened_at=now,
            setup=payload.setup.model_dump(by_alias=True, mode="json"),
            setup_snapshot=snapshot.model_dump(by_alias=True, mode="json"),
            cost_estimate=estimate_cost(payload.scenario, snapshot).model_dump(
                by_alias=True, mode="json"
            ),
            consent_accepted=True,
            consent_version_id=payload.consent.version_id,
            consent_text=consent_text,
            consent_accepted_at=now,
        )
    )
    await repos.session.flush()
    return await _with_first_version(
        repos, project, scenario=scenario, now=now, change=FIRST_VERSION_CHANGE_EMPTY
    )


async def adopt_upload(
    repos: Repositories,
    *,
    upload: models.Upload,
    holder: models.Project,
    payload: ProjectCreateRequest,
    now: datetime,
) -> models.Project:
    """Оформить песню поверх строки, которая уже держит принятый файл.

    Второй путь создания. Он нужен там, где строка `projects` появилась не из
    `create_project`: демо-данные (`app/db/seed.py`) и будущий импорт со
    стороны. Пишет сценарий, цель, настройку, сводку, согласие и оценку
    стоимости, заводит первую версию и делает ее текущей.
    """
    consent_text = _consent_text_or_refuse(payload)
    snapshot = _snapshot_of(payload)
    scenario = enums.Scenario(payload.scenario.value)
    name = payload.name or f"{title_from_file_name(upload.file_name)}: подготовка"

    project = await repos.projects.update(
        holder.id,
        ProjectPatch(
            name=name,
            scenario=scenario,
            processing_goal_id=enums.ProcessingGoalId(payload.goal_id.value),
            setup=payload.setup.model_dump(by_alias=True, mode="json"),
            setup_snapshot=snapshot.model_dump(by_alias=True, mode="json"),
            cost_estimate=estimate_cost(payload.scenario, snapshot).model_dump(
                by_alias=True, mode="json"
            ),
            last_opened_at=now,
        ),
    )
    # Согласие лежит в колонках, а не в патче: `ProjectPatch` его не несет
    # намеренно — правка названия не должна иметь возможности задеть согласие.
    project.consent_accepted = True
    project.consent_version_id = payload.consent.version_id
    project.consent_text = consent_text
    project.consent_accepted_at = now
    await repos.session.flush()

    return await _with_first_version(
        repos, project, scenario=scenario, now=now, change=FIRST_VERSION_CHANGE
    )


# --- чтение ------------------------------------------------------------------


def entity_id(value: str) -> uuid.UUID:
    """Идентификатор из адреса.

    Чужая форма — это «не найдено», а не «неверный запрос»: в контракте
    идентификаторы непрозрачные строки, и клиент не обязан знать, что внутри
    UUID.
    """
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProjectRefusal(404, "not_found", "Песня не найдена или удалена.") from error


def owner_id(value: str) -> uuid.UUID:
    """Идентификатор владельца запроса.

    Отдельно от `entity_id`: чужая форма идентификатора пользователя — это не
    «песня не найдена», а сломанный вход в аккаунт, и говорить об этом надо
    своим текстом.
    """
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProjectRefusal(401, "unauthorized", "Вход в аккаунт не распознан.") from error


async def owned_project(repos: Repositories, project_id: uuid.UUID, user_id: str) -> models.Project:
    project = await repos.projects.get(project_id)
    if project is None:
        raise ProjectRefusal(404, "not_found", "Песня не найдена или удалена.")
    if str(project.user_id) != str(user_id):
        # Чужой проект отвечает `403`, а не `404`: наличие объекта клиент уже
        # знает из адреса, скрывать нечего, а «не найдено» на своем же проекте
        # после смены аккаунта сбивает с толку.
        raise ProjectRefusal(403, "forbidden", "Доступ к этой песне закрыт.")
    return project


async def source_upload(repos: Repositories, project: models.Project) -> models.Upload | None:
    """Исходник песни. Удаленные строки читаются: «исходник удален» — тоже состояние."""
    uploads = await repos.uploads.list_for_project(project.id, include_deleted=True)
    live = [item for item in uploads if item.deleted_at is None]
    ordered = live or list(uploads)
    return ordered[-1] if ordered else None


@dataclass(frozen=True, slots=True)
class ProjectBundle:
    """Все, что показывает карточка песни, прочитанное одной пачкой."""

    project: models.Project
    upload: models.Upload | None
    versions: Sequence[models.Version]
    artifacts: Sequence[models.Artifact]
    issues: Sequence[models.ReviewIssue]
    comments: Sequence[models.ReviewComment]
    musicians: Sequence[models.Musician]
    recipients: Sequence[models.ShareRecipient]


async def load_bundle(repos: Repositories, project: models.Project) -> ProjectBundle:
    issues = await repos.review_issues.list_for_project(project.id)
    comments: list[models.ReviewComment] = []
    for issue in issues:
        comments.extend(await repos.review_comments.list_for_issue(issue.id))
    return ProjectBundle(
        project=project,
        upload=await source_upload(repos, project),
        versions=await repos.versions.list_for_project(project.id),
        artifacts=await repos.artifacts.list_for_project(project.id),
        issues=issues,
        comments=comments,
        musicians=await repos.musicians.list_for_project(project.id),
        recipients=await repos.share_recipients.list_for_project(project.id),
    )


# --- представление -----------------------------------------------------------


def artifact_out(artifact: models.Artifact) -> ArtifactOut:
    preview = ArtifactPreviewOut.model_validate(artifact.preview) if artifact.preview else None
    return ArtifactOut(
        id=str(artifact.id),
        type=ArtifactType(artifact.artifact_type.value),
        name=artifact.name,
        format=ArtifactFormat(artifact.artifact_format.value),
        description=artifact.description or "",
        status=ArtifactStatus(artifact.status.value),
        # Уверенности может не быть в базе, а в контракте поле обязательное.
        # Ноль здесь читается как «уверенности нет», и это ближе к правде, чем
        # любое подставленное число.
        confidence=float(artifact.confidence) if artifact.confidence is not None else 0.0,
        audience=ArtifactAudience(artifact.audience.value),
        is_stale=artifact.is_stale,
        preview=preview,
        updated_at=artifact.updated_at,
    )


def stage_pack_out(version_id: uuid.UUID, artifacts: Sequence[models.Artifact]) -> StagePackOut:
    """Материалы одной версии.

    Своей таблицы у Stage Pack нет намеренно (`app/db/models.py`): это срез
    артефактов по версии. Поэтому идентификатор считается из версии, а не
    хранится — второй точки правды о составе пакета быть не должно.
    """
    return StagePackOut(
        id=f"pack-{version_id}",
        version_id=str(version_id),
        artifacts=[artifact_out(artifact) for artifact in artifacts],
    )


def stage_pack_or_none(
    version_id: uuid.UUID | None, artifacts: Sequence[models.Artifact]
) -> StagePackOut | None:
    """Пакет к репетиции или его отсутствие.

    Раньше на месте отсутствия стоял объект с придуманным идентификатором
    `pack-none` и пустой версией. Отличить его от настоящего пакета клиент не
    мог, а идентификатор вел в никуда: запрос по нему не нашел бы ничего.
    """
    if version_id is None:
        return None
    return stage_pack_out(version_id, artifacts)


def review_issue_out(
    issue: models.ReviewIssue, comments: Sequence[models.ReviewComment]
) -> ReviewIssueOut:
    return ReviewIssueOut(
        id=str(issue.id),
        title=issue.title,
        section_id=issue.section_id or "",
        # Такт обязателен в контракте и необязателен в базе. Единица — первый
        # такт песни: место без такта показывается в ее начале, а не исчезает.
        bar=issue.bar or 1,
        part=issue.part or "",
        reason=issue.reason or "",
        status=ReviewStatus(issue.status.value),
        confidence=float(issue.confidence) if issue.confidence is not None else 0.0,
        comments=[
            ReviewCommentOut(
                id=str(comment.id),
                issue_id=str(comment.issue_id),
                author=comment.author,
                text=comment.text_body,
                created_at=comment.created_at,
            )
            for comment in comments
            if comment.issue_id == issue.id
        ],
    )


def version_out(
    version: models.Version, *, current_version_id: uuid.UUID | None
) -> ArrangementVersionOut:
    snapshot = version.artifacts_snapshot
    return ArrangementVersionOut(
        id=str(version.id),
        label=version.label,
        kind=VersionKind(version.kind.value),
        parent_version_id=str(version.parent_version_id) if version.parent_version_id else None,
        created_at=version.created_at,
        created_by=version.created_by,
        status=VersionStatus(version.status.value),
        changes=list(version.changes or []),
        artifacts_snapshot=(
            [ArtifactOut.model_validate(item) for item in snapshot] if snapshot else None
        ),
        is_current=current_version_id is not None and version.id == current_version_id,
    )


def musician_out(musician: models.Musician) -> MusicianOut:
    return MusicianOut(
        id=str(musician.id),
        name=musician.name,
        role=MusicianRole(musician.role.value),
        instrument_note=musician.instrument_note or "",
        constraint=musician.constraint_note or "",
        level=MusicianLevel(musician.level.value),
    )


def _band_lineup_out(raw: dict[str, Any] | None) -> BandLineupOut | None:
    if not raw:
        return None
    data = dict(raw)
    data["bass"] = _mapped(data.get("bass"), _BASS_STRINGS, BassStrings, "bandLineup.bass")
    data["musicianLevel"] = _mapped(
        data.get("musicianLevel"), _MUSICIAN_LEVELS, MusicianLevel, "bandLineup.musicianLevel"
    )
    return BandLineupOut.model_validate(data)


def _student_profile_out(raw: dict[str, Any] | None) -> StudentProfileOut | None:
    if not raw:
        return None
    data = dict(raw)
    data["level"] = _mapped(
        data.get("level"), _STUDENT_LEVELS, StudentLevel, "studentProfile.level"
    )
    data["notationReading"] = _mapped(
        data.get("notationReading"),
        _NOTATION_READING,
        NotationReading,
        "studentProfile.notationReading",
    )
    return StudentProfileOut.model_validate(data)


def _teacher_profile_out(raw: dict[str, Any] | None) -> TeacherProfileOut | None:
    if not raw:
        return None
    data = dict(raw)
    data["format"] = _mapped(
        data.get("format"), _TEACHER_FORMATS, TeacherFormat, "teacherProfile.format"
    )
    return TeacherProfileOut.model_validate(data)


def _lesson_out(raw: dict[str, Any] | None) -> LessonOut | None:
    if not raw:
        return None
    data = dict(raw)
    data["desiredDifficulty"] = _mapped(
        data.get("desiredDifficulty"),
        _LESSON_DIFFICULTY,
        LessonDifficulty,
        "lesson.desiredDifficulty",
    )
    return LessonOut.model_validate(data)


def _assignments_out(raw: list[Any] | None) -> list[AssignmentOut]:
    if not raw:
        return []
    return [
        AssignmentOut(
            id=str(item["id"]),
            title=str(item["title"]),
            recipient=str(item["recipient"]),
            status=AssignmentStatus(str(item["status"])),
        )
        for item in raw
    ]


def upload_or_none(upload: models.Upload | None) -> UploadOut | None:
    """Исходник песни или честное «его еще нет».

    Раньше здесь стоял отказ `404 source_missing`. Он был верен, пока строка
    `uploads` заводилась раньше песни, и стал ложью, как только порядок стал
    обратным: песню, которую пользователь только что создал и видит в списке,
    нельзя открывать ответом «не найдена».

    Придуманной пустой загрузки тут по-прежнему нет: `null` говорит «файла еще
    нет», а объект с нулевой длительностью говорил бы «файл есть, он пустой».
    """
    return uploads_service.to_out(upload) if upload is not None else None


def legal_consent_out(project: models.Project) -> LegalConsentOut:
    return LegalConsentOut(
        accepted=project.consent_accepted,
        version_id=project.consent_version_id or "",
        text=project.consent_text or "",
        accepted_at=project.consent_accepted_at,
    )


def data_retention_out(project: models.Project) -> DataRetentionStateOut:
    source = DeletionState(project.source_deletion_state.value)
    results = DeletionState(project.results_deletion_state.value)
    return DataRetentionStateOut(
        # «Удалено» показывается только по подтверждению хранилища: до него
        # правильное состояние — «удаление выполняется».
        source_deleted=source is DeletionState.PURGED,
        results_deleted=results is DeletionState.PURGED,
        source_state=source,
        results_state=results,
        retention_note=project.retention_note or "",
    )


def setup_out(project: models.Project) -> ProjectSetup | None:
    if not project.setup:
        return None
    return _SETUP_ADAPTER.validate_python(project.setup)


def setup_snapshot_out(project: models.Project) -> SetupSnapshot:
    if project.setup_snapshot:
        return SetupSnapshot.model_validate(project.setup_snapshot)
    scenario = Scenario(project.scenario.value)
    return SetupSnapshot(
        scenario=scenario,
        title="Состав группы" if scenario is Scenario.BAND else "Учебная задача",
        fields=[],
    )


def cost_estimate_out(project: models.Project) -> CostEstimateOut:
    if project.cost_estimate:
        return CostEstimateOut.model_validate(project.cost_estimate)
    return estimate_cost(Scenario(project.scenario.value), setup_snapshot_out(project))


def project_out(bundle: ProjectBundle, processing: ProcessingJobOut | None) -> ProjectOut:
    """Карточка песни целиком.

    Пустые списки предложений директора, разговора, ссылок, пакетов и истории
    изменений — не заглушки: этих сущностей в базе нет вовсе, и их батчи еще
    не собраны. Наполнить их выдумкой значило бы показать пользователю
    действия, которых он не совершал.

    `processing` приходит сюда `None`, если обработку не запускали, и уходит
    наружу тем же `None`. Задание-призрак со статусом «в очереди» и пустым
    идентификатором тут не собирается: клиент отнес бы этот идентификатор на
    адрес задания и получил бы `404`.
    """
    project = bundle.project
    current = project.current_version_id
    version_of_artifact = {version.id for version in bundle.versions}
    pack_version = current or (bundle.versions[-1].id if bundle.versions else None)
    pack_artifacts = [
        artifact
        for artifact in bundle.artifacts
        if pack_version is not None and artifact.version_id == pack_version
    ]
    # Материалы без версии показываются в пакете текущей версии: иначе они
    # исчезнут из интерфейса, оставшись в базе.
    pack_artifacts.extend(
        artifact
        for artifact in bundle.artifacts
        if artifact.version_id is None or artifact.version_id not in version_of_artifact
    )

    return ProjectOut(
        id=str(project.id),
        name=project.name,
        scenario=Scenario(project.scenario.value),
        processing_goal=goal_out(project.processing_goal_id),
        upload=upload_or_none(bundle.upload),
        band_lineup=_band_lineup_out(project.band_lineup),
        musicians=[musician_out(item) for item in bundle.musicians],
        student_profile=_student_profile_out(project.student_profile),
        teacher_profile=_teacher_profile_out(project.teacher_profile),
        class_group=(
            ClassGroupOut.model_validate(project.class_group) if project.class_group else None
        ),
        lesson=_lesson_out(project.lesson),
        assignments=_assignments_out(project.assignments),
        versions=[version_out(item, current_version_id=current) for item in bundle.versions],
        current_version_id=str(current) if current else None,
        processing=processing,
        analysis=analysis_out(project, bundle.upload),
        stage_pack=stage_pack_or_none(pack_version, pack_artifacts),
        review_issues=[review_issue_out(issue, bundle.comments) for issue in bundle.issues],
        review_comments=[
            ReviewCommentOut(
                id=str(comment.id),
                issue_id=str(comment.issue_id),
                author=comment.author,
                text=comment.text_body,
                created_at=comment.created_at,
            )
            for comment in bundle.comments
        ],
        director_suggestions=[],
        chat=[],
        change_log=[],
        share_recipients=[
            ShareRecipientOut(
                id=str(item.id),
                name=item.name,
                role=ShareRecipientRole(item.role.value),
                material=item.material or "",
                status=ShareRecipientStatus(item.status.value),
            )
            for item in bundle.recipients
        ],
        share_links=[],
        export_bundles=[],
        cost_estimate=cost_estimate_out(project),
        setup=setup_out(project),
        setup_snapshot=setup_snapshot_out(project),
        legal_consent=legal_consent_out(project),
        data_retention=data_retention_out(project),
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_opened_at=project.last_opened_at,
    )


def project_summary(
    project: models.Project,
    upload: models.Upload | None,
    processing: ProcessingJobOut | None,
) -> ProjectSummary:
    return ProjectSummary(
        id=str(project.id),
        name=project.name,
        scenario=Scenario(project.scenario.value),
        goal_id=ProcessingGoalId(project.processing_goal_id.value),
        file_name=upload.file_name if upload else "",
        job_status=processing,
        source_deleted=project.source_deletion_state is enums.DeletionState.PURGED,
        results_deleted=project.results_deletion_state is enums.DeletionState.PURGED,
        created_at=project.created_at,
        last_opened_at=project.last_opened_at,
    )


# --- список ------------------------------------------------------------------


def _list_statement(
    user_id: uuid.UUID, *, scenario: Scenario | None, search: str | None
) -> Select[Any]:
    """Отбор проектов пользователя.

    Запрос собран здесь, а не в репозитории: `list_for_user` не умеет отбор по
    сценарию и поиску, а дописывать его — чужая зона батча. Правила видимости
    повторены дословно (`deleted_at IS NULL`), и это закреплено тестом: список,
    показывающий удаленную песню, делает обещание удаления ложным.
    """
    statement = select(models.Project).where(
        models.Project.user_id == user_id,
        models.Project.deleted_at.is_(None),
    )
    if scenario is not None:
        statement = statement.where(models.Project.scenario == enums.Scenario(scenario.value))
    if search:
        pattern = f"%{search.strip().lower()}%"
        statement = statement.where(func.lower(models.Project.name).like(pattern))
    return statement


async def list_projects(
    repos: Repositories,
    *,
    user_id: uuid.UUID,
    limit: int,
    offset: int,
    scenario: Scenario | None = None,
    search: str | None = None,
) -> tuple[Sequence[models.Project], int]:
    """Страница списка и полное число подходящих песен.

    Порядок — по времени последнего открытия, сверху то, что открывали
    последним. Ровно под него заведен `ix_projects_user_last_opened`.
    """
    base = _list_statement(user_id, scenario=scenario, search=search)
    total = await repos.session.scalar(select(func.count()).select_from(base.subquery()))
    page = await repos.session.execute(
        base.order_by(models.Project.last_opened_at.desc(), models.Project.id)
        .limit(limit)
        .offset(offset)
    )
    return page.scalars().all(), int(total or 0)


# --- создание: проверки перед записью ----------------------------------------


async def holder_for_upload(
    repos: Repositories, *, upload_id: str, user_id: str
) -> tuple[models.Upload, models.Project]:
    """Найти загрузку и песню, в которой она лежит, и убедиться, что песню можно создать.

    Проверки идут в порядке «есть — твое — годное»: сначала существование,
    потом права, потом состояние. Обратный порядок рассказал бы чужому, что
    объект существует.
    """
    upload = await repos.uploads.get(entity_id(upload_id), include_deleted=True)
    if upload is None:
        raise ProjectRefusal(404, "not_found", "Загрузка не найдена.")

    holder = await repos.projects.get(upload.project_id)
    if holder is None:
        raise ProjectRefusal(404, "not_found", "Загрузка не найдена.")
    if str(holder.user_id) != str(user_id):
        raise ProjectRefusal(403, "forbidden", "Доступ к этой загрузке закрыт.")

    state = uploads_service.state_of(upload)
    if state is not UploadState.STORED:
        raise ProjectRefusal(
            409,
            "upload_not_ready",
            "Файл этой загрузки еще не принят: песню создавать не из чего.",
            details={"state": state.value},
        )

    if holder.consent_accepted:
        # Согласие записывается ровно один раз — при создании песни. Значит,
        # эта загрузка уже израсходована, и вторая песня из одного файла не
        # появится. Полноценная идемпотентность по `Idempotency-Key` требует
        # своего хранилища ключей; здесь повтор ловится по данным, а не по
        # обещанию в заголовке.
        raise ProjectRefusal(
            409,
            "upload_already_used",
            "Из этой загрузки песня уже создана.",
            details={"projectId": str(holder.id)},
        )
    return upload, holder


async def rename_project(repos: Repositories, project: models.Project, name: str) -> models.Project:
    try:
        return await repos.projects.update(project.id, ProjectPatch(name=name))
    except EntityNotFound as error:
        raise ProjectRefusal(404, "not_found", "Песня не найдена или удалена.") from error


# --- демо --------------------------------------------------------------------


async def demo_projects(repos: Repositories) -> list[models.Project]:
    """Три демо-проекта из `app/db/seed.py`.

    Идентификаторы демо детерминированы, поэтому список читается по ключам, а
    не поиском по названию: название — подпись для человека, и его правка не
    должна ронять демо.
    """
    from app.db.seed import DEMO_PROJECT_KEYS, demo_uuid

    found: list[models.Project] = []
    for key in DEMO_PROJECT_KEYS:
        project = await repos.projects.get(demo_uuid("project", key))
        if project is not None:
            found.append(project)
    return found
