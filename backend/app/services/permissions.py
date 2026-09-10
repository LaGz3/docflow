import uuid

from sqlmodel import Session, select

from app.core.errors import PermissionDeniedError, ResourceNotFoundError
from app.models import Organization, OrganizationMembership, OrganizationRole, User

ROLE_LEVEL = {
    OrganizationRole.MEMBER: 1,
    OrganizationRole.REVIEWER: 2,
    OrganizationRole.ADMIN: 3,
    OrganizationRole.OWNER: 4,
}


def require_organization_membership(
    session: Session,
    organization_id: uuid.UUID,
    user: User,
) -> OrganizationMembership:
    organization = session.get(Organization, organization_id)
    if organization is None:
        raise ResourceNotFoundError("Organization not found")

    membership = session.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    ).first()
    if membership is None:
        raise PermissionDeniedError("You are not a member of this organization")
    return membership


def require_organization_role(
    session: Session,
    organization_id: uuid.UUID,
    user: User,
    minimum_role: OrganizationRole,
) -> OrganizationMembership:
    membership = require_organization_membership(session, organization_id, user)
    if ROLE_LEVEL[membership.role] < ROLE_LEVEL[minimum_role]:
        raise PermissionDeniedError()
    return membership

