"""Identity and project-scoped authorization.

Authentication is not authorization: being signed in gets you the app, not the data. Every read
and write below is evaluated here, at the API layer - never hidden in the UI.

SSO (OIDC) is the only identity provider in production. The service sits behind an SSO proxy
that authenticates the person and forwards who they are on headers; `auth_mode` says whether
those headers are trusted outright (local dev) or only when the proxy proves it sent them
(`trusted-proxy`). This module is the single place that changes when OIDC is validated in-process.
"""

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models.project import Project, ProjectAccess

ROLE_RANK = {"viewer": 1, "contributor": 2, "admin": 3}


def platform_admins() -> frozenset[str]:
    """The audited operator set. Configured, never granted through the API."""
    return frozenset(email.lower() for email in get_settings().platform_admins)


@dataclass
class CurrentUser:
    email: str
    groups: tuple[str, ...] = ()

    @property
    def is_platform_admin(self) -> bool:
        return self.email.lower() in platform_admins()

    @property
    def principals(self) -> set[str]:
        """Everything a grant can name this caller by: their email and each SSO group."""
        return {self.email, *self.groups}


def _proxy_verified(presented: str | None) -> bool:
    secret = get_settings().proxy_shared_secret
    if secret is None or not presented:
        return False
    return hmac.compare_digest(presented.encode(), secret.get_secret_value().encode())


async def current_user(
    x_shiftleft_user: str | None = Header(default=None),
    x_shiftleft_groups: str | None = Header(default=None),
    x_shiftleft_proxy_secret: str | None = Header(default=None),
) -> CurrentUser:
    settings = get_settings()
    if settings.auth_mode == "trusted-proxy" and not _proxy_verified(x_shiftleft_proxy_secret):
        # The identity headers did not come through the SSO proxy, so they prove nothing.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No SSO session")
    email = (x_shiftleft_user or "").strip()
    if not email:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No SSO session")
    groups = tuple(g.strip() for g in (x_shiftleft_groups or "").split(",") if g.strip())
    return CurrentUser(email=email, groups=groups)


async def require_platform_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """For service-wide configuration that belongs to no single project, such as connectors.

    A 403 rather than a 404: the resource is visible to every signed-in user, only changing it
    is restricted, so there is nothing to hide about its existence.
    """
    if not user.is_platform_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a platform admin can change service-wide configuration"
        )
    return user


async def effective_role(
    session: AsyncSession, user: CurrentUser, project_id: str
) -> str | None:
    if user.is_platform_admin:
        return "admin"
    roles = (
        await session.execute(
            select(ProjectAccess.role).where(
                ProjectAccess.project_id == project_id,
                ProjectAccess.principal.in_(user.principals),
            )
        )
    ).scalars().all()
    if not roles:
        return None
    return max(roles, key=lambda r: ROLE_RANK.get(r, 0))


def require(minimum: str):
    """Dependency factory: the caller needs at least `minimum` on the project in the path."""
    if minimum not in ROLE_RANK:
        raise ValueError(f"Unknown role {minimum!r}")

    async def _dep(
        project_id: str,
        user: CurrentUser = Depends(current_user),
        session: AsyncSession = Depends(get_session),
    ) -> Project:
        project = await session.get(Project, project_id)
        if project is None or project.archived_at is not None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        role = await effective_role(session, user, project_id)
        if role is None or ROLE_RANK.get(role, 0) < ROLE_RANK[minimum]:
            # Deliberately a 404: an unauthorized caller learns nothing about what exists.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
        return project

    return _dep


async def visible_projects(session: AsyncSession, user: CurrentUser) -> list[Project]:
    query = select(Project).where(Project.archived_at.is_(None)).order_by(Project.name)
    if not user.is_platform_admin:
        granted = select(ProjectAccess.project_id).where(ProjectAccess.principal.in_(user.principals))
        query = query.where(Project.id.in_(granted))
    return list((await session.execute(query)).scalars().all())
