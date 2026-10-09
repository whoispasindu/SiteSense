from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.scoping import accessible_site_ids
from app.schemas.auth import SiteSummary
from app.services import user_service

router = APIRouter(tags=["sites"])


@router.get("/sites", response_model=list[SiteSummary])
def my_sites(user: CurrentUser, db: DbSession) -> list[SiteSummary]:
    """Active sites the current user may work on: assigned sites for scoped roles, all otherwise."""
    sites = user_service.list_sites(db, site_ids=accessible_site_ids(user), include_inactive=False)
    return [SiteSummary.model_validate(site) for site in sites]
