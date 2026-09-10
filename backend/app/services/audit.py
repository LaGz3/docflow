import uuid

from sqlmodel import Session

from app.models import AuditLog


def add_audit_log(
    session: Session,
    *,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    details: dict | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        organization_id=organization_id,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )
    session.add(audit_log)
    return audit_log

