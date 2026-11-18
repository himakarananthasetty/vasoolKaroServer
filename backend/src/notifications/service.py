from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from src.core.errors import NotFound, ValidationError
from src.db.models import Notification, PushSubscription, User


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    receipt_id: uuid.UUID
    merchant_name: str
    cashback_cents: int
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MarkReadIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=100)


def list_notifications(db: Session, user: User, *, page: int, page_size: int) -> dict:
    stmt = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    unread = (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0
    )
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total, "unread_count": unread}


def mark_read(db: Session, user: User, ids: list[uuid.UUID]) -> int:
    res = db.execute(
        update(Notification)
        .where(
            Notification.id.in_(ids),
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)
    p256dh: str = Field(min_length=1, max_length=256)
    auth_key: str = Field(min_length=1, max_length=256)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("endpoint must be HTTPS")
        return v


def register_push(db: Session, user: User, body: PushSubscriptionIn) -> None:
    if not body.endpoint.startswith("https://"):
        raise ValidationError("endpoint must be HTTPS")
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing is not None:
        existing.user_id = user.id
        existing.p256dh = body.p256dh
        existing.auth_key = body.auth_key
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=body.endpoint,
                p256dh=body.p256dh,
                auth_key=body.auth_key,
            )
        )
    db.flush()


def delete_push(db: Session, user: User, endpoint: str) -> None:
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id))
    if sub is None:
        raise NotFound()
    db.delete(sub)
    db.flush()
