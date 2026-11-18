"""Rate limiting backed by rate_limit_events (DB-backed sliding window)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.core.errors import RateLimited
from src.db.models import RateLimitEvent


def check_rate_limit(
    db: Session,
    *,
    action: str,
    subject_kind: str,
    subject_id: str,
    limit: int,
    window_seconds: int,
    error_factory=None,
) -> None:
    """Raise a RateLimited-style error when the subject exceeded `limit` in the
    window; otherwise record this attempt. The insert is committed by the caller."""
    now = datetime.now(UTC)
    window_start = now - timedelta(seconds=window_seconds)

    # opportunistic prune of old rows for this action
    db.execute(delete(RateLimitEvent).where(RateLimitEvent.action == action, RateLimitEvent.occurred_at < window_start))

    count = (
        db.scalar(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.action == action,
                RateLimitEvent.subject_kind == subject_kind,
                RateLimitEvent.subject_id == subject_id,
                RateLimitEvent.occurred_at >= window_start,
            )
        )
        or 0
    )

    if count >= limit:
        oldest = db.scalar(
            select(RateLimitEvent.occurred_at)
            .where(
                RateLimitEvent.action == action,
                RateLimitEvent.subject_kind == subject_kind,
                RateLimitEvent.subject_id == subject_id,
                RateLimitEvent.occurred_at >= window_start,
            )
            .order_by(RateLimitEvent.occurred_at.asc())
            .limit(1)
        )
        retry_after = (
            max(1, int((oldest + timedelta(seconds=window_seconds) - now).total_seconds())) if oldest else window_seconds
        )
        if error_factory is not None:
            raise error_factory(retry_after)
        raise RateLimited(retry_after_seconds=retry_after)

    db.add(RateLimitEvent(action=action, subject_kind=subject_kind, subject_id=subject_id, occurred_at=now))
