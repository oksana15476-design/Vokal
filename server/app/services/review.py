"""Confidence and Review Engine: места проверки, уверенность, комментарии.

Слой проверки существует ради одного утверждения: **автоматический результат —
черновик, пока музыкант не сказал иначе**. Отсюда все правила модуля.

**Статус ставит человек.** Сервер не переводит место в «проверено» сам ни при
каких условиях: ни по комментарию, ни по времени, ни по тому, что материал
пересобрали. Иначе «проверено» перестает означать «человек посмотрел».

**Уверенность не выдумывается.** Там, где числа нет, в ответе пусто и сказано
почему. Ноль вместо отсутствия читается как «уверены, что все плохо» — другое
утверждение, и по нему принимают другие решения.

**Пустой список — тоже утверждение.** «Мест для проверки нет» у неразобранной
песни означает «все в порядке», хотя правда в том, что никто не смотрел.
Поэтому у песни без разбора список отвечает отказом с причиной, а не пустотой.
Разобранная песня без спорных мест, наоборот, отдает настоящий пустой список.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from app.api.schemas.enums import ReviewStatus
from app.api.schemas.review import ReviewCommentOut, ReviewIssueOut
from app.db import enums, models
from app.db.repositories import Repositories, ReviewCommentCreate, ReviewIssuePatch
from app.services.projects import ProjectRefusal

#: Почему у места нет числа уверенности. Причина одна и системная: считать ее
#: нечем — модели разбора в продукте еще нет. Когда она появится, здесь будет
#: разбор по случаям, а не «нет данных» на все.
CONFIDENCE_UNAVAILABLE = (
    "Уверенность не рассчитана: модели разбора, которая ее считает, в продукте еще нет."
)

#: Чего не хватает, чтобы места проверки появились у неразобранной песни.
REVIEW_MISSING = (
    "разбор песни (SongGraph): места проверки строятся по нему",
    "Confidence and Review Engine: расчет уверенности по разбору",
)


@dataclass(frozen=True, slots=True)
class IssueBundle:
    """Место проверки вместе со своими комментариями."""

    issue: models.ReviewIssue
    comments: list[models.ReviewComment]


def issue_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ProjectRefusal(404, "not_found", "Место проверки не найдено.") from error


async def issue_of_project(
    repos: Repositories, project: models.Project, issue_id: str
) -> models.ReviewIssue:
    """Место проверки своей песни. Чужое отвечает «не найдено».

    Не `403`: адрес вложен в песню, права на нее уже проверены, и подтверждать
    существование чужой строки по чужому идентификатору незачем.
    """
    issue = await repos.review_issues.get(issue_uuid(issue_id))
    if issue is None or issue.project_id != project.id:
        raise ProjectRefusal(404, "not_found", "Место проверки не найдено.")
    return issue


async def list_issues(
    repos: Repositories, project: models.Project, *, status: ReviewStatus | None
) -> list[IssueBundle]:
    """Места проверки песни, при желании — только с нужным статусом.

    Отбор по статусу объявлен в контракте, и объявить его, не применив, хуже,
    чем не объявлять: клиент показывает «только спорные», а получает все.
    """
    issues = list(await repos.review_issues.list_for_project(project.id))
    if not issues and not project.analysis:
        raise ProjectRefusal(
            501,
            "not_implemented",
            "Мест для проверки нет: песню еще не разбирали.",
            details={"missing": list(REVIEW_MISSING)},
        )

    if status is not None:
        issues = [item for item in issues if item.status.value == status.value]

    return [
        IssueBundle(
            issue=issue,
            comments=list(await repos.review_comments.list_for_issue(issue.id)),
        )
        for issue in issues
    ]


async def set_status(
    repos: Repositories,
    project: models.Project,
    issue: models.ReviewIssue,
    *,
    status: ReviewStatus,
    comment: str | None,
    author: str,
) -> IssueBundle:
    """Сменить статус места. Это единственный способ его изменить.

    Пояснение сохраняется отдельным комментарием: договоренность «играем так»
    без причины через неделю выясняется заново, уже на репетиции.
    """
    updated = await repos.review_issues.update(
        issue.id, ReviewIssuePatch(status=enums.ReviewStatus(status.value))
    )
    if comment and comment.strip():
        await repos.review_comments.create(
            ReviewCommentCreate(issue_id=issue.id, author=author, text=comment.strip())
        )
    await repos.session.flush()
    return IssueBundle(
        issue=updated,
        comments=list(await repos.review_comments.list_for_issue(issue.id)),
    )


async def add_comment(
    repos: Repositories,
    issue: models.ReviewIssue,
    *,
    text: str,
    requested_author: str | None,
    signature: str,
) -> models.ReviewComment:
    """Свой комментарий к месту. Статус места при этом не меняется.

    Комментарий — не проверка: человек может записать сомнение и оставить место
    спорным. Автоматическая смена статуса здесь означала бы, что запись мнения
    засчитывается за проверку.

    Подпись всегда своя. Чужая — подделка записи в истории проверки, и молча
    заменить ее на свою тоже нельзя: пользователь останется уверен, что
    подписал коллегу.
    """
    if requested_author is not None and requested_author.strip() != signature:
        raise ProjectRefusal(
            422,
            "foreign_author",
            "Комментарий подписывается своим именем: чужую подпись поставить нельзя.",
            details={"author": signature},
        )

    comment = await repos.review_comments.create(
        ReviewCommentCreate(issue_id=issue.id, author=signature, text=text)
    )
    await repos.session.flush()
    return comment


async def signature_of(repos: Repositories, project: models.Project, user_id: str) -> str:
    """Подпись владельца запроса под комментарием.

    Пока в продукте нет ни профиля, ни отображаемого имени, подписью служит
    контакт входа. Придумывать «Пользователь» вместо него нельзя: в истории
    проверки должно быть видно, кто именно это написал.
    """
    owner = await repos.users.get(project.user_id)
    return owner.contact if owner is not None else user_id


def comment_out(comment: models.ReviewComment) -> ReviewCommentOut:
    return ReviewCommentOut(
        id=str(comment.id),
        issue_id=str(comment.issue_id),
        author=comment.author,
        text=comment.text_body,
        created_at=comment.created_at,
    )


def issue_out(
    issue: models.ReviewIssue, comments: Sequence[models.ReviewComment]
) -> ReviewIssueOut:
    """Место проверки в виде контракта — вместе с честной уверенностью."""
    confidence = float(issue.confidence) if issue.confidence is not None else None
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
        confidence=confidence,
        confidence_note=None if confidence is not None else CONFIDENCE_UNAVAILABLE,
        comments=[comment_out(item) for item in comments],
    )


def bundle_out(bundle: IssueBundle) -> ReviewIssueOut:
    return issue_out(bundle.issue, bundle.comments)
