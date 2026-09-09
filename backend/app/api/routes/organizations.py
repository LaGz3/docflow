from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Organization,
    OrganizationCreate,
    OrganizationMembership,
    OrganizationPublic,
    OrganizationRole,
    OrganizationsPublic,
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
        raise HTTPException(
            status_code=409,
            detail="Organization slug already exists",
        )

    organization = Organization.model_validate(organization_in)
    session.add(organization)
    session.flush()

    membership = OrganizationMembership(
        organization_id=organization.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
    )
    session.add(membership)
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
