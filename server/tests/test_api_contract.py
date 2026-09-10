"""Тесты контракта API между фронтендом и сервером.

Проверяется именно контракт, а не реализация: форма запроса, форма ответа,
коды ошибок и обязательные поля. Реализации за большинством адресов еще нет,
и это часть контракта — такой адрес обязан отвечать `501` в общем формате
ошибки, а не правдоподобной выдумкой.

База данных этим тестам не нужна: контракт проверяется на приложении, куда
подключен только роутер API, а зависимость сессии остается заглушкой. Тесты,
которым нужен PostgreSQL, живут в соседних файлах.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.consent_versions import (
    consent_text_by_id,
    consent_versions,
    current_consent,
    fingerprint_of,
)
from app.api.contract_app import build_contract_app
from app.api.schemas.uploads import MAX_UPLOAD_BYTES, SUPPORTED_UPLOAD_EXTENSIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
OPENAPI_FILE = REPO_ROOT / "docs" / "api" / "openapi.json"

# Адреса, за которыми стоит настоящий ответ, а не заглушка. Список закрытый:
# любой новый адрес по умолчанию обязан быть заглушкой, пока его не внесли сюда
# осознанно вместе с реализацией.
REAL_ENDPOINTS = {
    ("GET", "/api/uploads/constraints"),
    ("GET", "/api/consent/current"),
    ("GET", "/api/consent/versions"),
}

SAMPLE_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(build_contract_app())


@pytest.fixture(scope="module")
def openapi(client: TestClient) -> dict[str, Any]:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def error_of(response: Any) -> dict[str, Any]:
    """Достает конверт ошибки и заодно проверяет, что он именно такой."""
    body = response.json()
    assert set(body) == {"error"}, f"в теле ошибки лишние ключи: {sorted(body)}"
    error = body["error"]
    assert set(error) >= {"code", "message", "requestId", "details"}
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["message"], str) and error["message"]
    return error


def field_errors(response: Any) -> list[str]:
    error = error_of(response)
    assert error["code"] == "validation_error"
    return [item["field"] for item in error["details"]["fields"]]


def component(openapi: dict[str, Any], name: str) -> dict[str, Any]:
    schemas = openapi["components"]["schemas"]
    assert name in schemas, f"в схеме нет компонента {name}"
    return schemas[name]


def required_properties(openapi: dict[str, Any], name: str) -> set[str]:
    return set(component(openapi, name).get("required", ()))


def properties(openapi: dict[str, Any], name: str) -> set[str]:
    return set(component(openapi, name).get("properties", {}))


# --- Общее устройство ----------------------------------------------------


def test_router_exposed_under_expected_name() -> None:
    """`main.py` подключает роутер по этому имени. Переименование сломает сборку."""
    from app.api.router import api_router

    assert api_router.routes


def test_all_paths_live_under_api_prefix(openapi: dict[str, Any]) -> None:
    assert openapi["paths"]
    for path in openapi["paths"]:
        assert path.startswith("/api/"), path


def test_unknown_api_path_answers_not_found_envelope(client: TestClient) -> None:
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert error_of(response)["code"] == "not_found"


def test_wrong_method_answers_method_not_allowed_envelope(client: TestClient) -> None:
    response = client.delete("/api/uploads/constraints")
    assert response.status_code == 405
    assert error_of(response)["code"] == "method_not_allowed"


# --- Задача 10: заглушка обязана выглядеть заглушкой ---------------------


def routes_of(openapi: dict[str, Any]) -> list[tuple[str, str]]:
    """Адреса берутся из схемы, а не из таблицы маршрутов.

    Так проверяется именно опубликованный контракт: то, что описано в схеме,
    обязано вести себя честно. Адрес, забытый в схеме, все равно всплывет —
    отдельным тестом про префикс `/api`.
    """
    verbs = {"get", "post", "patch", "put", "delete"}
    return [
        (method.upper(), path)
        for path, operations in openapi["paths"].items()
        for method in operations
        if method in verbs
    ]


def test_every_stub_endpoint_answers_not_implemented(
    client: TestClient, openapi: dict[str, Any]
) -> None:
    """Ни один адрес без реализации не отвечает `200` выдуманными данными.

    Допустимы ровно два исхода: `422` (запрос не прошел проверку схемы) и
    `501` (схема в порядке, реализации нет). Появление `200` означает, что
    кто-то подставил правдоподобный мок вместо честного отказа.
    """
    checked = 0
    for method, path in routes_of(openapi):
        concrete = re.sub(r"\{[^}]+\}", SAMPLE_ID, path)
        if (method, concrete) in REAL_ENDPOINTS:
            continue
        checked += 1
        response = client.request(method, concrete, json={} if method != "GET" else None)
        assert response.status_code in {422, 501}, f"{method} {concrete} -> {response.status_code}"
        error = error_of(response)
        if response.status_code == 501:
            assert error["code"] == "not_implemented"
            assert isinstance(error["details"]["missing"], list)
            assert error["details"]["missing"], f"{method} {concrete}: не сказано, чего не хватает"
    assert checked > 20, "проверено подозрительно мало адресов"


def test_every_stub_endpoint_declares_501_in_schema(openapi: dict[str, Any]) -> None:
    for path, operations in openapi["paths"].items():
        for method, operation in operations.items():
            if (method.upper(), path) in REAL_ENDPOINTS:
                continue
            assert "501" in operation["responses"], f"{method.upper()} {path}: 501 не описан"


# --- Задача 1: загрузка файла -------------------------------------------


def test_upload_constraints_are_returned_explicitly(client: TestClient) -> None:
    response = client.get("/api/uploads/constraints")
    assert response.status_code == 200
    body = response.json()
    assert body["maxSizeBytes"] == MAX_UPLOAD_BYTES
    assert body["allowedExtensions"] == list(SUPPORTED_UPLOAD_EXTENSIONS)
    assert body["allowedContentTypes"]
    # Предела длительности нет, и об этом сказано полем, а не умолчанием:
    # выдуманное число здесь стало бы обещанием продукта.
    assert body["maxDurationSeconds"] is None


def test_upload_limits_match_frontend() -> None:
    """Один и тот же предел с двух сторон.

    Если фронтенд принимает файл, который отвергнет сервер, пользователь
    получит отказ там, где интерфейс обещал прием.
    """
    source = (REPO_ROOT / "src" / "services" / "mockServices.ts").read_text(encoding="utf-8")
    megabytes = re.search(r"maxUploadBytes\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", source)
    assert megabytes, "в mockServices.ts не найден maxUploadBytes"
    assert int(megabytes.group(1)) * 1024 * 1024 == MAX_UPLOAD_BYTES

    extensions = re.search(r"supportedUploadExtensions\s*=\s*\[([^\]]+)\]", source)
    assert extensions, "в mockServices.ts не найден supportedUploadExtensions"
    parsed = tuple(re.findall(r'"([^"]+)"', extensions.group(1)))
    assert parsed == SUPPORTED_UPLOAD_EXTENSIONS


def test_upload_rejects_unsupported_format(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        json={"fileName": "track.aiff", "sizeBytes": 1024},
    )
    assert response.status_code == 422
    assert any("fileName" in field for field in field_errors(response))


def test_upload_rejects_oversized_file(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        json={"fileName": "track.mp3", "sizeBytes": MAX_UPLOAD_BYTES + 1},
    )
    assert response.status_code == 422
    assert any("sizeBytes" in field for field in field_errors(response))


def test_upload_rejects_unknown_field(client: TestClient) -> None:
    """Лишнее поле — ошибка, а не тихо проигнорированное значение."""
    response = client.post(
        "/api/uploads",
        json={"fileName": "track.mp3", "sizeBytes": 1024, "fileNmae": "опечатка"},
    )
    assert response.status_code == 422


def test_valid_upload_request_reaches_not_implemented(client: TestClient) -> None:
    response = client.post(
        "/api/uploads",
        json={
            "fileName": "track.mp3",
            "sizeBytes": 4 * 1024 * 1024,
            "contentType": "audio/mpeg",
            "durationSeconds": 214,
            "sampleRate": 44100,
            "channels": 2,
        },
    )
    assert response.status_code == 501
    assert error_of(response)["code"] == "not_implemented"


# --- Задача 2: создание проекта из загрузки ------------------------------


def valid_project_payload() -> dict[str, Any]:
    return {
        "uploadId": SAMPLE_ID,
        "name": "Кукушка: репетиция",
        "scenario": "band",
        "goalId": "band-rehearsal",
        "setup": {
            "kind": "band",
            "vocalRange": "A2-C4",
            "guitars": 2,
            "bass": "5 струн",
            "keys": "Nord Stage",
            "drums": "акустика",
            "targetStyle": "ближе к оригиналу",
        },
        "consent": {"accepted": True, "versionId": current_consent().id},
    }


def test_project_create_requires_consent_version(client: TestClient) -> None:
    payload = valid_project_payload()
    payload["consent"] = {"accepted": True}
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422
    assert any("versionId" in field for field in field_errors(response))


def test_project_create_rejects_unknown_consent_version(client: TestClient) -> None:
    payload = valid_project_payload()
    payload["consent"] = {"accepted": True, "versionId": "consent-1999-01-01"}
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422
    assert any("versionId" in field for field in field_errors(response))


def test_project_create_rejects_declined_consent(client: TestClient) -> None:
    payload = valid_project_payload()
    payload["consent"] = {"accepted": False, "versionId": current_consent().id}
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422


def test_project_create_rejects_setup_of_other_scenario(client: TestClient) -> None:
    payload = valid_project_payload()
    payload["setup"] = {
        "kind": "lesson",
        "instrument": "гитара",
        "level": "средний",
        "lessonGoal": "разобрать припев",
        "difficulty": "проще оригинала",
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422


def test_project_create_rejects_goal_of_other_scenario(client: TestClient) -> None:
    payload = valid_project_payload()
    payload["goalId"] = "lesson-easy"
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422


def test_lesson_project_payload_is_accepted_by_schema(client: TestClient) -> None:
    payload = {
        "uploadId": SAMPLE_ID,
        "name": "Урок: Кукушка",
        "scenario": "education",
        "goalId": "lesson-easy",
        "setup": {
            "kind": "lesson",
            "instrument": "гитара",
            "level": "начальный",
            "lessonGoal": "сыграть куплет",
            "difficulty": "проще оригинала",
        },
        "consent": {"accepted": True, "versionId": current_consent().id},
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 501


def test_valid_project_payload_reaches_not_implemented(client: TestClient) -> None:
    response = client.post("/api/projects", json=valid_project_payload())
    assert response.status_code == 501


def test_consent_registry_matches_frontend() -> None:
    """Версии согласия на сервере и на экране — одни и те же.

    Правка текста без смены версии делает запись «согласие получено» записью
    о том, чего пользователь не читал. Тест ловит именно это.
    """
    source = (REPO_ROOT / "src" / "domain" / "consent.ts").read_text(encoding="utf-8")
    ids = re.findall(r'id:\s*"([^"]+)"', source)
    texts = re.findall(r'^const CONSENT_TEXT_\d+ =\s*\n?\s*"([^"]+)";', source, re.MULTILINE)
    assert ids, "в consent.ts не найдены идентификаторы версий"
    assert texts, "в consent.ts не найдены тексты согласия"
    assert [version.id for version in consent_versions] == ids
    assert [version.text for version in consent_versions] == texts
    for version in consent_versions:
        assert version.fingerprint == fingerprint_of(version.text)
        assert consent_text_by_id(version.id) == version.text


def test_consent_endpoints_return_real_data(client: TestClient) -> None:
    current = client.get("/api/consent/current")
    assert current.status_code == 200
    assert current.json()["id"] == current_consent().id
    assert current.json()["text"] == current_consent().text

    listing = client.get("/api/consent/versions")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == [v.id for v in consent_versions]


def test_project_response_covers_domain(openapi: dict[str, Any]) -> None:
    """Ответ проекта повторяет `Project` из src/domain/types.ts."""
    expected = {
        "id",
        "name",
        "scenario",
        "processingGoal",
        "upload",
        "musicians",
        "assignments",
        "versions",
        "currentVersionId",
        "processing",
        "analysis",
        "stagePack",
        "reviewIssues",
        "reviewComments",
        "directorSuggestions",
        "chat",
        "changeLog",
        "shareRecipients",
        "shareLinks",
        "exportBundles",
        "costEstimate",
        "setupSnapshot",
        "legalConsent",
        "dataRetention",
    }
    assert expected <= properties(openapi, "ProjectOut")


def test_legal_consent_keeps_version_and_text(openapi: dict[str, Any]) -> None:
    assert {"accepted", "versionId", "text"} <= required_properties(openapi, "LegalConsentOut")


# --- Задача 3: статус задания -------------------------------------------


def test_job_schema_has_polling_fields(openapi: dict[str, Any]) -> None:
    required = required_properties(openapi, "ProcessingJobOut")
    assert {"id", "status", "steps", "warnings", "progressPercent"} <= required
    assert "pollAfterMs" in properties(openapi, "ProcessingJobOut")


def test_job_step_status_keeps_skipped(openapi: dict[str, Any]) -> None:
    """`skipped` отличает «шага не будет» от «шаг сделан»."""
    values = set(component(openapi, "ProcessingStepStatus")["enum"])
    assert values == {"queued", "running", "done", "warning", "error", "skipped"}


def test_job_status_is_pollable(client: TestClient) -> None:
    response = client.get(f"/api/jobs/{SAMPLE_ID}")
    assert response.status_code == 501


def test_job_start_accepts_idempotency_key(openapi: dict[str, Any]) -> None:
    operation = openapi["paths"]["/api/projects/{project_id}/jobs"]["post"]
    names = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert "Idempotency-Key" in names


# --- Задача 4: Stage Pack ------------------------------------------------


def test_stage_pack_response_has_materials_analysis_and_review(openapi: dict[str, Any]) -> None:
    required = required_properties(openapi, "StagePackResponse")
    assert {"stagePack", "analysis", "reviewIssues"} <= required


def test_artifact_schema_marks_staleness_and_confidence(openapi: dict[str, Any]) -> None:
    required = required_properties(openapi, "ArtifactOut")
    assert {"id", "type", "name", "format", "status", "confidence", "audience", "isStale"} <= required


def test_stage_pack_endpoint_is_not_implemented(client: TestClient) -> None:
    response = client.get(f"/api/projects/{SAMPLE_ID}/stage-pack")
    assert response.status_code == 501


# --- Задача 5: действия директора ---------------------------------------


def test_single_director_action_requires_known_action(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/director/actions",
        json={"actionId": "make-it-better", "baseVersionId": SAMPLE_ID},
    )
    assert response.status_code == 422


def test_single_director_action_reaches_not_implemented(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/director/actions",
        json={"actionId": "transpose-down-2", "baseVersionId": SAMPLE_ID},
    )
    assert response.status_code == 501


def test_batch_director_action_requires_at_least_one_action(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/director/actions/batch",
        json={"actionIds": [], "baseVersionId": SAMPLE_ID},
    )
    assert response.status_code == 422


def test_batch_director_action_builds_single_version(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/director/actions/batch",
        json={
            "actionIds": ["transpose-down-2", "merge-guitars"],
            "baseVersionId": SAMPLE_ID,
        },
    )
    assert response.status_code == 501


def test_director_action_result_lists_stale_artifacts(openapi: dict[str, Any]) -> None:
    required = required_properties(openapi, "DirectorActionResultOut")
    assert {"versionLabel", "versionKind", "historyTitle", "changes", "staleArtifactTypes"} <= required


# --- Задача 6: версии и откат -------------------------------------------


def test_version_schema_keeps_parent_and_snapshot(openapi: dict[str, Any]) -> None:
    fields = properties(openapi, "ArrangementVersionOut")
    assert {"parentVersionId", "artifactsSnapshot", "changes", "status", "kind"} <= fields


def test_rollback_accepts_any_version_id(client: TestClient) -> None:
    """Откат на любую глубину: целью служит любая версия проекта, не только родитель."""
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/versions/{SAMPLE_ID}/rollback",
        json={"comment": "вернуться к оригиналу"},
    )
    assert response.status_code == 501


def test_rollback_declares_version_conflict(openapi: dict[str, Any]) -> None:
    operation = openapi["paths"]["/api/projects/{project_id}/versions/{version_id}/rollback"]["post"]
    assert "409" in operation["responses"]


def test_version_select_is_not_implemented(client: TestClient) -> None:
    response = client.patch(f"/api/projects/{SAMPLE_ID}/versions/{SAMPLE_ID}/select", json={})
    assert response.status_code == 501


# --- Задача 7: проверка --------------------------------------------------


def test_review_status_enum_matches_domain(openapi: dict[str, Any]) -> None:
    values = set(component(openapi, "ReviewStatus")["enum"])
    assert values == {"needs_review", "checked", "fixed", "uncertain", "accepted_for_rehearsal"}


def test_review_status_change_rejects_unknown_status(client: TestClient) -> None:
    response = client.patch(
        f"/api/projects/{SAMPLE_ID}/review-issues/{SAMPLE_ID}",
        json={"status": "почти готово"},
    )
    assert response.status_code == 422


def test_review_status_change_reaches_not_implemented(client: TestClient) -> None:
    response = client.patch(
        f"/api/projects/{SAMPLE_ID}/review-issues/{SAMPLE_ID}",
        json={"status": "checked"},
    )
    assert response.status_code == 501


def test_review_comment_requires_text(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/review-issues/{SAMPLE_ID}/comments",
        json={"text": "   "},
    )
    assert response.status_code == 422


def test_review_comment_reaches_not_implemented(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/review-issues/{SAMPLE_ID}/comments",
        json={"text": "во втором куплете аккорд другой"},
    )
    assert response.status_code == 501


# --- Задача 8: выдача ----------------------------------------------------


def test_share_link_schema_is_revocable(openapi: dict[str, Any]) -> None:
    """Ссылка ведет на наш эндпоинт и отзывается.

    Требование `docs/DELETION_AND_RETENTION_DESIGN.md`: без отзыва обещание
    «удалить результаты» не исполняется для уже выданных ссылок.
    """
    fields = properties(openapi, "ShareLinkOut")
    assert {"url", "expiresAt", "revokedAt", "recipientId", "status"} <= fields


def test_share_link_requires_recipient(client: TestClient) -> None:
    response = client.post(f"/api/projects/{SAMPLE_ID}/share-links", json={})
    assert response.status_code == 422


def test_share_link_creation_reaches_not_implemented(client: TestClient) -> None:
    response = client.post(
        f"/api/projects/{SAMPLE_ID}/share-links",
        json={"recipientId": SAMPLE_ID, "artifactIds": [SAMPLE_ID]},
    )
    assert response.status_code == 501


def test_share_link_revocation_exists(client: TestClient) -> None:
    response = client.delete(f"/api/projects/{SAMPLE_ID}/share-links/{SAMPLE_ID}")
    assert response.status_code == 501


def test_recipient_role_enum_covers_domain(openapi: dict[str, Any]) -> None:
    values = set(component(openapi, "ShareRecipientRole")["enum"])
    assert values == {
        "vocalist",
        "guitarist",
        "bassist",
        "keys",
        "drummer",
        "teacher",
        "student",
        "parent",
    }


# --- Задача 9: удаление --------------------------------------------------


def test_source_and_results_deletion_are_separate_endpoints(openapi: dict[str, Any]) -> None:
    assert "/api/projects/{project_id}/delete-source" in openapi["paths"]
    assert "/api/projects/{project_id}/delete-results" in openapi["paths"]


def test_deletion_requires_explicit_confirmation(client: TestClient) -> None:
    """Необратимая операция не запускается пустым телом."""
    for path in ("delete-source", "delete-results"):
        response = client.post(f"/api/projects/{SAMPLE_ID}/{path}", json={})
        assert response.status_code == 422, path


def test_deletion_confirmed_reaches_not_implemented(client: TestClient) -> None:
    for path in ("delete-source", "delete-results"):
        response = client.post(f"/api/projects/{SAMPLE_ID}/{path}", json={"confirm": True})
        assert response.status_code == 501, path


def test_deletion_state_is_a_task_not_a_flag(openapi: dict[str, Any]) -> None:
    """`DELETION_AND_RETENTION_DESIGN.md`: статус подтвержденный, а не флаг."""
    values = set(component(openapi, "DeletionState")["enum"])
    assert values == {"present", "purge_requested", "purged", "purge_failed"}
    required = required_properties(openapi, "DeletionStatusOut")
    assert {"source", "results"} <= required


def test_deletion_status_endpoint_exists(client: TestClient) -> None:
    response = client.get(f"/api/projects/{SAMPLE_ID}/deletion-status")
    assert response.status_code == 501


# --- Выгруженная схема ---------------------------------------------------


def test_exported_openapi_is_current(openapi: dict[str, Any]) -> None:
    """`docs/api/openapi.json` совпадает с тем, что отдает приложение.

    Иначе фронтенд сгенерирует клиент по устаревшему контракту и получит
    несоответствие полей уже в рантайме.
    """
    assert OPENAPI_FILE.exists(), "схема не выгружена в docs/api/openapi.json"
    exported = json.loads(OPENAPI_FILE.read_text(encoding="utf-8"))
    assert exported == json.loads(json.dumps(openapi))
