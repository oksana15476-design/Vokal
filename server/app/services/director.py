"""Действия AI-директора: детерминированный слой аранжировки.

Главное правило, из которого следует все остальное: **команда, которой нет, не
подменяется похожей**. Директор выбирает действие из закрытого списка, а
применяет его этот модуль — без догадок о намерении. Незнакомый код отвечает
отказом, который называет поддерживаемые коды, а не «улучшает песню» наугад.

Что действие делает по существу: создает новую версию аранжировки и помечает
материалы, которых правка касается. Помеченный материал не выдается за
пересобранный — у него статус «нужна проверка» или «нужна пересборка», и
пользователь видит по нему, что работа с этим материалом еще не сделана.
Пересборка — отдельный слой (задания обработки), и изображать ее здесь было бы
ровно тем самым муляжом готовности.

Тексты правил перенесены из `src/domain/mockData.ts` дословно. Не из лени: они
уже прошли продуктовую приемку и показываются пользователю сегодня. Вторая
формулировка того же — верный способ развести экран и сервер.

Отдельный адрес для пакета действий существует ради истории версий: пять
действий по одному дадут пять версий и пять пересборок, те же пять действий
пакетом — одну версию с общим перечнем изменений.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.api.schemas.enums import DirectorActionId
from app.db import enums, models
from app.db.repositories import Repositories
from app.services import versions as versions_service
from app.services.projects import ProjectRefusal
from app.services.versions import MaterialState, VersionDraft

__all__ = [
    "ACTIONS",
    "ActionOutcome",
    "DirectorRule",
    "ProjectRefusal",
    "apply_actions",
    "rule_for",
]


@dataclass(frozen=True, slots=True)
class DirectorRule:
    """Правило одного действия: что получится и что после него устареет."""

    version_label: str
    version_kind: enums.VersionKind
    history_title: str
    changes: tuple[str, ...]
    stale_artifact_types: tuple[enums.ArtifactType, ...]


_T = enums.ArtifactType
_K = enums.VersionKind


#: Закрытый список действий. Ключи совпадают с `DirectorActionId` контракта —
#: это проверяется тестом, потому что код без правила означал бы адрес, который
#: принимает команду и ничего с ней не делает.
ACTIONS: dict[DirectorActionId, DirectorRule] = {
    DirectorActionId.TRANSPOSE_DOWN_2: DirectorRule(
        version_label="Транспозиция под вокал",
        version_kind=_K.BAND,
        history_title="Песня транспонирована на два полутона вниз",
        changes=(
            "Тональность перенесена на два полутона ниже.",
            "Вокальная кульминация стала ближе к выбранному диапазону.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.TAB, _T.CHORDS, _T.LYRICS, _T.MIDI, _T.ZIP),
    ),
    DirectorActionId.MERGE_GUITARS: DirectorRule(
        version_label="Одна гитара",
        version_kind=_K.BAND,
        history_title="Гитарные партии объединены для одного гитариста",
        changes=(
            "Рифф оставлен в куплетах.",
            "В припеве сохранены акценты второй гитары.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.TAB, _T.MIDI, _T.ZIP),
    ),
    DirectorActionId.MOVE_STRINGS_TO_KEYS: DirectorRule(
        version_label="Strings на клавишах",
        version_kind=_K.BAND,
        history_title="Струнные перенесены на клавиши",
        changes=(
            "Партия strings переложена на правую руку.",
            "В припеве добавлен pad-слой.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.MIDI, _T.ZIP),
    ),
    DirectorActionId.SIMPLIFY_DRUMS: DirectorRule(
        version_label="Барабаны проще",
        version_kind=_K.EASY,
        history_title="Барабаны упрощены",
        changes=(
            "Филлы заменены на устойчивый groove.",
            "Синкопы оставлены только в переходах.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.MIDI, _T.PRACTICE, _T.ZIP),
    ),
    DirectorActionId.BEGINNER_BASS: DirectorRule(
        version_label="Бас начального уровня",
        version_kind=_K.EASY,
        history_title="Создана простая басовая партия",
        changes=(
            "Партия держит тоники и основные подходы.",
            "Сложные проходящие ноты вынесены в advanced-заметки.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.MIDI, _T.PRACTICE, _T.ZIP),
    ),
    DirectorActionId.BOOST_CHORUS: DirectorRule(
        version_label="Усиленный припев",
        version_kind=_K.CONCERT,
        history_title="AI-директор усилил припев",
        changes=(
            "Клавиши дублируют hook в припеве.",
            "Барабаны получают открытый hi-hat.",
            "В концовке добавлен концертный стоп.",
        ),
        stale_artifact_types=(_T.SCORE, _T.PART, _T.MIDI, _T.PRACTICE, _T.ZIP),
    ),
    DirectorActionId.PRACTICE_WITHOUT_BASS: DirectorRule(
        version_label="Трек без баса",
        version_kind=_K.BAND,
        history_title="Создан репетиционный трек без баса",
        changes=(
            "Бас приглушен в тренировочном миксе.",
            "Клик оставлен только в интро и бридже.",
        ),
        stale_artifact_types=(_T.PRACTICE, _T.ZIP),
    ),
    DirectorActionId.EDUCATION_VERSION: DirectorRule(
        version_label="Учебная версия",
        version_kind=_K.EASY,
        history_title="Создана учебная версия",
        changes=(
            "Оставлены куплет и припев.",
            "Ритм упрощен до восьмых.",
            "Добавлены заметки преподавателя.",
        ),
        stale_artifact_types=(
            _T.SCORE,
            _T.PART,
            _T.STUDENT,
            _T.TEACHER,
            _T.PRACTICE,
            _T.ZIP,
        ),
    ),
    DirectorActionId.ADVANCED_STUDENT_PART: DirectorRule(
        version_label="Advanced для сильного ученика",
        version_kind=_K.ADVANCED,
        history_title="Создана усложненная партия для сильного ученика",
        changes=(
            "Добавлены проходящие ноты.",
            "Во втором припеве появилась ритмическая вариация.",
            "Сложные такты отмечены для проверки.",
        ),
        stale_artifact_types=(
            _T.SCORE,
            _T.PART,
            _T.STUDENT,
            _T.TEACHER,
            _T.MIDI,
            _T.ZIP,
        ),
    ),
    DirectorActionId.STUDENT_ENSEMBLE: DirectorRule(
        version_label="Ансамбль учеников",
        version_kind=_K.ENSEMBLE,
        history_title="Песня разложена на ансамбль учеников",
        changes=(
            "Мелодия разделена между гитарой и клавишами.",
            "Перкуссия получила простую пульсацию.",
            "Каждому ученику назначена отдельная партия.",
        ),
        stale_artifact_types=(
            _T.SCORE,
            _T.PART,
            _T.STUDENT,
            _T.TEACHER,
            _T.PRACTICE,
            _T.ZIP,
        ),
    ),
    DirectorActionId.LESSON_ANALYSIS: DirectorRule(
        version_label="Разбор для урока",
        version_kind=_K.ORIGINAL_LIKE,
        history_title="Подготовлен разбор песни для урока",
        changes=(
            "Добавлена форма песни.",
            "Отмечены трудные аккорды.",
            "Сформировано домашнее задание на припев.",
        ),
        stale_artifact_types=(_T.TEACHER, _T.STUDENT, _T.CHORDS, _T.LYRICS, _T.ZIP),
    ),
}

#: Материалы, которые после правки нужно не проверить, а пересобрать целиком:
#: свести трек заново или собрать архив. Проверить их глазами нельзя.
_REBUILT_TYPES: frozenset[enums.ArtifactType] = frozenset({_T.PRACTICE, _T.ZIP})


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    """Что сделало действие: новая версия и перечень последствий."""

    version: models.Version
    applied: list[DirectorActionId]
    version_label: str
    version_kind: enums.VersionKind
    history_title: str
    changes: list[str]
    stale_artifact_types: list[enums.ArtifactType]


def supported_action_ids() -> list[str]:
    return [item.value for item in DirectorActionId]


def rule_for(action_id: DirectorActionId) -> DirectorRule:
    """Правило действия или честный отказ с перечнем поддерживаемых.

    Схема запроса уже не пропускает незнакомый код, и повтор здесь — не
    перестраховка: сервис вызывается и из тестов, и из будущего разбора реплики
    директору, где код приходит от модели, а не от клиента. Ответ «не знаю
    такой команды» с полным списком лучше, чем выполнение похожей.
    """
    rule = ACTIONS.get(action_id)
    if rule is None:
        raise ProjectRefusal(
            422,
            "unknown_director_action",
            "Такого действия нет. Директор выполняет только команды из списка.",
            details={"actionId": str(action_id), "supported": supported_action_ids()},
        )
    return rule


async def apply_actions(
    repos: Repositories,
    project: models.Project,
    *,
    action_ids: Sequence[DirectorActionId],
    base_version_id: str,
    label: str | None,
    comment: str | None,
    now: datetime,
) -> ActionOutcome:
    """Применить действия и собрать из них одну версию.

    `base_version_id` обязателен и сверяется с текущей версией песни. Без сверки
    правка легла бы на версию, которую пользователь уже не видит на экране: два
    открытых окна, действие в старом — и материалы уезжают не от того состояния,
    от которого человек их отсчитывал.
    """
    if not action_ids:
        raise ProjectRefusal(
            422,
            "empty_action_batch",
            "Нечего применять: список действий пуст.",
            details={"supported": supported_action_ids()},
        )

    rules = [rule_for(action_id) for action_id in action_ids]
    base = await _base_version(repos, project, base_version_id)

    if len(rules) == 1:
        rule = rules[0]
        version_label = label or rule.version_label
        version_kind = rule.version_kind
        history_title = rule.history_title
        changes = list(rule.changes)
    else:
        version_label = label or rules[0].version_label
        version_kind = rules[0].version_kind
        history_title = f"Собрана версия из {len(rules)} предложений"
        changes = [line for rule in rules for line in rule.changes]

    stale_types = _stale_types(rules)
    materials = await versions_service.materials_of(repos, base)
    _refuse_if_nothing_to_arrange(project, materials)
    marks = _marks_for(materials, stale_types)

    version_changes = list(changes)
    if comment:
        # Реплика человека остается рядом с правкой: без нее по истории видно
        # что сделано, но не видно зачем.
        version_changes.append(comment)

    version = await versions_service.build_version(
        repos,
        project,
        base=base,
        draft=VersionDraft(
            label=version_label,
            kind=version_kind,
            changes=version_changes,
            created_by=versions_service.DIRECTOR_AUTHOR,
            # Версия после правки директора не «готова»: материалы к ней еще не
            # пересобраны, и статус говорит именно это.
            status=enums.VersionStatus.NEEDS_REVIEW,
        ),
        materials=materials,
        marks=marks,
        now=now,
    )

    return ActionOutcome(
        version=version,
        applied=list(action_ids),
        version_label=version_label,
        version_kind=version_kind,
        history_title=history_title,
        changes=changes,
        stale_artifact_types=stale_types,
    )


def _refuse_if_nothing_to_arrange(
    project: models.Project, materials: Sequence[models.Artifact]
) -> None:
    """Действие должно к чему-то применяться.

    У песни без разбора и без материалов запись «гитарные партии объединены»
    была бы утверждением о песне, за которым не стоит ничего: ни формы, ни
    партий, ни файла. История версий после такой записи врет ровно так же, как
    врал бы придуманный материал в ответе.
    """
    if materials or project.analysis:
        return
    raise ProjectRefusal(
        409,
        "nothing_to_arrange",
        "Аранжировать нечего: песню еще не разбирали, материалов у нее нет.",
        details={"missing": ["разбор песни (SongGraph)", "материалы текущей версии"]},
    )


async def _base_version(
    repos: Repositories, project: models.Project, base_version_id: str
) -> models.Version:
    """Версия, к которой применяется действие. Она обязана быть текущей."""
    current = await versions_service.current_version(repos, project)
    if current is None:
        raise ProjectRefusal(
            409,
            "version_conflict",
            "У песни еще нет версии аранжировки: применять действие не к чему.",
            details={"currentVersionId": None},
        )
    if str(current.id) != base_version_id:
        raise ProjectRefusal(
            409,
            "version_conflict",
            "Песня изменилась с момента загрузки экрана: обновите данные и повторите.",
            details={"currentVersionId": str(current.id), "baseVersionId": base_version_id},
        )
    return current


def _stale_types(rules: Sequence[DirectorRule]) -> list[enums.ArtifactType]:
    """Объединение по правилам, порядок первого появления сохраняется."""
    seen: list[enums.ArtifactType] = []
    for rule in rules:
        for artifact_type in rule.stale_artifact_types:
            if artifact_type not in seen:
                seen.append(artifact_type)
    return seen


def _marks_for(
    materials: Sequence[models.Artifact], stale_types: Sequence[enums.ArtifactType]
) -> dict[uuid.UUID, MaterialState]:
    """Пометки материалов: только те, которых правка касается.

    Материал, не затронутый действием, не помечается устаревшим. Пометить все
    подряд проще, но тогда пометка перестает что-либо значить: пользователь
    видит «пересобрать» на аудиослоях после правки нотной партии и перестает
    ей верить.
    """
    affected = set(stale_types)
    marks: dict[uuid.UUID, MaterialState] = {}
    for artifact in materials:
        if artifact.artifact_type not in affected:
            continue
        status = (
            enums.ArtifactStatus.REBUILD_REQUIRED
            if artifact.artifact_type in _REBUILT_TYPES
            else enums.ArtifactStatus.NEEDS_REVIEW
        )
        marks[artifact.id] = MaterialState(status=status, is_stale=True)
    return marks
