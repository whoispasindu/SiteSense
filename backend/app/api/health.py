import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import engine

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    database: str


@router.get("/health")
def health() -> HealthResponse:
    """Reports whether the API is up and whether it can reach the database."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        logger.warning("Health check could not reach the database")
        database = "unavailable"
    return HealthResponse(status="ok", database=database)
