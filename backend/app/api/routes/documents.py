import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    ApprovalPublic,
    DocumentActionResponse,
    DocumentCreate,
    DocumentDetail,
    DocumentPublic,
    DocumentsPublic,
    DocumentStatus,
    DocumentUpdate,
    DocumentVersionPublic,
    SubmitForReviewRequest,
    WorkflowActionRequest,
)
from app.services import documents as document_service

router = APIRouter(
    prefix="/organizations/{organization_id}/documents",
    tags=["documents"],
)


def _document_detail(
    document,
    version,
) -> DocumentDetail:
    return DocumentDetail.model_validate(
        document,
        update={
            "content": version.content,
            "latest_version_id": version.id,
        },
    )


def _action_response(document, approval=None) -> DocumentActionResponse:
    return DocumentActionResponse(
        document=DocumentPublic.model_validate(document),
        approval=(
            ApprovalPublic.model_validate(approval) if approval is not None else None
        ),
    )


@router.post("/", response_model=DocumentDetail, status_code=201)
def create_document(
    *,
    organization_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    document_in: DocumentCreate,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=1, max_length=255),
    ] = None,
) -> DocumentDetail:
    document, version = document_service.create_document(
        session,
        organization_id=organization_id,
        user=current_user,
        document_in=document_in,
        idempotency_key=idempotency_key,
    )
    return _document_detail(document, version)


@router.get("/", response_model=DocumentsPublic)
def read_documents(
    *,
    organization_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    status: DocumentStatus | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DocumentsPublic:
    documents, count = document_service.list_documents(
        session,
        organization_id=organization_id,
        user=current_user,
        status=status,
        search=search,
        offset=offset,
        limit=limit,
    )
    return DocumentsPublic(
        data=[DocumentPublic.model_validate(document) for document in documents],
        count=count,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def read_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> DocumentDetail:
    document, version = document_service.get_document_detail(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
    )
    return _document_detail(document, version)


@router.patch("/{document_id}", response_model=DocumentDetail)
def update_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    document_in: DocumentUpdate,
) -> DocumentDetail:
    document, version = document_service.update_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        document_in=document_in,
    )
    return _document_detail(document, version)


@router.get(
    "/{document_id}/versions",
    response_model=list[DocumentVersionPublic],
)
def read_document_versions(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> list[DocumentVersionPublic]:
    versions = document_service.list_document_versions(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
    )
    return [DocumentVersionPublic.model_validate(version) for version in versions]


@router.post("/{document_id}/submit", response_model=DocumentActionResponse)
def submit_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action_in: SubmitForReviewRequest,
) -> DocumentActionResponse:
    document, approval = document_service.submit_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        action_in=action_in,
        reviewer_id=action_in.reviewer_id,
    )
    return _action_response(document, approval)


@router.post("/{document_id}/approve", response_model=DocumentActionResponse)
def approve_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action_in: WorkflowActionRequest,
) -> DocumentActionResponse:
    document, approval = document_service.decide_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        action_in=action_in,
        approve=True,
    )
    return _action_response(document, approval)


@router.post("/{document_id}/reject", response_model=DocumentActionResponse)
def reject_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action_in: WorkflowActionRequest,
) -> DocumentActionResponse:
    document, approval = document_service.decide_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        action_in=action_in,
        approve=False,
    )
    return _action_response(document, approval)


@router.post("/{document_id}/withdraw", response_model=DocumentActionResponse)
def withdraw_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action_in: WorkflowActionRequest,
) -> DocumentActionResponse:
    document = document_service.withdraw_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        action_in=action_in,
    )
    return _action_response(document)


@router.post("/{document_id}/archive", response_model=DocumentActionResponse)
def archive_document(
    *,
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action_in: WorkflowActionRequest,
) -> DocumentActionResponse:
    document = document_service.archive_document(
        session,
        organization_id=organization_id,
        document_id=document_id,
        user=current_user,
        action_in=action_in,
    )
    return _action_response(document)
