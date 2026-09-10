import uuid

from fastapi.testclient import TestClient

from app.core.config import settings


def create_organization_data() -> dict[str, str]:
    suffix = uuid.uuid4().hex[:8]

    return {
        "name": f"Test Organization {suffix}",
        "slug": f"test-org-{suffix}",
    }


def test_create_organization_assigns_owner(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    data = create_organization_data()

    response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
        json=data,
    )

    assert response.status_code == 201

    content = response.json()
    assert content["name"] == data["name"]
    assert content["slug"] == data["slug"]
    assert content["role"] == "owner"
    assert "id" in content
    assert "created_at" in content


def test_read_my_organizations(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    data = create_organization_data()

    create_response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
        json=data,
    )
    organization_id = create_response.json()["id"]

    response = client.get(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200

    content = response.json()
    organization_ids = {organization["id"] for organization in content["data"]}

    assert organization_id in organization_ids
    assert content["count"] == len(content["data"])


def test_duplicate_slug_returns_409(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    data = create_organization_data()

    first_response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
        json=data,
    )
    second_response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
        json=data,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert second_response.json() == {
        "detail": "Organization slug already exists",
        "code": "CONFLICT",
    }


def test_invalid_slug_returns_422(
    client: TestClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/organizations/",
        headers=normal_user_token_headers,
        json={
            "name": "Invalid Organization",
            "slug": "含有 空格",
        },
    )

    assert response.status_code == 422
