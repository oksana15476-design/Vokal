"""Тесты слоя проверки: места, уверенность, комментарии.

Написаны до реализации. Проверяются обещания, а не вызовы.

1. **Рядом с уверенностью всегда стоит число в процентах.** Правило бренда
   (`README.md`, `docs/design/HANDOFF.md`): цвет — не единственный сигнал.
   Считает процент сервер, а не каждый экран по-своему.
2. **Уверенность не выдумывается.** Там, где считать ее нечем, в ответе пусто и
   сказано почему. Ноль вместо отсутствия — не «нет данных», а «мы уверены, что
   все плохо»: это разные утверждения, и пользователь читает второе.
3. **Статус ставит человек.** Сервер не переводит место в «проверено» сам ни
   при каких условиях: смысл слоя в том, что автоматический результат — черновик,
   пока музыкант не сказал иначе.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.api.contract_app import build_contract_app
from app.db import enums, models
from app.db.repositories import (
    ProjectCreate,
    Repositories,
    ReviewCommentCreate,
    ReviewIssueCreate,
    UserCreate,
)

pytestmark = pytest.mark.asyncio


# --- вспомогательное ---------------------------------------------------------


def build_app(session: AsyncSession, user_id: Any) -> FastAPI:
    app = build_contract_app()
    app.dependency_overrides[deps.db_session] = lambda: session
    app.dependency_overrides[deps.current_user_id] = lambda: str(user_id)
    return app


def client_for(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://vokal.test")


def error_of(response: httpx.Response) -> dict[str, Any]:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


async def make_user(session: AsyncSession, contact: str | None = None) -> models.User:
    repos = Repositories(session)
    return await repos.users.create(
        UserCreate(contact=contact or f"band-{uuid.uuid4().hex[:8]}@example.test")
    )


async def make_project(
    session: AsyncSession, user: models.User, *, analysis: dict[str, Any] | None = None
) -> models.Project:
    repos = Repositories(session)
    project = await repos.projects.create(
        ProjectCreate(
            user_id=user.id,
            name="Late Train Home",
            scenario=enums.Scenario.BAND,
            processing_goal_id=enums.ProcessingGoalId.BAND_REHEARSAL,
            analysis=analysis,
        )
    )
    await session.flush()
    return project


async def make_issue(
    session: AsyncSession,
    project: models.Project,
    *,
    title: str = "Аккорд в бридже под вопросом",
    confidence: float | None = 0.62,
    status: enums.ReviewStatus = enums.ReviewStatus.NEEDS_REVIEW,
) -> models.ReviewIssue:
    repos = Repositories(session)
    issue = await repos.review_issues.create(
        ReviewIssueCreate(
            project_id=project.id,
            title=title,
            section_id="bridge",
            bar=37,
            part="Гитара",
            reason="Модель разошлась между Cm и Eb",
            status=status,
            confidence=confidence,
        )
    )
    await session.flush()
    return issue


async def song_with_issues(session: AsyncSession) -> dict[str, Any]:
    user = await make_user(session)
    project = await make_project(session, user, analysis={"key": "Gm", "bpm": 92})
    doubtful = await make_issue(session, project, confidence=0.62)
    settled = await make_issue(
        session,
        project,
        title="Ритм в припеве",
        confidence=0.825,
        status=enums.ReviewStatus.CHECKED,
    )
    return {"user": user, "project": project, "doubtful": doubtful, "settled": settled}


# --- уверенность -------------------------------------------------------------


async def test_confidence_always_comes_with_a_percent(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{song['project'].id}/review-issues")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items, "тест ничего не проверяет на пустом списке"
    for item in items:
        assert item["confidence"] is not None
        assert item["confidencePercent"] == round(item["confidence"] * 100 + 1e-9)


async def test_percent_rounds_the_way_the_screen_rounds(session: AsyncSession) -> None:
    """0.825 — это 83%, как на экране. Расхождение сервера и экрана заметит пользователь."""
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{song['project'].id}/review-issues")

    by_id = {item["id"]: item for item in response.json()["items"]}
    assert by_id[str(song["settled"].id)]["confidencePercent"] == 83


async def test_missing_confidence_is_explained_not_replaced_by_zero(
    session: AsyncSession,
) -> None:
    """Ноль читается как «уверенности нет вовсе». Это другое утверждение."""
    user = await make_user(session)
    project = await make_project(session, user, analysis={"key": "Gm"})
    await make_issue(session, project, confidence=None)
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/review-issues")

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["confidence"] is None
    assert item["confidencePercent"] is None
    assert item["confidenceNote"], "отсутствие числа обязано быть объяснено"


async def test_confidence_note_appears_only_without_a_number(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{song['project'].id}/review-issues")

    for item in response.json()["items"]:
        assert item["confidenceNote"] is None


# --- список ------------------------------------------------------------------


async def test_status_filter_returns_only_the_asked_status(session: AsyncSession) -> None:
    """Фильтр объявлен в контракте: объявить и не применить — хуже, чем не объявлять."""
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(
            f"/api/projects/{song['project'].id}/review-issues",
            params={"status": "checked"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["id"] for item in body["items"]] == [str(song["settled"].id)]
    assert body["total"] == 1


async def test_issues_carry_their_comments(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    repos = Repositories(session)
    await repos.review_comments.create(
        ReviewCommentCreate(
            issue_id=song["doubtful"].id,
            author="Гитарист",
            text="На записи слышно Eb",
        )
    )
    await session.flush()
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{song['project'].id}/review-issues")

    by_id = {item["id"]: item for item in response.json()["items"]}
    comments = by_id[str(song["doubtful"].id)]["comments"]
    assert [item["text"] for item in comments] == ["На записи слышно Eb"]


async def test_review_without_analysis_is_refused_with_a_reason(session: AsyncSession) -> None:
    """Пустой список читается как «все в порядке». Разбора не было — так и надо сказать."""
    user = await make_user(session)
    project = await make_project(session, user, analysis=None)
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/review-issues")

    assert response.status_code == 501
    error = error_of(response)
    assert error["code"] == "not_implemented"
    assert any("SongGraph" in item for item in error["details"]["missing"])


async def test_analysed_song_without_issues_returns_an_empty_list(
    session: AsyncSession,
) -> None:
    """Разбор был, спорных мест не нашлось — это настоящий пустой список, а не отказ."""
    user = await make_user(session)
    project = await make_project(session, user, analysis={"key": "C", "bpm": 120})
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{project.id}/review-issues")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0}


# --- статус ------------------------------------------------------------------


async def test_status_change_is_stored_and_returned(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{song['project'].id}/review-issues/{song['doubtful'].id}",
            json={"status": "accepted_for_rehearsal"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted_for_rehearsal"

    repos = Repositories(session)
    issue = await repos.review_issues.get(song["doubtful"].id)
    assert issue is not None
    assert issue.status is enums.ReviewStatus.ACCEPTED_FOR_REHEARSAL


async def test_status_change_keeps_the_explanation_as_a_comment(
    session: AsyncSession,
) -> None:
    """Договоренность «играем так» без причины через неделю выясняется заново."""
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{song['project'].id}/review-issues/{song['doubtful'].id}",
            json={
                "status": "accepted_for_rehearsal",
                "comment": "договорились играть Cm",
            },
        )

    assert response.status_code == 200, response.text
    assert [item["text"] for item in response.json()["comments"]] == ["договорились играть Cm"]


async def test_server_never_marks_an_issue_checked_by_itself(session: AsyncSession) -> None:
    """Комментарий — не проверка. Статус меняет человек отдельным действием."""
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/review-issues/{song['doubtful'].id}/comments",
            json={"text": "послушал еще раз, там Eb"},
        )

    assert response.status_code == 201, response.text
    repos = Repositories(session)
    issue = await repos.review_issues.get(song["doubtful"].id)
    assert issue is not None
    assert issue.status is enums.ReviewStatus.NEEDS_REVIEW


async def test_status_of_a_foreign_song_is_not_found(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    stranger = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.patch(
            f"/api/projects/{song['project'].id}/review-issues/{stranger['doubtful'].id}",
            json={"status": "checked"},
        )

    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


# --- комментарии -------------------------------------------------------------


async def test_comment_is_signed_by_the_request_owner(session: AsyncSession) -> None:
    user = await make_user(session, "guitar@example.test")
    project = await make_project(session, user, analysis={"key": "Gm"})
    issue = await make_issue(session, project)
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/review-issues/{issue.id}/comments",
            json={"text": "на записи слышно Eb"},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["author"] == "guitar@example.test"
    assert body["issueId"] == str(issue.id)
    assert body["text"] == "на записи слышно Eb"


async def test_foreign_signature_is_refused_not_silently_replaced(
    session: AsyncSession,
) -> None:
    """Чужая подпись под своим мнением — подделка записи в истории проверки."""
    user = await make_user(session, "guitar@example.test")
    project = await make_project(session, user, analysis={"key": "Gm"})
    issue = await make_issue(session, project)
    app = build_app(session, user.id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{project.id}/review-issues/{issue.id}/comments",
            json={"text": "это точно Cm", "author": "Преподаватель"},
        )

    assert response.status_code == 422
    assert error_of(response)["code"] == "foreign_author"

    repos = Repositories(session)
    assert await repos.review_comments.list_for_issue(issue.id) == []


async def test_blank_comment_is_refused(session: AsyncSession) -> None:
    song = await song_with_issues(session)
    app = build_app(session, song["user"].id)

    async with client_for(app) as client:
        response = await client.post(
            f"/api/projects/{song['project'].id}/review-issues/{song['doubtful'].id}/comments",
            json={"text": "   "},
        )

    assert response.status_code == 422


# --- честный отказ без швов --------------------------------------------------


async def test_review_answers_not_implemented_without_wiring() -> None:
    app = build_contract_app()
    sample = "00000000-0000-0000-0000-000000000000"

    async with client_for(app) as client:
        response = await client.get(f"/api/projects/{sample}/review-issues")

    assert response.status_code == 501
    assert error_of(response)["details"]["missing"]
