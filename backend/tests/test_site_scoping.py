"""Groundwork for BR-03: users only reach the sites they are assigned to."""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.permissions import Role
from app.core.scoping import accessible_site_ids, ensure_site_access, scope_to_user_sites
from app.models import Site, User
from tests.conftest import bearer, login


@pytest.fixture
def three_sites(make_site: Callable[..., Site]) -> tuple[Site, Site, Site]:
    return make_site("COL-07"), make_site("KDY-02"), make_site("GAL-11")


@pytest.mark.parametrize(
    "role", [Role.SITE_ENGINEER, Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.CLIENT]
)
def test_scoped_roles_only_list_assigned_sites(
    api: TestClient, make_user: Callable[..., User], three_sites: tuple[Site, Site, Site], role: Role
) -> None:
    colombo, kandy, _galle = three_sites
    user = make_user(role, sites=[colombo, kandy])

    response = api.get("/api/v1/sites", headers=bearer(login(api, user.email)))

    assert [s["code"] for s in response.json()] == ["COL-07", "KDY-02"]


@pytest.mark.parametrize("role", [Role.ADMIN, Role.PROCUREMENT_OFFICER])
def test_company_wide_roles_see_every_active_site(
    api: TestClient, make_user: Callable[..., User], three_sites: tuple[Site, Site, Site],
    make_site: Callable[..., Site], role: Role,
) -> None:  # fmt: skip
    make_site("OLD-99", active=False)
    user = make_user(role)

    codes = [s["code"] for s in api.get("/api/v1/sites", headers=bearer(login(api, user.email))).json()]

    assert set(codes) >= {"COL-07", "KDY-02", "GAL-11"}
    assert "OLD-99" not in codes


def test_unassigned_engineer_sees_nothing(
    api: TestClient, make_user: Callable[..., User], three_sites: object
) -> None:
    user = make_user(Role.SITE_ENGINEER)

    assert api.get("/api/v1/sites", headers=bearer(login(api, user.email))).json() == []


def test_helpers_enforce_scope(
    db: Session, make_user: Callable[..., User], three_sites: tuple[Site, Site, Site]
) -> None:
    colombo, kandy, galle = three_sites
    engineer = make_user(Role.SITE_ENGINEER, sites=[colombo])
    procurement = make_user(Role.PROCUREMENT_OFFICER)

    assert accessible_site_ids(engineer) == {colombo.id}
    assert accessible_site_ids(procurement) is None

    ensure_site_access(engineer, colombo.id)
    with pytest.raises(NotFoundError):
        ensure_site_access(engineer, galle.id)  # 404, not 403: existence is not revealed
    ensure_site_access(procurement, galle.id)

    stmt = scope_to_user_sites(select(Site.code), Site.id, engineer)
    assert list(db.scalars(stmt).all()) == ["COL-07"]
    unscoped = scope_to_user_sites(select(Site.code), Site.id, procurement)
    assert {"COL-07", "KDY-02", "GAL-11"} <= set(db.scalars(unscoped).all())
    assert kandy.id not in accessible_site_ids(engineer)  # type: ignore[operator]
