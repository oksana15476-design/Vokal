"""Выдача материалов: получатели, ссылки, архивы.

Срез разделен ровно по одному признаку — есть ли под адресом слой данных.

**Получатели есть.** Таблица `share_recipients` заведена (`app/db/models.py`),
и работа с ней здесь настоящая: список, добавление, правка, проверка владельца.
Смысл этой половины не в «списке контактов»: разным ролям выдается разное, и
кому что причитается, решается до выдачи, а не в момент отправки файла.

**Ссылок и архивов нет, и это не заглушка «на потом».** Ссылка, которую держит
музыкант или ученик, обязана иметь срок жизни и отзыв —
`docs/DELETION_AND_RETENTION_DESIGN.md` требует этого прямо, иначе кнопка
«удалить результаты» не закрывает уже выданный доступ и обещание становится
ложным. И срок, и отзыв — это состояние: когда выдали, до когда действует,
когда отозвали, что именно открывает. Держать такое состояние негде: таблицы
`share_links` в схеме базы нет вовсе, как нет и `export_bundles`.

Отсюда форма отказа. Он называет недостающую таблицу, а не «объектное
хранилище»: хранилище как раз есть (`app/storage/`), и списать отсутствие
выдачи на него значит отправить работу не туда. Перечень `missing` читают,
чтобы понять, чей это батч, — неверно названное недостающее дороже пустого.

Выдавать ссылку без отзыва «пока временно» здесь нельзя тем более: временная
выдача становится постоянной ровно в тот момент, когда по ней уже раздали
материалы, а отозвать их будет нечем.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.api.schemas.enums import ShareRecipientRole, ShareRecipientStatus
from app.api.schemas.sharing import (
    ShareRecipientCreate,
    ShareRecipientListResponse,
    ShareRecipientOut,
    ShareRecipientUpdate,
)
from app.db import enums, models
from app.db.repositories import (
    UNSET,
    Repositories,
    ShareRecipientPatch,
)
from app.db.repositories import (
    ShareRecipientCreate as RecipientRow,
)
from app.services.projects import ProjectRefusal

#: Чего не хватает для выдачи ссылок. Первым пунктом — то, чего действительно
#: нет: место, где живут срок жизни и отметка отзыва.
LINKS_MISSING = (
    "таблица выданных ссылок share_links: токен, срок жизни, отметка отзыва "
    "(app/db/models.py + миграция)",
    "адрес открытия материалов по токену без входа в аккаунт",
)

#: Архив собирается из файлов материалов, а их пока не создается.
BUNDLES_MISSING = (
    "таблица архивов export_bundles: состав, статус сборки, версия (app/db/models.py + миграция)",
    "таблица выданных ссылок share_links: архив отдается ссылкой, а ссылку надо отзывать",
    "сборка материалов: файлов результатов пока не создается",
)


def recipient_out(recipient: models.ShareRecipient) -> ShareRecipientOut:
    """Получатель в ответ контракта.

    `material` в базе может быть пустым, а в контракте поле обязательное.
    Пустая строка читается как «не указано» и честнее придуманного описания
    того, что человеку якобы выдается.
    """
    return ShareRecipientOut(
        id=str(recipient.id),
        name=recipient.name,
        role=ShareRecipientRole(recipient.role.value),
        material=recipient.material or "",
        status=ShareRecipientStatus(recipient.status.value),
    )


def recipients_out(
    recipients: Sequence[models.ShareRecipient], *, limit: int, offset: int
) -> ShareRecipientListResponse:
    """Страница списка.

    `total` — сколько всего у песни, а не сколько влезло на страницу: иначе
    экран не сможет показать, есть ли что-то дальше.
    """
    page = recipients[offset : offset + limit]
    return ShareRecipientListResponse(
        items=[recipient_out(item) for item in page], total=len(recipients)
    )


async def list_recipients(
    repos: Repositories, project: models.Project, *, limit: int, offset: int
) -> ShareRecipientListResponse:
    recipients = await repos.share_recipients.list_for_project(project.id)
    return recipients_out(recipients, limit=limit, offset=offset)


async def create_recipient(
    repos: Repositories, project: models.Project, payload: ShareRecipientCreate
) -> models.ShareRecipient:
    """Добавляет получателя в конец списка.

    Порядок задается явно: список получателей — это порядок, в котором
    руководитель раздает материалы, и переставлять его выдачей нового
    идентификатора нельзя.
    """
    existing = await repos.share_recipients.list_for_project(project.id)
    return await repos.share_recipients.create(
        RecipientRow(
            project_id=project.id,
            name=payload.name,
            role=enums.ShareRecipientRole(payload.role.value),
            material=payload.material,
            # Ничего не выдано и выдать нечем: статус говорит это прямо.
            status=enums.ShareRecipientStatus.NOT_ISSUED,
            position=len(existing),
        )
    )


async def owned_recipient(
    repos: Repositories, project: models.Project, recipient_id: uuid.UUID
) -> models.ShareRecipient:
    """Получатель этой песни.

    Получатель чужой песни отвечает «не найден», а не «закрыт»: адрес вложен
    в песню, и подтверждать существование чужой строки по чужому
    идентификатору незачем.
    """
    recipient = await repos.share_recipients.get(recipient_id)
    if recipient is None or recipient.project_id != project.id:
        raise ProjectRefusal(404, "not_found", "Получатель не найден.")
    return recipient


async def update_recipient(
    repos: Repositories,
    project: models.Project,
    recipient_id: uuid.UUID,
    payload: ShareRecipientUpdate,
) -> models.ShareRecipient:
    """Меняет только названное в запросе.

    Не названное поле остается прежним, а не затирается умолчанием схемы:
    правка описания материала не должна переименовывать человека.
    """
    recipient = await owned_recipient(repos, project, recipient_id)
    return await repos.share_recipients.update(
        recipient.id,
        ShareRecipientPatch(
            name=payload.name if payload.name is not None else UNSET,
            role=(
                enums.ShareRecipientRole(payload.role.value) if payload.role is not None else UNSET
            ),
            material=payload.material if payload.material is not None else UNSET,
        ),
    )
