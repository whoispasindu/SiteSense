"""Progress claims (BR-08), variation orders (BR-09), the client's variation decisions, the admin limit.

Claims: the QS creates and records payment (``claims:manage``), the PM approves (``claims:approve``);
both read (``cost:read``). Variations: the PM and QS raise and read (``variations:manage``), the QS
prices (``variations:price``), the PM decides (``variations:approve``), the client decides on the
ones sent to them (``variations:client_decide``) through a view with no internal costs. Every
project route goes through the project's site scope (404 outside it).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, Meta, require_permission
from app.core.permissions import Permission
from app.models import User
from app.schemas.contract import (
    ClaimCheckOut,
    ClaimDecisionIn,
    ClaimIn,
    ClaimOut,
    ClaimPaymentIn,
    ClaimsOverview,
    ClientDecisionIn,
    ClientVariationOut,
    CostOverview,
    ProjectLimitIn,
    ProjectLimitOut,
    VariationDecisionIn,
    VariationIn,
    VariationListOut,
    VariationOut,
    VariationPriceIn,
    WithdrawIn,
)
from app.services import claim_service, cost_service, variation_service

router = APIRouter(tags=["claims and variations"])

CostReader = Annotated[User, Depends(require_permission(Permission.COST_READ))]
ClaimManager = Annotated[User, Depends(require_permission(Permission.COST_READ, Permission.CLAIMS_MANAGE))]
ClaimApprover = Annotated[User, Depends(require_permission(Permission.COST_READ, Permission.CLAIMS_APPROVE))]
VariationManager = Annotated[User, Depends(require_permission(Permission.VARIATIONS_MANAGE))]
VariationPricer = Annotated[
    User, Depends(require_permission(Permission.VARIATIONS_MANAGE, Permission.VARIATIONS_PRICE))
]
VariationApprover = Annotated[
    User, Depends(require_permission(Permission.VARIATIONS_MANAGE, Permission.VARIATIONS_APPROVE))
]
Client = Annotated[User, Depends(require_permission(Permission.CLIENT_PORTAL))]
ClientDecider = Annotated[
    User, Depends(require_permission(Permission.CLIENT_PORTAL, Permission.VARIATIONS_CLIENT_DECIDE))
]
LimitAdmin = Annotated[User, Depends(require_permission(Permission.VARIATION_LIMITS_MANAGE))]


# --- Cost & claims overview ------------------------------------------------------------------------------


@router.get("/cost/overview", response_model=CostOverview)
def cost_overview(user: CostReader, db: DbSession) -> CostOverview:
    """Every project on the caller's sites with its forecast and claims, and what waits for the caller."""
    return cost_service.overview(db, user)


# --- Progress claims ------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/claims", response_model=ClaimsOverview)
def project_claims(project_id: uuid.UUID, user: CostReader, db: DbSession) -> ClaimsOverview:
    return claim_service.overview(db, user, project_id)


@router.post("/projects/{project_id}/claims/check", response_model=ClaimCheckOut)
def check_claim(project_id: uuid.UUID, body: ClaimIn, user: ClaimManager, db: DbSession) -> ClaimCheckOut:
    """BR-08 for a draft claim: the calculation and anything that stops it, nothing saved."""
    return claim_service.check(db, user, project_id, body)


@router.post("/projects/{project_id}/claims", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
def create_claim(
    project_id: uuid.UUID, body: ClaimIn, user: ClaimManager, db: DbSession, meta: Meta
) -> ClaimOut:
    claim = claim_service.create(db, user, project_id, body, meta=meta)
    return claim_service.claim_out(claim, user)


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: uuid.UUID, user: CostReader, db: DbSession) -> ClaimOut:
    return claim_service.claim_out(claim_service.get_claim(db, user, claim_id), user)


@router.post("/claims/{claim_id}/decision", response_model=ClaimOut)
def decide_claim(
    claim_id: uuid.UUID, body: ClaimDecisionIn, user: ClaimApprover, db: DbSession, meta: Meta
) -> ClaimOut:
    return claim_service.claim_out(claim_service.decide(db, user, claim_id, body, meta=meta), user)


@router.post("/claims/{claim_id}/payment", response_model=ClaimOut)
def record_payment(
    claim_id: uuid.UUID, body: ClaimPaymentIn, user: ClaimManager, db: DbSession, meta: Meta
) -> ClaimOut:
    return claim_service.claim_out(claim_service.record_payment(db, user, claim_id, body, meta=meta), user)


# --- Variation orders -----------------------------------------------------------------------------------


@router.get("/projects/{project_id}/variations", response_model=VariationListOut)
def project_variations(project_id: uuid.UUID, user: VariationManager, db: DbSession) -> VariationListOut:
    return variation_service.list_variations(db, user, project_id)


@router.post(
    "/projects/{project_id}/variations", response_model=VariationOut, status_code=status.HTTP_201_CREATED
)
def raise_variation(
    project_id: uuid.UUID, body: VariationIn, user: VariationManager, db: DbSession, meta: Meta
) -> VariationOut:
    variation = variation_service.raise_variation(db, user, project_id, body, meta=meta)
    return variation_service.variation_out(db, variation, user)


@router.get("/variations/{variation_id}", response_model=VariationOut)
def get_variation(variation_id: uuid.UUID, user: VariationManager, db: DbSession) -> VariationOut:
    return variation_service.variation_out(db, variation_service.get_variation(db, user, variation_id), user)


@router.post("/variations/{variation_id}/price", response_model=VariationOut)
def price_variation(
    variation_id: uuid.UUID, body: VariationPriceIn, user: VariationPricer, db: DbSession, meta: Meta
) -> VariationOut:
    variation = variation_service.price(db, user, variation_id, body, meta=meta)
    return variation_service.variation_out(db, variation, user)


@router.post("/variations/{variation_id}/revision", response_model=VariationOut)
def revise_variation(
    variation_id: uuid.UUID, body: VariationIn, user: VariationManager, db: DbSession, meta: Meta
) -> VariationOut:
    variation = variation_service.revise(db, user, variation_id, body, meta=meta)
    return variation_service.variation_out(db, variation, user)


@router.post("/variations/{variation_id}/decision", response_model=VariationOut)
def decide_variation(
    variation_id: uuid.UUID, body: VariationDecisionIn, user: VariationApprover, db: DbSession, meta: Meta
) -> VariationOut:
    variation = variation_service.decide(db, user, variation_id, body, meta=meta)
    return variation_service.variation_out(db, variation, user)


@router.post("/variations/{variation_id}/withdraw", response_model=VariationOut)
def withdraw_variation(
    variation_id: uuid.UUID, body: WithdrawIn, user: VariationManager, db: DbSession, meta: Meta
) -> VariationOut:
    variation = variation_service.withdraw(db, user, variation_id, body, meta=meta)
    return variation_service.variation_out(db, variation, user)


# --- The client -----------------------------------------------------------------------------------------


@router.get("/client/variations", response_model=list[ClientVariationOut])
def client_variations(user: Client, db: DbSession) -> list[ClientVariationOut]:
    """Variations sent to the client on their projects, without internal costs."""
    return variation_service.client_list(db, user)


@router.get("/client/variations/{variation_id}", response_model=ClientVariationOut)
def client_variation(variation_id: uuid.UUID, user: Client, db: DbSession) -> ClientVariationOut:
    return variation_service.client_get(db, user, variation_id)


@router.post("/variations/{variation_id}/client-decision", response_model=ClientVariationOut)
def client_decision(
    variation_id: uuid.UUID, body: ClientDecisionIn, user: ClientDecider, db: DbSession, meta: Meta
) -> ClientVariationOut:
    """TC-10: the client approves (the contract, budget and programme change) or queries."""
    return variation_service.client_decide(db, user, variation_id, body, meta=meta)


# --- Company Admin: BR-09 limit -------------------------------------------------------------------------


@router.get("/admin/variation-limits", response_model=list[ProjectLimitOut])
def variation_limits(_admin: LimitAdmin, db: DbSession) -> list[ProjectLimitOut]:
    return variation_service.list_limits(db)


@router.put("/admin/projects/{project_id}/variation-limit", response_model=ProjectLimitOut)
def set_variation_limit(
    project_id: uuid.UUID, body: ProjectLimitIn, admin: LimitAdmin, db: DbSession, meta: Meta
) -> ProjectLimitOut:
    return variation_service.set_limit(db, admin, project_id, body, meta=meta)
