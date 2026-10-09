"""The access model itself: what each role can and, more importantly, cannot do."""

import pytest

from app.core.permissions import (
    MFA_ROLES,
    ROLE_LABELS,
    ROLE_PERMISSIONS,
    SITE_SCOPED_ROLES,
    Permission,
    Role,
    has_permission,
)


def test_every_role_has_a_label_and_a_permission_set() -> None:
    assert set(ROLE_LABELS) == set(Role)
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_only_admin_manages_users_sites_and_reads_audit() -> None:
    for permission in (Permission.USERS_MANAGE, Permission.SITES_MANAGE, Permission.AUDIT_READ):
        assert {role for role in Role if has_permission(role, permission)} == {Role.ADMIN}


def test_admin_has_no_project_approvals() -> None:
    approvals = {
        Permission.MATERIALS_APPROVE_QS,
        Permission.MATERIALS_APPROVE_PM,
        Permission.CLAIMS_APPROVE,
        Permission.VARIATIONS_CLIENT_DECIDE,
    }
    assert not approvals & ROLE_PERMISSIONS[Role.ADMIN]


def test_tc01_site_engineer_cannot_approve_material_requests() -> None:
    assert not has_permission(Role.SITE_ENGINEER, Permission.MATERIALS_APPROVE_QS)
    assert not has_permission(Role.SITE_ENGINEER, Permission.MATERIALS_APPROVE_PM)
    assert has_permission(Role.SITE_ENGINEER, Permission.MATERIALS_REQUEST)


def test_qs_and_pm_approve_at_different_levels() -> None:
    assert has_permission(Role.QUANTITY_SURVEYOR, Permission.MATERIALS_APPROVE_QS)
    assert not has_permission(Role.QUANTITY_SURVEYOR, Permission.MATERIALS_APPROVE_PM)
    assert has_permission(Role.PROJECT_MANAGER, Permission.MATERIALS_APPROVE_PM)


@pytest.mark.parametrize(
    "permission",
    [Permission.COST_READ, Permission.BOQ_MANAGE, Permission.MATERIALS_READ, Permission.PROJECTS_READ,
     Permission.RISK_READ, Permission.REPORTS_READ, Permission.DASHBOARD_VIEW],
)  # fmt: skip
def test_client_never_gets_internal_permissions(permission: Permission) -> None:
    assert not has_permission(Role.CLIENT, permission)


def test_only_procurement_issues_purchase_orders() -> None:
    assert {r for r in Role if has_permission(r, Permission.PURCHASE_ORDERS_MANAGE)} == {
        Role.PROCUREMENT_OFFICER
    }


def test_site_scoping_covers_field_roles_and_clients() -> None:
    assert Role.SITE_ENGINEER in SITE_SCOPED_ROLES
    assert Role.CLIENT in SITE_SCOPED_ROLES
    assert Role.ADMIN not in SITE_SCOPED_ROLES
    assert Role.PROCUREMENT_OFFICER not in SITE_SCOPED_ROLES


def test_mfa_roles_match_the_guide() -> None:
    assert {Role.PROJECT_MANAGER, Role.PROCUREMENT_OFFICER} <= MFA_ROLES
