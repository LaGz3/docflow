from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    Approval,
    AuditLog,
    Document,
    DocumentVersion,
    IdempotencyRecord,
    Item,
    NotificationOutbox,
    Organization,
    OrganizationMembership,
    User,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

database_name = make_url(str(settings.DATABASE_URL)).database
if database_name != "app_test":
    raise RuntimeError(
        "Tests must run against the isolated 'app_test' database, "
        f"not {database_name!r}. Run scripts/test-backend-isolated.ps1."
    )


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session]:
    with Session(engine) as session:
        init_db(session)
        yield session
        for model in (
            IdempotencyRecord,
            AuditLog,
            NotificationOutbox,
            Approval,
            DocumentVersion,
            Document,
            OrganizationMembership,
            Organization,
            Item,
            User,
        ):
            session.execute(delete(model))
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
