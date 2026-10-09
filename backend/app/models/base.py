from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Predictable constraint names, so Alembic can later find and drop or alter them by name
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every SQLAlchemy model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
