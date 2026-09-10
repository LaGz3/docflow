import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import AuditLog, AuditLogPublic, AuditLogsPublic, OrganizationRole
from app.services.permissions import require_organization_role

router = APIRouter(
    prefix="/organizations/{organization_id}/audit-logs",
    tags=["audit-logs"],
)


@router.get("/", response_model=AuditLogsPublic)
def read_audit_logs(
    *,
    organization_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    action: Annotated[str | None, Query(max_length=100)] = None,
    resource_type: Annotated[str | None, Query(max_length=100)] = None,
    resource_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditLogsPublic:
    require_organization_role(
        session,
        organization_id,
        current_user,
        OrganizationRole.ADMIN,
    )
    filters = [AuditLog.organization_id == organization_id]
    if action:
        filters.append(AuditLog.action == action)
    if resource_type:
        filters.append(AuditLog.resource_type == resource_type)
    if resource_id:
        filters.append(AuditLog.resource_id == resource_id)

    count = session.exec(
        select(func.count()).select_from(AuditLog).where(*filters)
    ).one()
    logs = session.exec(
        select(AuditLog)
        .where(*filters)
        .order_by(col(AuditLog.created_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return AuditLogsPublic(
        data=[AuditLogPublic.model_validate(log) for log in logs],
        count=count,
    )

