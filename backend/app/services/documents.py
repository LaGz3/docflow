import hashlib
import json
import uuid

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.core.cache import delete as delete_cache
from app.core.cache import get_json, set_json
from app.core.errors import (
    ConflictError,
    InvalidTransitionError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.models import (
    Approval,
    ApprovalStatus,
    Document,
    DocumentCreate,
    DocumentStatus,
    DocumentUpdate,
    DocumentVersion,
    IdempotencyRecord,
    NotificationOutbox,
    OrganizationMembership,
    OrganizationRole,
    User,
    WorkflowActionRequest,
    get_datetime_utc,
)
from app.services.audit import add_audit_log
from app.services.permissions import (
    ROLE_LEVEL,
    require_organization_membership,
    require_organization_role,
)


def _document_cache_key(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
) -> str:
    return f"document:{organization_id}:{document_id}"


def _invalidate_document_cache(document: Document) -> None:
    delete_cache(_document_cache_key(document.organization_id, document.id))


def _can_manage_document(
    document: Document,
    membership: OrganizationMembership,
    user: User,
) -> bool:
    return document.created_by_id == user.id or membership.role in {
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    }


def _check_lock_version(document: Document, expected_lock_version: int) -> None:
    if document.lock_version != expected_lock_version:
        raise ConflictError(
            "Document was modified by another request. Refresh it and try again."
        )


def _get_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    for_update: bool = False,
) -> Document:
    statement = select(Document).where(
        Document.id == document_id,
        Document.organization_id == organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    document = session.exec(statement).first()
    if document is None:
        raise ResourceNotFoundError("Document not found")
    return document


def get_latest_version(session: Session, document: Document) -> DocumentVersion:
    version = session.exec(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.version_number == document.current_version_number,
        )
    ).first()
    if version is None:
        raise ResourceNotFoundError("Document version not found")
    return version


def create_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    user: User,
    document_in: DocumentCreate,
    idempotency_key: str | None = None,
) -> tuple[Document, DocumentVersion]:
    require_organization_membership(session, organization_id, user)
    request_hash = hashlib.sha256(
        json.dumps(
            document_in.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    if idempotency_key is not None:
        existing = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == user.id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    "Idempotency key was already used with a different request"
                )
            document = _get_document(
                session,
                organization_id=organization_id,
                document_id=existing.resource_id,
            )
            return document, get_latest_version(session, document)

    document = Document(
        organization_id=organization_id,
        created_by_id=user.id,
        title=document_in.title,
        description=document_in.description,
    )
    session.add(document)
    session.flush()

    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content=document_in.content,
        change_summary="Initial version",
        created_by_id=user.id,
    )
    session.add(version)
    if idempotency_key is not None:
        session.add(
            IdempotencyRecord(
                organization_id=organization_id,
                user_id=user.id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                resource_id=document.id,
            )
        )
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action="document.created",
        resource_type="document",
        resource_id=document.id,
        details={"version_number": 1},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if idempotency_key is None:
            raise
        existing = session.exec(
            select(IdempotencyRecord).where(
                IdempotencyRecord.organization_id == organization_id,
                IdempotencyRecord.user_id == user.id,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        ).first()
        if existing is None or existing.request_hash != request_hash:
            raise ConflictError("Idempotency key conflict") from None
        document = _get_document(
            session,
            organization_id=organization_id,
            document_id=existing.resource_id,
        )
        return document, get_latest_version(session, document)
    session.refresh(document)
    session.refresh(version)
    return document, version


def list_documents(
    session: Session,
    *,
    organization_id: uuid.UUID,
    user: User,
    status: DocumentStatus | None,
    search: str | None,
    offset: int,
    limit: int,
) -> tuple[list[Document], int]:
    require_organization_membership(session, organization_id, user)
    filters = [Document.organization_id == organization_id]
    if status is not None:
        filters.append(Document.status == status)
    if search:
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                col(Document.title).ilike(term),
                col(Document.description).ilike(term),
            )
        )

    count = session.exec(
        select(func.count()).select_from(Document).where(*filters)
    ).one()
    documents = session.exec(
        select(Document)
        .where(*filters)
        .order_by(col(Document.updated_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return list(documents), count


def get_document_detail(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
) -> tuple[Document, DocumentVersion]:
    require_organization_membership(session, organization_id, user)
    cache_key = _document_cache_key(organization_id, document_id)
    cached = get_json(cache_key)
    if cached is not None:
        return (
            Document.model_validate(cached["document"]),
            DocumentVersion.model_validate(cached["version"]),
        )
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
    )
    version = get_latest_version(session, document)
    set_json(
        cache_key,
        {
            "document": document.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
        },
    )
    return document, version


def update_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    document_in: DocumentUpdate,
) -> tuple[Document, DocumentVersion]:
    membership = require_organization_membership(session, organization_id, user)
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        for_update=True,
    )
    if not _can_manage_document(document, membership, user):
        raise PermissionDeniedError()
    if document.status not in {DocumentStatus.DRAFT, DocumentStatus.REJECTED}:
        raise InvalidTransitionError("Only draft or rejected documents can be edited")
    _check_lock_version(document, document_in.expected_lock_version)

    update_data = document_in.model_dump(
        exclude={"content", "change_summary", "expected_lock_version"},
        exclude_unset=True,
    )
    document.sqlmodel_update(update_data)

    if document_in.content is not None:
        document.current_version_number += 1
        version = DocumentVersion(
            document_id=document.id,
            version_number=document.current_version_number,
            content=document_in.content,
            change_summary=document_in.change_summary,
            created_by_id=user.id,
        )
        session.add(version)
    else:
        version = get_latest_version(session, document)

    document.status = DocumentStatus.DRAFT
    document.lock_version += 1
    document.updated_at = get_datetime_utc()
    session.add(document)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action="document.updated",
        resource_type="document",
        resource_id=document.id,
        details={"version_number": document.current_version_number},
    )
    session.commit()
    session.refresh(document)
    session.refresh(version)
    _invalidate_document_cache(document)
    return document, version


def list_document_versions(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
) -> list[DocumentVersion]:
    require_organization_membership(session, organization_id, user)
    _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
    )
    return list(
        session.exec(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(col(DocumentVersion.version_number).desc())
        ).all()
    )


def submit_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    action_in: WorkflowActionRequest,
    reviewer_id: uuid.UUID | None,
) -> tuple[Document, Approval]:
    membership = require_organization_membership(session, organization_id, user)
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        for_update=True,
    )
    if not _can_manage_document(document, membership, user):
        raise PermissionDeniedError()
    if document.status != DocumentStatus.DRAFT:
        raise InvalidTransitionError("Only draft documents can be submitted")
    _check_lock_version(document, action_in.expected_lock_version)

    if reviewer_id is not None:
        reviewer_membership = session.exec(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == reviewer_id,
            )
        ).first()
        if reviewer_membership is None or ROLE_LEVEL[reviewer_membership.role] < ROLE_LEVEL[
            OrganizationRole.REVIEWER
        ]:
            raise ConflictError("Assigned reviewer is not eligible to review documents")

    version = get_latest_version(session, document)
    approval = Approval(
        document_id=document.id,
        document_version_id=version.id,
        submitted_by_id=user.id,
        reviewer_id=reviewer_id,
        comment=action_in.comment,
    )
    session.add(approval)
    if reviewer_id is not None:
        session.add(
            NotificationOutbox(
                organization_id=organization_id,
                recipient_id=reviewer_id,
                event_type="document.review_requested",
                payload={
                    "document_id": str(document.id),
                    "title": document.title,
                    "approval_id": str(approval.id),
                },
            )
        )
    document.status = DocumentStatus.IN_REVIEW
    document.lock_version += 1
    document.updated_at = get_datetime_utc()
    session.add(document)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action="document.submitted",
        resource_type="document",
        resource_id=document.id,
        details={"reviewer_id": str(reviewer_id) if reviewer_id else None},
    )
    session.commit()
    session.refresh(document)
    session.refresh(approval)
    _invalidate_document_cache(document)
    return document, approval


def decide_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    action_in: WorkflowActionRequest,
    approve: bool,
) -> tuple[Document, Approval]:
    membership = require_organization_role(
        session,
        organization_id,
        user,
        OrganizationRole.REVIEWER,
    )
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        for_update=True,
    )
    if document.status != DocumentStatus.IN_REVIEW:
        raise InvalidTransitionError("Document is not awaiting review")
    _check_lock_version(document, action_in.expected_lock_version)

    approval = session.exec(
        select(Approval).where(
            Approval.document_id == document.id,
            Approval.status == ApprovalStatus.PENDING,
        )
    ).first()
    if approval is None:
        raise ResourceNotFoundError("Pending approval not found")
    if approval.submitted_by_id == user.id:
        raise PermissionDeniedError("A submitter cannot review their own document")
    if (
        approval.reviewer_id is not None
        and approval.reviewer_id != user.id
        and membership.role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
    ):
        raise PermissionDeniedError("This approval is assigned to another reviewer")

    now = get_datetime_utc()
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.comment = action_in.comment
    approval.decided_at = now
    document.status = DocumentStatus.APPROVED if approve else DocumentStatus.REJECTED
    document.lock_version += 1
    document.updated_at = now
    session.add(approval)
    session.add(document)
    action = "document.approved" if approve else "document.rejected"
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action=action,
        resource_type="document",
        resource_id=document.id,
        details={"approval_id": str(approval.id)},
    )
    session.commit()
    session.refresh(document)
    session.refresh(approval)
    _invalidate_document_cache(document)
    return document, approval


def withdraw_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    action_in: WorkflowActionRequest,
) -> Document:
    membership = require_organization_membership(session, organization_id, user)
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        for_update=True,
    )
    if document.status != DocumentStatus.IN_REVIEW:
        raise InvalidTransitionError("Document is not awaiting review")
    _check_lock_version(document, action_in.expected_lock_version)

    approval = session.exec(
        select(Approval).where(
            Approval.document_id == document.id,
            Approval.status == ApprovalStatus.PENDING,
        )
    ).first()
    if approval is None:
        raise ResourceNotFoundError("Pending approval not found")
    if approval.submitted_by_id != user.id and membership.role not in {
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    }:
        raise PermissionDeniedError()

    approval.status = ApprovalStatus.CANCELLED
    approval.comment = action_in.comment
    approval.decided_at = get_datetime_utc()
    document.status = DocumentStatus.DRAFT
    document.lock_version += 1
    document.updated_at = get_datetime_utc()
    session.add(approval)
    session.add(document)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action="document.withdrawn",
        resource_type="document",
        resource_id=document.id,
        details={"approval_id": str(approval.id)},
    )
    session.commit()
    session.refresh(document)
    _invalidate_document_cache(document)
    return document


def archive_document(
    session: Session,
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    user: User,
    action_in: WorkflowActionRequest,
) -> Document:
    require_organization_role(
        session,
        organization_id,
        user,
        OrganizationRole.ADMIN,
    )
    document = _get_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        for_update=True,
    )
    if document.status == DocumentStatus.IN_REVIEW:
        raise InvalidTransitionError("A document under review cannot be archived")
    if document.status == DocumentStatus.ARCHIVED:
        raise InvalidTransitionError("Document is already archived")
    _check_lock_version(document, action_in.expected_lock_version)

    document.status = DocumentStatus.ARCHIVED
    document.lock_version += 1
    document.updated_at = get_datetime_utc()
    session.add(document)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=user.id,
        action="document.archived",
        resource_type="document",
        resource_id=document.id,
    )
    session.commit()
    session.refresh(document)
    _invalidate_document_cache(document)
    return document
