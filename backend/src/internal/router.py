from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.db import get_db
from src.core.errors import NotFound, Unauthorized
from src.internal import push_service

router = APIRouter(prefix="/internal", tags=["internal"])


class PushDispatchIn(BaseModel):
    notification_id: uuid.UUID


@router.post("/push/dispatch")
def push_dispatch(
    body: PushDispatchIn,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    expected = f"Bearer {get_settings().internal_service_token}"
    if authorization != expected:
        raise Unauthorized()
    result = push_service.dispatch_notification_push(
        db, body.notification_id, sender=_web_push_sender
    )
    db.commit()
    return result


def _web_push_sender(subscription, payload: dict) -> int:
    """Real Web Push adapter (pywebpush) when installed and VAPID configured;
    otherwise a no-op that reports success. Same interface for tests."""
    settings = get_settings()
    if not (settings.push_vapid_private_key and settings.push_vapid_public_key):
        return 200
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        return 200
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth_key},
            },
            data=__import__("json").dumps(payload),
            vapid_private_key=settings.push_vapid_private_key,
            vapid_claims={"sub": settings.push_vapid_subject},
        )
        return 200
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 500
