"""All models are imported here so Alembic sees every table when it autogenerates migrations.

When you add a model module, import it below, e.g. `from app.models.user import User`.
"""

from app.models.base import Base

__all__ = ["Base"]
