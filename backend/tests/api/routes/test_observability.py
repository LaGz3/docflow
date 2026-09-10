from fastapi.testclient import TestClient

from app.core.config import settings


def test_request_id_is_returned(client: TestClient) -> None:
    response = client.get(
        f"{settings.API_V1_STR}/utils/health-check/",
        headers={"X-Request-ID": "request-test-001"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-test-001"


def test_request_id_is_generated(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/utils/health-check/")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
