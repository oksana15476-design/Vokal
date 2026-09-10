"""Схемы проекта: создание из загрузки и полная карточка.

Настройка пользователя приходит **типизированной** (`BandSetup`/`LessonSetup`),
а не словарем подписей. Это прямое следствие уже случившейся ошибки: сервис
искал значения по русским подписям («Диапазон вокала»), и переименование
подписи копирайтером молча заменяло настройку пользователя умолчанием. Ошибка
была тихой — ни исключения, ни пустого поля, просто чужое значение.

Поэтому здесь два разных поля:

- `setup` — значения, из которых считается аранжировка;
- `setup_snapshot` — то, что пользователь видит в сводке. Из него ничего не
  вычисляется, и подписи в нем можно менять свободно.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.api.schemas.artifacts import StagePackOut
from app.api.schemas.common import ApiModel
from app.api.schemas.consent import ConsentAcceptance, LegalConsentOut
from app.api.schemas.deletion import DataRetentionStateOut
from app.api.schemas.director import ChatMessageOut, DirectorSuggestionOut
from app.api.schemas.enums import (
    GOAL_PREFIX_BY_SCENARIO,
    CostComplexity,
    CostTier,
    ProcessingGoalId,
    Scenario,
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
from app.api.schemas.review import ReviewCommentOut, ReviewIssueOut
from app.api.schemas.sharing import ExportBundleOut, ShareLinkOut, ShareRecipientOut
from app.api.schemas.song import ProcessingGoalOut, SongAnalysisOut
from app.api.schemas.uploads import UploadOut
from app.api.schemas.versions import ArrangementVersionOut


class BandSetup(ApiModel):
    """Настройка сценария группы. Свободные строки: это слова пользователя."""

    kind: Literal["band"]
    vocal_range: str = Field(max_length=200)
    guitars: int = Field(ge=0, le=8)
    bass: str = Field(max_length=200)
    keys: str = Field(max_length=200)
    drums: str = Field(max_length=200)
    target_style: str = Field(max_length=200)


class LessonSetup(ApiModel):
    """Настройка сценария урока."""

    kind: Literal["lesson"]
    instrument: str = Field(max_length=200)
    level: str = Field(max_length=200)
    lesson_goal: str = Field(max_length=500)
    difficulty: str = Field(max_length=200)


#: Разбор по полю `kind`, а не по набору полей: перепутанный сценарий должен
#: быть ошибкой с внятным текстом, а не молча подошедшей второй схемой.
ProjectSetup = Annotated[BandSetup | LessonSetup, Field(discriminator="kind")]

#: Какая настройка допустима в каком сценарии.
SETUP_KIND_BY_SCENARIO: dict[Scenario, str] = {
    Scenario.BAND: "band",
    Scenario.EDUCATION: "lesson",
}


class SetupSnapshotField(ApiModel):
    label: str = Field(max_length=200)
    value: str = Field(max_length=500)


class SetupSnapshot(ApiModel):
    """Сводка настроек для показа. Из нее ничего не вычисляется."""

    scenario: Scenario
    title: str = Field(max_length=200)
    fields: list[SetupSnapshotField] = Field(max_length=40)


class CostEstimateOut(ApiModel):
    """Оценка стоимости обработки.

    Ожидаемого времени здесь намеренно нет: обработки не существует, а любое
    число рядом со словом «минут» читается как обещание срока. Вернуть вместе
    с настоящим ModelRouter.
    """

    tier: CostTier
    complexity: CostComplexity
    credits: int = Field(ge=0)
    notes: list[str]


class ChangeLogEntryOut(ApiModel):
    """Запись истории изменений проекта."""

    id: str
    title: str
    description: str
    created_at: datetime
    actor: str


class ProjectCreateRequest(ApiModel):
    """Создание песни.

    `uploadId` необязателен, и это разрыв круга, из-за которого продукт раньше
    не запускался вовсе: строка загрузки требует песни (`uploads.project_id`
    NOT NULL), а создание песни требовало принятой загрузки. Первым нельзя было
    создать ни то, ни другое. Теперь песня заводится первой и пустой, а файл
    приходит в нее вторым запросом (`POST /api/uploads` с `projectId`).

    Почему разрыв именно с этой стороны, а не через nullable
    `uploads.project_id`: строка загрузки без песни — это объект в хранилище,
    за который никто не отвечает. Его некому показать, некому удалить по
    запросу и не с чем связать согласие. Пустая песня, наоборот, — состояние,
    которое пользователь и так видит на экране: он завел песню и еще не выбрал
    файл.
    """

    upload_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Принятая загрузка, вокруг которой оформляется песня. Пусто — песня "
            "создается без файла, и файл приходит в нее отдельным запросом."
        ),
    )
    name: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Название песни. Пусто — соберется из имени файла, поэтому без "
            "`uploadId` название обязательно."
        ),
    )
    scenario: Scenario
    goal_id: ProcessingGoalId
    setup: ProjectSetup = Field(description="Типизированная настройка сценария")
    setup_snapshot: SetupSnapshot | None = Field(
        default=None, description="Сводка для показа. Необязательна."
    )
    consent: ConsentAcceptance = Field(
        description="Согласие вместе с версией формулировки. Без версии проект не создается."
    )

    @model_validator(mode="after")
    def _consistent_scenario(self) -> ProjectCreateRequest:
        # Сценарий, цель и настройка обязаны сойтись. Расхождение здесь — не
        # опечатка пользователя, а разошедшееся состояние экрана, и молча
        # выбрать «правильное» значение нельзя: любое из трех может быть верным.
        expected_kind = SETUP_KIND_BY_SCENARIO[self.scenario]
        if self.setup.kind != expected_kind:
            raise ValueError(
                f"Настройка «{self.setup.kind}» не подходит сценарию «{self.scenario.value}»: "
                f"ожидается «{expected_kind}»."
            )
        prefix = GOAL_PREFIX_BY_SCENARIO[self.scenario]
        if not self.goal_id.value.startswith(prefix):
            raise ValueError(
                f"Цель «{self.goal_id.value}» не относится к сценарию «{self.scenario.value}»."
            )
        return self

    @model_validator(mode="after")
    def _name_when_no_file(self) -> ProjectCreateRequest:
        # Название собирается из имени файла. Без файла собирать его не из
        # чего, а назвать песню «Без названия» за пользователя — это придумать
        # за него данные, которые он потом будет искать в списке.
        if self.upload_id is None and not (self.name or "").strip():
            raise ValueError("Без загрузки название песни обязательно: собрать его не из чего.")
        return self


class ProjectPatchRequest(ApiModel):
    """Правка карточки проекта. Пока только название."""

    name: str = Field(min_length=1, max_length=200)


class ProjectOut(ApiModel):
    """Проект целиком. Повторяет `Project` из `src/domain/types.ts`."""

    id: str
    name: str
    scenario: Scenario
    processing_goal: ProcessingGoalOut
    upload: UploadOut | None = Field(
        description=(
            "Исходник песни. `null` — файла еще нет: песня заведена, файл не загружен. "
            "Это состояние продукта, а не потеря данных."
        ),
    )
    band_lineup: BandLineupOut | None = None
    musicians: list[MusicianOut] = Field(
        description="Кто играет. Пусто в сценарии урока и у проектов без состава."
    )
    student_profile: StudentProfileOut | None = None
    teacher_profile: TeacherProfileOut | None = None
    class_group: ClassGroupOut | None = None
    lesson: LessonOut | None = None
    assignments: list[AssignmentOut]
    versions: list[ArrangementVersionOut]
    current_version_id: str | None = None
    processing: ProcessingJobOut | None = Field(
        description=(
            "Состояние обработки. `null` — обработку не запускали. Пустое задание с пустым "
            "идентификатором сюда не подставляется: по такому идентификатору клиент пошел бы "
            "спрашивать статус и получил бы 404."
        ),
    )
    analysis: SongAnalysisOut
    stage_pack: StagePackOut | None = Field(
        description="Пакет к репетиции. `null` — версии аранжировки еще нет, собирать нечего.",
    )
    review_issues: list[ReviewIssueOut]
    review_comments: list[ReviewCommentOut]
    director_suggestions: list[DirectorSuggestionOut]
    chat: list[ChatMessageOut]
    change_log: list[ChangeLogEntryOut]
    share_recipients: list[ShareRecipientOut]
    share_links: list[ShareLinkOut]
    export_bundles: list[ExportBundleOut]
    cost_estimate: CostEstimateOut
    setup: ProjectSetup | None = None
    setup_snapshot: SetupSnapshot
    legal_consent: LegalConsentOut
    data_retention: DataRetentionStateOut
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime


class ProjectSummary(ApiModel):
    """Строка списка проектов.

    Короткая намеренно: список открывается часто, а тянуть в него разбор и
    материалы каждого проекта — платить за то, что на экране не показано.
    """

    id: str
    name: str
    scenario: Scenario
    goal_id: ProcessingGoalId
    file_name: str
    job_status: ProcessingJobOut | None = Field(
        default=None, description="Состояние обработки. Пусто, если обработка не запускалась."
    )
    source_deleted: bool
    results_deleted: bool
    created_at: datetime
    last_opened_at: datetime


class ProjectListResponse(ApiModel):
    items: list[ProjectSummary]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
