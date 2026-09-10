import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import NotificationOutbox, NotificationStatus
from app.workers.notifications import process_next_notification
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import random_email


def create_organization(
    client: TestClient,
    headers: dict[str, str],
) -> dict:
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=headers,
        json={"name": f"Organization {suffix}", "slug": f"org-{suffix}"},
    )
    assert response.status_code == 201
    return response.json()


def create_document(
    client: TestClient,
    headers: dict[str, str],
    organization_id: str,
) -> dict:
    response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization_id}/documents/",
        headers=headers,
        json={
            "title": "Security Policy",
            "description": "Initial security rules",
            "content": "All accounts must enable MFA.",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_document_approval_lifecycle(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(
        client,
        normal_user_token_headers,
        organization["id"],
    )
    assert document["status"] == "draft"
    assert document["current_version_number"] == 1
    assert document["lock_version"] == 1

    update_response = client.patch(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}",
        headers=normal_user_token_headers,
        json={
            "content": "All accounts must enable MFA and rotate recovery codes.",
            "change_summary": "Add recovery-code requirement",
            "expected_lock_version": 1,
        },
    )
    assert update_response.status_code == 200
    document = update_response.json()
    assert document["current_version_number"] == 2
    assert document["lock_version"] == 2

    versions_response = client.get(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/versions",
        headers=normal_user_token_headers,
    )
    assert versions_response.status_code == 200
    assert [item["version_number"] for item in versions_response.json()] == [2, 1]

    reviewer_email = random_email()
    reviewer_headers = authentication_token_from_email(
        client=client,
        email=reviewer_email,
        db=db,
    )
    member_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}/members",
        headers=normal_user_token_headers,
        json={"email": reviewer_email, "role": "reviewer"},
    )
    assert member_response.status_code == 201
    reviewer_id = member_response.json()["user_id"]

    submit_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/submit",
        headers=normal_user_token_headers,
        json={
            "expected_lock_version": 2,
            "reviewer_id": reviewer_id,
            "comment": "Please review the updated policy.",
        },
    )
    assert submit_response.status_code == 200
    submitted = submit_response.json()
    assert submitted["document"]["status"] == "in_review"
    assert submitted["document"]["lock_version"] == 3
    assert submitted["approval"]["status"] == "pending"

    with patch("app.workers.notifications.send_email") as mock_send_email:
        assert process_next_notification() is True
    mock_send_email.assert_called_once()
    notification = db.exec(
        select(NotificationOutbox).where(
            NotificationOutbox.recipient_id == uuid.UUID(reviewer_id)
        )
    ).first()
    assert notification is not None
    db.refresh(notification)
    assert notification.status == NotificationStatus.SENT

    approve_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/approve",
        headers=reviewer_headers,
        json={"expected_lock_version": 3, "comment": "Approved."},
    )
    assert approve_response.status_code == 200
    approved = approve_response.json()
    assert approved["document"]["status"] == "approved"
    assert approved["document"]["lock_version"] == 4
    assert approved["approval"]["status"] == "approved"

    list_response = client.get(
        f"{settings.API_V1_STR}/organizations/{organization['id']}/documents/",
        headers=normal_user_token_headers,
        params={"status": "approved", "search": "Security"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    audit_response = client.get(
        f"{settings.API_V1_STR}/organizations/{organization['id']}/audit-logs/",
        headers=normal_user_token_headers,
        params={"resource_id": document["id"]},
    )
    assert audit_response.status_code == 200
    audit_actions = {item["action"] for item in audit_response.json()["data"]}
    assert {
        "document.created",
        "document.updated",
        "document.submitted",
        "document.approved",
    }.issubset(audit_actions)


def test_stale_document_version_returns_conflict(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(client, normal_user_token_headers, organization["id"])

    response = client.patch(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}",
        headers=normal_user_token_headers,
        json={"title": "Stale update", "expected_lock_version": 99},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_non_member_cannot_read_organization_document(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
    db: Session,
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(client, normal_user_token_headers, organization["id"])
    outsider_headers = authentication_token_from_email(
        client=client,
        email=random_email(),
        db=db,
    )

    response = client.get(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}",
        headers=outsider_headers,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_invalid_document_status_is_rejected(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    response = client.get(
        f"{settings.API_V1_STR}/organizations/{organization['id']}/documents/",
        headers=normal_user_token_headers,
        params={"status": "unknown"},
    )
    assert response.status_code == 422


def test_submitter_cannot_approve_own_document(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(client, normal_user_token_headers, organization["id"])
    submit_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/submit",
        headers=normal_user_token_headers,
        json={"expected_lock_version": 1},
    )
    assert submit_response.status_code == 200

    approve_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/approve",
        headers=normal_user_token_headers,
        json={"expected_lock_version": 2},
    )
    assert approve_response.status_code == 403
    assert approve_response.json()["code"] == "FORBIDDEN"


def test_submitted_document_can_be_withdrawn(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(client, normal_user_token_headers, organization["id"])
    submit_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/submit",
        headers=normal_user_token_headers,
        json={"expected_lock_version": 1},
    )
    assert submit_response.status_code == 200

    withdraw_response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/withdraw",
        headers=normal_user_token_headers,
        json={"expected_lock_version": 2, "comment": "Needs another edit."},
    )
    assert withdraw_response.status_code == 200
    assert withdraw_response.json()["document"]["status"] == "draft"
    assert withdraw_response.json()["document"]["lock_version"] == 3


def test_draft_document_cannot_be_approved(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    document = create_document(client, normal_user_token_headers, organization["id"])
    response = client.post(
        f"{settings.API_V1_STR}/organizations/{organization['id']}"
        f"/documents/{document['id']}/approve",
        headers=normal_user_token_headers,
        json={"expected_lock_version": 1},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "INVALID_TRANSITION"


def test_document_creation_is_idempotent(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    headers = {
        **normal_user_token_headers,
        "Idempotency-Key": f"create-{uuid.uuid4()}",
    }
    payload = {
        "title": "Incident response policy",
        "description": "Security incident workflow",
        "content": "Report incidents within 30 minutes.",
    }
    url = (
        f"{settings.API_V1_STR}/organizations/{organization['id']}/documents/"
    )

    first = client.post(url, headers=headers, json=payload)
    second = client.post(url, headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    listed = client.get(url, headers=normal_user_token_headers)
    assert listed.json()["count"] == 1


def test_idempotency_key_cannot_be_reused_for_another_request(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    organization = create_organization(client, normal_user_token_headers)
    headers = {
        **normal_user_token_headers,
        "Idempotency-Key": f"create-{uuid.uuid4()}",
    }
    url = (
        f"{settings.API_V1_STR}/organizations/{organization['id']}/documents/"
    )
    first = client.post(
        url,
        headers=headers,
        json={"title": "Policy A", "content": "Content A"},
    )
    second = client.post(
        url,
        headers=headers,
        json={"title": "Policy B", "content": "Content B"},
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"
