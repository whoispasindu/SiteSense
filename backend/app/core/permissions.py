"""Roles and permissions: the single source of truth for who may do what.

Endpoints never check role names directly. They require a *permission*, and this table maps
roles to permissions, so the whole access model can be read (and tested) in one place.
Permissions for modules built in later phases are declared now so menus and tests can use them.
"""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    PROJECT_MANAGER = "project_manager"
    QUANTITY_SURVEYOR = "quantity_surveyor"
    SITE_ENGINEER = "site_engineer"
    PROCUREMENT_OFFICER = "procurement_officer"
    CLIENT = "client"


ROLE_LABELS: dict[Role, str] = {
    Role.ADMIN: "Company Admin",
    Role.PROJECT_MANAGER: "Project Manager",
    Role.QUANTITY_SURVEYOR: "Quantity Surveyor",
    Role.SITE_ENGINEER: "Site Engineer",
    Role.PROCUREMENT_OFFICER: "Procurement Officer",
    Role.CLIENT: "Client",
}


class Permission(StrEnum):
    # Administration (Phase 1)
    USERS_MANAGE = "users:manage"
    SITES_MANAGE = "sites:manage"
    AUDIT_READ = "audit:read"
    # Core project data (Phases 2-3)
    DASHBOARD_VIEW = "dashboard:view"
    PROJECTS_READ = "projects:read"
    PROJECTS_MANAGE = "projects:manage"
    BOQ_MANAGE = "boq:manage"
    SCHEDULE_READ = "schedule:read"
    SCHEDULE_MANAGE = "schedule:manage"
    # Update a task's percent complete only (site engineers report progress; Phase 4 via reports).
    SCHEDULE_PROGRESS = "schedule:progress"
    # Site reports (Phase 4)
    REPORTS_CREATE = "reports:create"
    REPORTS_READ = "reports:read"
    # Materials and procurement (Phase 5)
    MATERIALS_REQUEST = "materials:request"
    MATERIALS_READ = "materials:read"
    MATERIALS_APPROVE_QS = "materials:approve_qs"
    MATERIALS_APPROVE_PM = "materials:approve_pm"
    PURCHASE_ORDERS_MANAGE = "purchase_orders:manage"
    SUPPLIERS_MANAGE = "suppliers:manage"
    # Risk, cost, claims, variations (Phases 6-10)
    RISK_READ = "risk:read"
    RISK_WHAT_IF = "risk:what_if"
    COST_READ = "cost:read"
    # Rates and amounts (contract values, BOQ rates, prices, totals). Site engineers and clients
    # never receive them: their API responses use cost-free schemas (``app.services.visibility``).
    RATES_READ = "rates:read"
    CLAIMS_MANAGE = "claims:manage"
    CLAIMS_APPROVE = "claims:approve"
    VARIATIONS_MANAGE = "variations:manage"  # raise and read variations (PM, QS)
    VARIATIONS_PRICE = "variations:price"  # the QS prices every variation (Phase 8)
    VARIATIONS_APPROVE = "variations:approve"  # the PM approves those that do not need the client
    # BR-09: the variation limit of each project. Company Admin only, audited.
    VARIATION_LIMITS_MANAGE = "variation_limits:manage"
    # Phase 9: the company's holidays (the working calendar). Company Admin only, audited.
    HOLIDAYS_MANAGE = "holidays:manage"
    # Client portal (Phase 12)
    CLIENT_PORTAL = "client:portal"
    VARIATIONS_CLIENT_DECIDE = "variations:client_decide"


P = Permission

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # Sets up the company. Deliberately has no project approvals (segregation of duties).
    Role.ADMIN: frozenset(
        {
            P.USERS_MANAGE,
            P.SITES_MANAGE,
            P.AUDIT_READ,
            P.DASHBOARD_VIEW,
            P.VARIATION_LIMITS_MANAGE,
            P.HOLIDAYS_MANAGE,
        }
    ),
    Role.PROJECT_MANAGER: frozenset(
        {
            P.DASHBOARD_VIEW,
            P.PROJECTS_READ,
            P.PROJECTS_MANAGE,
            P.SCHEDULE_READ,
            P.SCHEDULE_MANAGE,
            P.SCHEDULE_PROGRESS,
            P.REPORTS_READ,
            P.MATERIALS_READ,
            P.MATERIALS_REQUEST,
            P.MATERIALS_APPROVE_PM,
            P.RISK_READ,
            P.RISK_WHAT_IF,
            P.COST_READ,
            P.RATES_READ,
            P.CLAIMS_APPROVE,
            P.VARIATIONS_MANAGE,
            P.VARIATIONS_APPROVE,
        }
    ),
    Role.QUANTITY_SURVEYOR: frozenset(
        {
            P.DASHBOARD_VIEW,
            P.PROJECTS_READ,
            P.BOQ_MANAGE,
            P.SCHEDULE_READ,
            P.REPORTS_READ,
            P.MATERIALS_READ,
            P.MATERIALS_REQUEST,
            P.MATERIALS_APPROVE_QS,
            P.RISK_READ,
            P.COST_READ,
            P.RATES_READ,
            P.CLAIMS_MANAGE,
            P.VARIATIONS_MANAGE,
            P.VARIATIONS_PRICE,
        }
    ),
    Role.SITE_ENGINEER: frozenset(
        {
            P.DASHBOARD_VIEW,
            P.PROJECTS_READ,
            P.SCHEDULE_READ,
            P.SCHEDULE_PROGRESS,
            P.REPORTS_CREATE,
            P.REPORTS_READ,
            P.MATERIALS_REQUEST,
            P.MATERIALS_READ,
        }
    ),
    Role.PROCUREMENT_OFFICER: frozenset(
        {
            P.DASHBOARD_VIEW,
            P.PROJECTS_READ,
            P.MATERIALS_READ,
            P.PURCHASE_ORDERS_MANAGE,
            P.SUPPLIERS_MANAGE,
            P.RATES_READ,
        }
    ),
    # Read-only portal. Never receives internal cost permissions.
    Role.CLIENT: frozenset({P.CLIENT_PORTAL, P.VARIATIONS_CLIENT_DECIDE}),
}

# Roles that only see the sites they are assigned to (BR-03). Admin and procurement work
# company-wide: admin configures sites, procurement buys for every site.
SITE_SCOPED_ROLES: frozenset[Role] = frozenset(
    {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.SITE_ENGINEER, Role.CLIENT}
)

# Roles that must use two-step sign-in (Phase 13): everyone who sees costs or runs the company.
# Site engineers and clients may turn it on themselves.
MFA_ROLES: frozenset[Role] = frozenset(
    {Role.ADMIN, Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR, Role.PROCUREMENT_OFFICER}
)


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
