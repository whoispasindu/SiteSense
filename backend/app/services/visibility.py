"""Who may see rates and amounts, and the cost-free versions of responses for everyone else.

Site engineers (and clients) never receive contract values, BOQ rates, prices or totals: not in
the screen, not in the JSON. Every response that can carry them has a base schema without cost
fields and a subclass that adds them. Services build the full version; ``shape`` turns it into the
base version for viewers without ``rates:read``. Because the base schemas simply do not declare the
cost fields, nothing can leak by accident: unknown keys are dropped on the way in.
"""

from pydantic import BaseModel

from app.core.permissions import Permission, Role, has_permission
from app.models import User


def sees_rates(user: User) -> bool:
    return has_permission(Role(user.role), Permission.RATES_READ)


def shape[Full: BaseModel, Basic: BaseModel](user: User, full: Full, basic: type[Basic]) -> Full | Basic:
    """``full`` for viewers who may see rates; otherwise the same data in the cost-free schema."""
    if sees_rates(user):
        return full
    return basic.model_validate(full.model_dump())


def shape_all[Full: BaseModel, Basic: BaseModel](
    user: User, items: list[Full], basic: type[Basic]
) -> list[Full] | list[Basic]:
    if sees_rates(user):
        return items
    return [basic.model_validate(item.model_dump()) for item in items]
