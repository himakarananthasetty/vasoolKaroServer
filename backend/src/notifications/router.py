from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.core.errors import ValidationError
from src.db.models import User
from src.notifications import service
from src.notifications.service import MarkReadIn, PushSubscriptionIn

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_notifications(db, user, page=page, page_size=page_size)
    return {
        "items": [service.NotificationOut.model_validate(r) for r in result["items"]],
        "page": result["page"],
        "page_size": result["page_size"],
        "total": result["total"],
        "unread_count": result["unread_count"],
    }


@router.patch("/notifications/read")
def mark_read(
    body: MarkReadIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = service.mark_read(db, user, body.ids)
    db.commit()
    return {"updated": updated}


@router.post("/push/subscriptions", status_code=204)
def register_push(
    body: PushSubscriptionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.register_push(db, user, body)
    db.commit()


@router.delete("/push/subscriptions", status_code=204)
def delete_push(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raise ValidationError("Endpoint path is required: use the endpoint query parameter.")


@router.delete("/push/subscriptions/{endpoint:path}", status_code=204)
def delete_push_by_endpoint(
    endpoint: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service.delete_push(db, user, endpoint)
    db.commit()
