import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import DbSession, Meta, require_permission
from app.core.errors import ForbiddenError
from app.core.permissions import Permission, Role, has_permission
from app.models import User
from app.schemas.materials import (
    BoqItemOption,
    BoqItemOptionBasics,
    BudgetOut,
    DecisionIn,
    DeliveryIn,
    OrderResult,
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderDetailBasics,
    PurchaseOrderSummary,
    PurchaseOrderSummaryBasics,
    RequestCheck,
    RequestCreate,
    RequestDetail,
    RequestDetailBasics,
    RequestList,
    RequestListBasics,
    RequestSummary,
    RequestUpdate,
    ReturnedLineOut,
    RuleCheckBasics,
    RuleCheckOut,
    RuleResultOut,
    Status,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
)
from app.schemas.supplier import CriticalPathIn, CriticalPathOut, OnTimeOut, OutlookOut
from app.services import materials_service, procurement_service, project_service, supplier_service
from app.services.visibility import shape, shape_all

router = APIRouter(tags=["materials"])

Reader = Annotated[User, Depends(require_permission(Permission.MATERIALS_READ))]
Requester = Annotated[
    User, Depends(require_permission(Permission.MATERIALS_READ, Permission.MATERIALS_REQUEST))
]
Buyer = Annotated[
    User, Depends(require_permission(Permission.MATERIALS_READ, Permission.PURCHASE_ORDERS_MANAGE))
]
SupplierManager = Annotated[User, Depends(require_permission(Permission.SUPPLIERS_MANAGE))]
CostReader = Annotated[User, Depends(require_permission(Permission.COST_READ))]


def decider(user: Reader) -> User:
    """Requesters (to cancel) and approvers. Which decision is allowed is checked against the stage."""
    role = Role(user.role)
    deciding = (
        Permission.MATERIALS_REQUEST,
        Permission.MATERIALS_APPROVE_QS,
        Permission.MATERIALS_APPROVE_PM,
    )
    if not any(has_permission(role, p) for p in deciding):
        raise ForbiddenError()
    return user


Decider = Annotated[User, Depends(decider)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


# --- Material requests ---------------------------------------------------------------------------


# Responses with rates and amounts have a cost-free twin for viewers without ``rates:read``.
AnyRequestDetail = RequestDetail | RequestDetailBasics
AnyOrderDetail = PurchaseOrderDetail | PurchaseOrderDetailBasics


@router.get("/material-requests", response_model=RequestList | RequestListBasics)
def list_requests(
    user: Reader,
    db: DbSession,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    project_id: uuid.UUID | None = None,
    mine: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> RequestList | RequestListBasics:
    """Requests in the caller's scope, newest first, with pipeline counts by status."""
    result = materials_service.list_requests(
        db, user, status=status_filter, project_id=project_id, mine=mine, limit=limit, offset=offset
    )
    return shape(user, result, RequestListBasics)


@router.post("/material-requests/check", response_model=RuleCheckOut | RuleCheckBasics)
def check_request(body: RequestCheck, user: Requester, db: DbSession) -> RuleCheckOut | RuleCheckBasics:
    """Run the rules on a draft request without saving it (the form shows the result live)."""
    project = project_service.get_project(db, user, body.project_id)
    return shape(user, materials_service.check_request(db, user, project, body), RuleCheckBasics)


@router.post("/material-requests", response_model=AnyRequestDetail, status_code=status.HTTP_201_CREATED)
def create_request(body: RequestCreate, user: Requester, db: DbSession, meta: Meta) -> AnyRequestDetail:
    request = materials_service.create_request(db, user, body, meta=meta)
    return shape(user, materials_service.to_detail(db, request, user), RequestDetailBasics)


@router.get("/material-requests/{request_id}", response_model=AnyRequestDetail)
def get_request(request_id: uuid.UUID, user: Reader, db: DbSession) -> AnyRequestDetail:
    detail = materials_service.to_detail(db, materials_service.get_request(db, user, request_id), user)
    return shape(user, detail, RequestDetailBasics)


@router.patch("/material-requests/{request_id}", response_model=AnyRequestDetail)
def update_request(
    request_id: uuid.UUID, body: RequestUpdate, user: Requester, db: DbSession, meta: Meta
) -> AnyRequestDetail:
    request = materials_service.update_request(db, user, request_id, body, meta=meta)
    return shape(user, materials_service.to_detail(db, request, user), RequestDetailBasics)


@router.post("/material-requests/{request_id}/decision", response_model=AnyRequestDetail)
def decide(
    request_id: uuid.UUID, body: DecisionIn, user: Decider, db: DbSession, meta: Meta
) -> AnyRequestDetail:
    """Approve, reject, request a change or cancel. Who may decide depends on the request's stage."""
    request = materials_service.decide(db, user, request_id, body, meta=meta)
    return shape(user, materials_service.to_detail(db, request, user), RequestDetailBasics)


@router.get(
    "/projects/{project_id}/boq-items", response_model=list[BoqItemOption] | list[BoqItemOptionBasics]
)
def boq_items(
    project_id: uuid.UUID, user: Requester, db: DbSession
) -> list[BoqItemOption] | list[BoqItemOptionBasics]:
    """The project's BOQ items for the request form, with quantity already requested and remaining."""
    options = materials_service.boq_options(db, project_service.get_project(db, user, project_id))
    return shape_all(user, options, BoqItemOptionBasics)


@router.get("/projects/{project_id}/budget", response_model=BudgetOut)
def project_budget(project_id: uuid.UUID, user: CostReader, db: DbSession) -> BudgetOut:
    """Budget, approved, committed and spent cost per BOQ section."""
    return procurement_service.project_budget(db, project_service.get_project(db, user, project_id))


# --- Suppliers -----------------------------------------------------------------------------------


@router.get("/suppliers", response_model=list[SupplierOut])
def list_suppliers(user: Reader, db: DbSession, include_inactive: bool = False) -> list[SupplierOut]:
    show_all = include_inactive and has_permission(Role(user.role), Permission.SUPPLIERS_MANAGE)
    return [
        SupplierOut.model_validate(s)
        for s in procurement_service.list_suppliers(db, include_inactive=show_all)
    ]


@router.post("/suppliers", response_model=SupplierOut, status_code=status.HTTP_201_CREATED)
def create_supplier(body: SupplierIn, user: SupplierManager, db: DbSession, meta: Meta) -> SupplierOut:
    return SupplierOut.model_validate(procurement_service.create_supplier(db, user, body, meta=meta))


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(
    supplier_id: uuid.UUID, body: SupplierUpdate, user: SupplierManager, db: DbSession, meta: Meta
) -> SupplierOut:
    return SupplierOut.model_validate(
        procurement_service.update_supplier(db, user, supplier_id, body, meta=meta)
    )


# --- Purchase orders and deliveries --------------------------------------------------------------


@router.get("/purchase-orders/ready", response_model=list[RequestSummary])
def ready_to_order(user: Buyer, db: DbSession) -> list[RequestSummary]:
    """Approved requests waiting for a purchase order (BR-05: nothing else can be ordered)."""
    return [materials_service.to_summary(r) for r in procurement_service.ready_to_order(db)]


@router.get("/purchase-orders", response_model=list[PurchaseOrderSummary] | list[PurchaseOrderSummaryBasics])
def list_orders(
    user: Reader,
    db: DbSession,
    status_filter: Annotated[
        Literal["issued", "part_delivered", "delivered"] | None, Query(alias="status")
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[PurchaseOrderSummary] | list[PurchaseOrderSummaryBasics]:
    orders, _ = procurement_service.list_orders(db, user, status=status_filter, limit=limit, offset=offset)
    return shape_all(
        user, [procurement_service.to_po_summary(po) for po in orders], PurchaseOrderSummaryBasics
    )


@router.post("/purchase-orders", response_model=OrderResult, status_code=status.HTTP_201_CREATED)
def create_order(
    body: PurchaseOrderCreate, user: Buyer, db: DbSession, meta: Meta, response: Response
) -> OrderResult:
    """Issue an order for approved requests. Lines whose quote breaks BR-14 (more than 5% above the
    approved price) or BR-13 (the section's budget line) go back to the PM instead. 201 when an
    order was issued, 200 when every line went back."""
    outcome = procurement_service.create_order(db, user, body, meta=meta)
    if outcome.order is None:
        response.status_code = status.HTTP_200_OK
    return OrderResult(
        order=procurement_service.to_po_detail(outcome.order) if outcome.order is not None else None,
        returned=[
            ReturnedLineOut(
                request_id=item.request.id,
                number=item.request.number,
                unit_price=item.request.unit_price or Decimal(0),
                rules=[
                    RuleResultOut(rule=r.rule, severity=r.severity, message=r.message, facts=r.facts)
                    for r in item.results
                ],
            )
            for item in outcome.returned
        ],
    )


@router.get("/purchase-orders/{order_id}", response_model=AnyOrderDetail)
def get_order(order_id: uuid.UUID, user: Reader, db: DbSession) -> AnyOrderDetail:
    detail = procurement_service.to_po_detail(procurement_service.get_order(db, user, order_id))
    return shape(user, detail, PurchaseOrderDetailBasics)


@router.post(
    "/purchase-orders/{order_id}/deliveries",
    response_model=PurchaseOrderDetail,
    status_code=status.HTTP_201_CREATED,
)
def record_delivery(
    order_id: uuid.UUID, body: DeliveryIn, user: Buyer, db: DbSession, meta: Meta
) -> PurchaseOrderDetail:
    return procurement_service.to_po_detail(
        procurement_service.record_delivery(db, user, order_id, body, meta=meta)
    )


# --- Supplier on-time estimates and BR-12 (Phase 10) --------------------------------------------------


@router.get("/suppliers/{supplier_id}/on-time", response_model=OnTimeOut)
def supplier_on_time(
    supplier_id: uuid.UUID,
    user: Reader,
    db: DbSession,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    expected_delivery: Annotated[date | None, Query()] = None,
) -> OnTimeOut:
    """The chance the supplier's next order arrives on time, with its range and the deliveries behind it."""
    return supplier_service.on_time(db, user, supplier_id, project_id, expected_delivery)


@router.get("/projects/{project_id}/supplier-outlook", response_model=OutlookOut)
def supplier_outlook(
    project_id: uuid.UUID,
    user: Reader,
    db: DbSession,
    expected_delivery: Annotated[date | None, Query()] = None,
) -> OutlookOut:
    """Every active supplier for an order on this project, best first, and its critical-path requests."""
    return supplier_service.outlook(db, user, project_id, expected_delivery)


@router.get("/material-requests/{request_id}/critical-path", response_model=CriticalPathOut)
def request_critical_path(request_id: uuid.UUID, user: Reader, db: DbSession) -> CriticalPathOut:
    return supplier_service.critical_path(db, user, request_id)


@router.put("/material-requests/{request_id}/critical-path", response_model=CriticalPathOut)
def set_request_critical_path(
    request_id: uuid.UUID, data: CriticalPathIn, user: Reader, db: DbSession, meta: Meta
) -> CriticalPathOut:
    """Project manager only: mark the request critical or not critical, or hand it back to the programme."""
    return supplier_service.set_critical_path(db, user, request_id, data, meta=meta)
