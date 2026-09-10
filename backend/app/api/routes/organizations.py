import uuid
from typing import Any

from fastapi import APIRouter
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.core.errors import ConflictError, PermissionDeniedError, ResourceNotFoundError
from app.models import (
    Organization,
    OrganizationCreate,
    OrganizationMemberCreate,
    OrganizationMemberPublic,
    OrganizationMembership,
    OrganizationMembersPublic,
    OrganizationMemberUpdate,
    OrganizationPublic,
    OrganizationRole,
    OrganizationsPublic,
    User,
)
from app.services.audit import add_audit_log
from app.services.permissions import (
    ROLE_LEVEL,
    require_organization_role,
)

router = APIRouter(
    prefix="/organizations",
    tags=["organizations"],
)


@router.post(
    "/",
    response_model=OrganizationPublic,
    status_code=201,
)
def create_organization(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    organization_in: OrganizationCreate,
) -> Any:
    existing = session.exec(
        select(Organization).where(Organization.slug == organization_in.slug)
    ).first()

    if existing:
        raise ConflictError("Organization slug already exists")

    organization = Organization.model_validate(organization_in)
    session.add(organization)
    session.flush()

    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
    )
    session.add(membership)
    add_audit_log(
        session,
        organization_id=organization.id,
        actor_id=current_user.id,
        action="organization.created",
        resource_type="organization",
        resource_id=organization.id,
    )
    session.commit()
    session.refresh(organization)

    return OrganizationPublic.model_validate(
        organization,
        update={"role": OrganizationRole.OWNER},
    )


@router.get(
    "/",
    response_model=OrganizationsPublic,
)
def read_my_organizations(
    *,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    statement = (
        select(
            Organization,
            OrganizationMembership.role,
        )
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(OrganizationMembership.user_id == current_user.id)
        .order_by(Organization.created_at.desc())
    )

    rows = session.exec(statement).all()

    organizations = [
        OrganizationPublic.model_validate(
            organization,
            update={"role": role},
        )
        for organization, role in rows
    ]

    return OrganizationsPublic(
        data=organizations,
        count=len(organizations),
    )


@router.get(
    "/{organization_id}/members",
    response_model=OrganizationMembersPublic,
)
def read_organization_members(
    *,
    organization_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> OrganizationMembersPublic:
    require_organization_role(
        session,
        organization_id,
        current_user,
        OrganizationRole.MEMBER,
    )
    rows = session.exec(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(OrganizationMembership.organization_id == organization_id)
        .order_by(OrganizationMembership.created_at)
    ).all()
    members = [
        OrganizationMemberPublic(
            id=membership.id,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            created_at=membership.created_at,
        )
        for membership, user in rows
    ]
    return OrganizationMembersPublic(data=members, count=len(members))


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberPublic,
    status_code=201,
)
def add_organization_member(
    *,
    organization_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    member_in: OrganizationMemberCreate,
) -> OrganizationMemberPublic:
    require_organization_role(
        session,
        organization_id,
        current_user,
        OrganizationRole.ADMIN,
    )
    if member_in.role == OrganizationRole.OWNER:
        raise ConflictError("Owner role can only be changed through ownership transfer")

    user = session.exec(select(User).where(User.email == member_in.email)).first()
    if user is None:
        raise ResourceNotFoundError("User not found")
    existing = session.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    ).first()
    if existing is not None:
        raise ConflictError("User is already a member of this organization")

    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user.id,
        role=member_in.role,
    )
    session.add(membership)
    session.flush()
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=current_user.id,
        action="organization.member_added",
        resource_type="organization_membership",
        resource_id=membership.id,
        details={"user_id": str(user.id), "role": member_in.role.value},
    )
    session.commit()
    session.refresh(membership)
    return OrganizationMemberPublic(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.patch(
    "/{organization_id}/members/{membership_id}",
    response_model=OrganizationMemberPublic,
)
def update_organization_member(
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    member_in: OrganizationMemberUpdate,
) -> OrganizationMemberPublic:
    require_organization_role(
        session,
        organization_id,
        current_user,
        OrganizationRole.OWNER,
    )
    membership = session.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).first()
    if membership is None:
        raise ResourceNotFoundError("Organization member not found")
    if membership.role == OrganizationRole.OWNER or member_in.role == OrganizationRole.OWNER:
        raise ConflictError("Owner role can only be changed through ownership transfer")

    membership.role = member_in.role
    user = session.get(User, membership.user_id)
    if user is None:
        raise ResourceNotFoundError("User not found")
    session.add(membership)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=current_user.id,
        action="organization.member_role_changed",
        resource_type="organization_membership",
        resource_id=membership.id,
        details={"user_id": str(user.id), "role": member_in.role.value},
    )
    session.commit()
    session.refresh(membership)
    return OrganizationMemberPublic(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete("/{organization_id}/members/{membership_id}")
def remove_organization_member(
    *,
    organization_id: uuid.UUID,
    membership_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> dict[str, str]:
    actor_membership = require_organization_role(
        session,
        organization_id,
        current_user,
        OrganizationRole.ADMIN,
    )
    membership = session.exec(
        select(OrganizationMembership).where(
            OrganizationMembership.id == membership_id,
            OrganizationMembership.organization_id == organization_id,
        )
    ).first()
    if membership is None:
        raise ResourceNotFoundError("Organization member not found")
    if membership.role == OrganizationRole.OWNER:
        raise ConflictError("Organization owner cannot be removed")
    if ROLE_LEVEL[actor_membership.role] <= ROLE_LEVEL[membership.role]:
        raise PermissionDeniedError("You cannot remove a member with an equal role")

    removed_user_id = membership.user_id
    session.delete(membership)
    add_audit_log(
        session,
        organization_id=organization_id,
        actor_id=current_user.id,
        action="organization.member_removed",
        resource_type="organization_membership",
        resource_id=membership.id,
        details={"user_id": str(removed_user_id)},
    )
    session.commit()
    return {"message": "Organization member removed"}
