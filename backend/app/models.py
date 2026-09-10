import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import EmailStr, field_validator
from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    MEMBER = "member"


class OrganizationBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=3, max_length=80)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*",
            normalized,
        ):
            raise ValueError("slug只能包含小写字母、数字和连字符")

        return normalized


class OrganizationCreate(OrganizationBase):
    pass


class Organization(OrganizationBase, table=True):
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    slug: str = Field(
        min_length=3,
        max_length=80,
        unique=True,
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class OrganizationMembership(SQLModel, table=True):
    __tablename__ = "organization_membership"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_membership",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
    )
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        ondelete="CASCADE",
        index=True,
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        index=True,
    )
    role: OrganizationRole = Field(
        default=OrganizationRole.MEMBER,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class OrganizationPublic(OrganizationBase):
    id: uuid.UUID
    role: OrganizationRole
    created_at: datetime


class OrganizationsPublic(SQLModel):
    data: list[OrganizationPublic]
    count: int


class OrganizationMemberCreate(SQLModel):
    email: EmailStr
    role: OrganizationRole = OrganizationRole.MEMBER


class OrganizationMemberUpdate(SQLModel):
    role: OrganizationRole


class OrganizationMemberPublic(SQLModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: OrganizationRole
    created_at: datetime


class OrganizationMembersPublic(SQLModel):
    data: list[OrganizationMemberPublic]
    count: int


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class IdempotencyRecord(SQLModel, table=True):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "user_id",
            "idempotency_key",
            name="uq_idempotency_record_scope",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        ondelete="CASCADE",
        index=True,
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        index=True,
    )
    idempotency_key: str = Field(min_length=1, max_length=255)
    request_hash: str = Field(min_length=64, max_length=64)
    resource_id: uuid.UUID = Field(index=True)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class DocumentBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)


class DocumentCreate(DocumentBase):
    content: str = Field(min_length=1)


class DocumentUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    content: str | None = Field(default=None, min_length=1)
    change_summary: str | None = Field(default=None, max_length=500)
    expected_lock_version: int = Field(ge=1)


class Document(DocumentBase, table=True):
    __tablename__ = "document"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        ondelete="CASCADE",
        index=True,
    )
    status: DocumentStatus = Field(default=DocumentStatus.DRAFT, index=True)
    current_version_number: int = Field(default=1, ge=1)
    lock_version: int = Field(default=1, ge=1)
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="RESTRICT",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class DocumentVersion(SQLModel, table=True):
    __tablename__ = "document_version"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_version_number",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id",
        ondelete="CASCADE",
        index=True,
    )
    version_number: int = Field(ge=1)
    content: str = Field(sa_column=Column(Text, nullable=False))
    change_summary: str | None = Field(default=None, max_length=500)
    created_by_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="RESTRICT",
        index=True,
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )


class Approval(SQLModel, table=True):
    __tablename__ = "approval"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    document_id: uuid.UUID = Field(
        foreign_key="document.id",
        ondelete="CASCADE",
        index=True,
    )
    document_version_id: uuid.UUID = Field(
        foreign_key="document_version.id",
        ondelete="CASCADE",
        index=True,
    )
    submitted_by_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="RESTRICT",
        index=True,
    )
    reviewer_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
        index=True,
    )
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING, index=True)
    comment: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    decided_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        ondelete="CASCADE",
        index=True,
    )
    actor_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="user.id",
        ondelete="SET NULL",
        index=True,
    )
    action: str = Field(max_length=100, index=True)
    resource_type: str = Field(max_length=100, index=True)
    resource_id: uuid.UUID = Field(index=True)
    details: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        index=True,
    )


class NotificationOutbox(SQLModel, table=True):
    __tablename__ = "notification_outbox"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    organization_id: uuid.UUID = Field(
        foreign_key="organization.id",
        ondelete="CASCADE",
        index=True,
    )
    recipient_id: uuid.UUID = Field(
        foreign_key="user.id",
        ondelete="CASCADE",
        index=True,
    )
    event_type: str = Field(max_length=100, index=True)
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    status: NotificationStatus = Field(
        default=NotificationStatus.PENDING,
        index=True,
    )
    attempts: int = Field(default=0, ge=0)
    available_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        index=True,
    )
    last_error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
    )
    processed_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
    )


class DocumentPublic(DocumentBase):
    id: uuid.UUID
    organization_id: uuid.UUID
    status: DocumentStatus
    current_version_number: int
    lock_version: int
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentPublic):
    content: str
    latest_version_id: uuid.UUID


class DocumentsPublic(SQLModel):
    data: list[DocumentPublic]
    count: int


class DocumentVersionPublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    content: str
    change_summary: str | None
    created_by_id: uuid.UUID
    created_at: datetime


class ApprovalPublic(SQLModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    submitted_by_id: uuid.UUID
    reviewer_id: uuid.UUID | None
    status: ApprovalStatus
    comment: str | None
    created_at: datetime
    decided_at: datetime | None


class DocumentActionResponse(SQLModel):
    document: DocumentPublic
    approval: ApprovalPublic | None = None


class WorkflowActionRequest(SQLModel):
    expected_lock_version: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=1000)


class SubmitForReviewRequest(WorkflowActionRequest):
    reviewer_id: uuid.UUID | None = None


class AuditLogPublic(SQLModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    actor_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID
    details: dict
    created_at: datetime


class AuditLogsPublic(SQLModel):
    data: list[AuditLogPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


class HealthStatus(SQLModel):
    status: Literal["ok", "degraded"]
    database: bool
    redis: bool


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
