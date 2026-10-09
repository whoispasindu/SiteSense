import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.report import NotificationList, NotificationOut
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(user: CurrentUser, db: DbSession) -> NotificationList:
    """The caller's own notifications, newest first, with the unread count."""
    return notification_service.list_for(db, user)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DbSession) -> NotificationOut:
    return notification_service.mark_read(db, user, notification_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(user: CurrentUser, db: DbSession) -> None:
    notification_service.mark_all_read(db, user)
