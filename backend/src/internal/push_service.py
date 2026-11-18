from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.errors import NotFound, ValidationError
from src.db.models import PushSubscription, User


def dispatch_notification_push(db: Session, notification_id: uuid.UUID, *, sender) -> dict:
    """Send Web Push for one notification. `sender` is an injectable callable
    (subscription, payload) -> status_code, so tests and VAPID-less dev run the
    same code path with a no-op adapter."""
    notification = db.get(Notification := __import__(
        "src.db.models", fromlist=["Notification"]
    ).Notification, notification_id)
    if notification is None:
        raise NotFound()
    if notification.pushed_at is not None:
        return {"sent": 0, "removed": 0, "failed": 0, "skipped": True}

    subs = db.scalars(
        select(PushSubscription).where(PushSubscription.user_id == notification.user_id)
    ).all()

    titles = {
        "RECEIPT_APPROVED": "Receipt approved",
        "RECEIPT_REJECTED": "Receipt update",
    }
    payload = {
        "title": titles.get(notification.kind, "VasoolKaro"),
        "body": f"Your receipt from {notification.merchant_name} was "
        f"{'approved' if notification.kind == 'RECEIPT_APPROVED' else 'reviewed'}. Open the app for details.",
        "url": "/notifications",
    }

    sent = removed = failed = 0
    for sub in subs:
        try:
            status = sender(sub, payload)
        except Exception:
            failed += 1
            continue
        if status in (404, 410):
            db.delete(sub)
            removed += 1
        elif status == 200:
            sent += 1
        else:
            failed += 1

    notification.pushed_at = datetime.now(UTC)
    db.flush()
    return {"sent": sent, "removed": removed, "failed": failed, "skipped": False}
