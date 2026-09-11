import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.security import CurrentUser, current_user, platform_admins
from app.schemas.settings import AccessModelEntry, WhoAmI

router = APIRouter(prefix="/access-model", tags=["access"])

_DATA = Path(__file__).resolve().parents[2] / "seed" / "data" / "access_model.json"


@lru_cache
def _entries() -> tuple[AccessModelEntry, ...]:
    return tuple(AccessModelEntry(title=e["t"], detail=e["d"]) for e in json.loads(_DATA.read_text()))


@router.get("", response_model=list[AccessModelEntry])
async def get_access_model(_: CurrentUser = Depends(current_user)) -> list[AccessModelEntry]:
    """The written positioning of the authorization model, served rather than hardcoded in the UI."""
    return list(_entries())


@router.get("/me", response_model=WhoAmI)
async def whoami(user: CurrentUser = Depends(current_user)) -> WhoAmI:
    return WhoAmI(
        email=user.email,
        groups=list(user.groups),
        platform_admin=user.is_platform_admin,
        platform_admin_count=len(platform_admins()),
    )
