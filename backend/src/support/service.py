from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.errors import ValidationError
from src.db.models import SupportRequest, User

TOPICS = ("ACCOUNT", "CASHBACK", "OFFERS", "OTHER")


class SupportCreateIn(BaseModel):
    """Field allow-list — ownership and status are server-controlled."""

    topic: str
    message: str = Field(min_length=10, max_length=2000)

    @classmethod
    def clean_topic(cls, v: str) -> str:
        return v.strip().upper()


class SupportOut(BaseModel):
    id: uuid.UUID
    topic: str
    message: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def create_request(db: Session, user: User, topic: str, message: str) -> SupportRequest:
    topic = (topic or "").strip().upper()
    if topic not in TOPICS:
        raise ValidationError(f"topic must be one of: {list(TOPICS)}")
    message = message.strip()
    if not (10 <= len(message) <= 2000):
        raise ValidationError("message must be 10-2000 characters.")
    row = SupportRequest(user_id=user.id, topic=topic, message=message)
    db.add(row)
    db.flush()
    return row


def list_requests(db: Session, user: User, *, page: int, page_size: int) -> dict:
    stmt = select(SupportRequest).where(SupportRequest.user_id == user.id).order_by(SupportRequest.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total}
