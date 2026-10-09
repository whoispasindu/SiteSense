"""In-app notifications. Users only ever see and change their own."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import NotFoundError
from app.models import Notification, User
from app.schemas.report import NotificationList, NotificationOut

LIST_LIMIT = 30


@dataclass(frozen=True, slots=True)
class NewNotification:
    user_id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None = None
    project_id: uuid.UUID | None = None
    dedupe_key: str | None = None


def _safe_link(link: str | None) -> str | None:
    """In-app paths only: anything else is dropped rather than stored."""
    if link is None or not link.startswith("/") or link.startswith("//") or len(link) > 200:
        return None
    return link


def send(db: Session, items: list[NewNotification]) -> int:
    """Insert notifications; ones whose (user, dedupe_key) already exists are skipped.

    Returns how many were created. The caller commits.
    """
    created = 0
    now = clock.utcnow()
    for item in items:
        stmt = (
            insert(Notification)
            .values(
                id=uuid.uuid4(),
                user_id=item.user_id,
                kind=item.kind,
                title=item.title[:160],
                body=item.body[:500],
                link=_safe_link(item.link),
                project_id=item.project_id,
                dedupe_key=item.dedupe_key,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_user_dedupe_key")
            .returning(Notification.id)
        )
        if db.execute(stmt).first() is not None:
            created += 1
    return created


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind,
        title=n.title,
        body=n.body,
        link=n.link,
        created_at=n.created_at,
        read_at=n.read_at,
    )


def list_for(db: Session, user: User) -> NotificationList:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(LIST_LIMIT)
    ).all()
    unread = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    return NotificationList(items=[_out(n) for n in rows], unread=int(unread or 0))


def mark_read(db: Session, user: User, notification_id: uuid.UUID) -> NotificationOut:
    notification = db.get(Notification, notification_id)
    # Someone else's notification answers 404, exactly like a missing one.
    if notification is None or notification.user_id != user.id:
        raise NotFoundError("Notification not found.")
    if notification.read_at is None:
        notification.read_at = clock.utcnow()
        db.commit()
    return _out(notification)


def mark_all_read(db: Session, user: User) -> None:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=clock.utcnow())
    )
    db.commit()
