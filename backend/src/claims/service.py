from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.rate_limit import check_rate_limit
from src.core.config import get_settings
from src.core.errors import NotFound, RateLimited, ValidationError
from src.db.models import Notification, Offer, PushSubscription, Receipt, User, WalletLedger

logger = logging.getLogger("vasoolkaro.claims")

CARD_RE = re.compile(r"^[0-9]{4}$")

MAX_TOTAL = 10_000_000


class ReceiptSubmitIn(BaseModel):
    offer_id: uuid.UUID
    merchant_name: str = Field(min_length=2, max_length=80)
    purchase_date: date
    total_cents: int = Field(gt=0, le=MAX_TOTAL)
    receipt_number: str = Field(min_length=3, max_length=40)
    card_last4: str | None = Field(default=None, pattern="^[0-9]{4}$")

    @field_validator("merchant_name", "receipt_number")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class ReceiptOut(BaseModel):
    id: uuid.UUID
    offer_id: uuid.UUID
    offer_title: str | None = None
    merchant_name: str
    purchase_date: date
    total_cents: int
    receipt_number: str
    card_last4: str | None
    status: str
    cashback_cents: int
    rejection_reason: str | None
    submitted_at: datetime
    decided_at: datetime | None

    model_config = {"from_attributes": True}


def compute_fingerprint(
    merchant_name: str,
    purchase_date: date,
    total_cents: int,
    receipt_number: str,
    card_last4: str | None,
) -> str:
    normalized = "|".join(
        [
            merchant_name.strip().lower(),
            purchase_date.isoformat(),
            str(total_cents),
            receipt_number.strip().lower(),
            (card_last4 or "").strip(),
        ]
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def submit_receipt(db: Session, user: User, body: ReceiptSubmitIn) -> Receipt:
    """Single transaction: validate → lock offer → eligibility → insert receipt
    (+ wallet credit + notification on approval) → rate-limit row."""
    settings = get_settings()
    now = datetime.now(UTC)

    if body.purchase_date > now.date():
        raise ValidationError("Purchase date cannot be in the future.")
    if body.merchant_name != body.merchant_name.strip() or len(body.merchant_name) < 2:
        raise ValidationError("Invalid merchant name.")
    if not (3 <= len(body.receipt_number.strip()) <= 40):
        raise ValidationError("Invalid receipt number.")

    # Offer: lock the row for the budget check + update.
    offer = db.execute(select(Offer).where(Offer.id == body.offer_id).with_for_update()).scalar_one_or_none()
    if offer is None:
        raise NotFound(message="Offer not found.")

    def reject(reason: str) -> Receipt:
        receipt = Receipt(
            user_id=user.id,
            offer_id=offer.id,
            merchant_name=body.merchant_name,
            purchase_date=body.purchase_date,
            total_cents=body.total_cents,
            receipt_number=body.receipt_number.strip(),
            card_last4=body.card_last4,
            fingerprint=compute_fingerprint(
                body.merchant_name,
                body.purchase_date,
                body.total_cents,
                body.receipt_number,
                body.card_last4,
            ),
            status="REJECTED",
            cashback_cents=0,
            rejection_reason=reason,
            decided_at=now,
        )
        db.add(receipt)
        db.flush()
        _notify(db, user, receipt)
        return receipt

    # 1. rate limit (12 / user / rolling hour) — checked within the TX
    try:
        check_rate_limit(
            db,
            action="receipt_submit",
            subject_kind="user",
            subject_id=str(user.id),
            limit=settings.receipt_submit_rate_limit,
            window_seconds=settings.receipt_submit_window_seconds,
            error_factory=lambda wait: RateLimited("Too many receipt submissions.", retry_after_seconds=wait),
        )
    except RateLimited:
        # Rate-limit failures create no receipt row (existing behavior).
        raise

    # 2. eligibility checks, in documented order
    if not offer.active:
        return reject("offer_inactive")
    if now < offer.starts_at or now > offer.ends_at:
        return reject("outside_offer_window")
    if not (offer.starts_at.date() <= body.purchase_date <= offer.ends_at.date()):
        return reject("purchase_date_outside_offer")
    if body.merchant_name.strip().lower() != offer.merchant_name.strip().lower():
        return reject("merchant_name_mismatch")
    if body.total_cents < offer.min_purchase_cents:
        return reject("below_minimum_purchase")

    fingerprint = compute_fingerprint(
        body.merchant_name,
        body.purchase_date,
        body.total_cents,
        body.receipt_number,
        body.card_last4,
    )
    dup = db.scalar(select(Receipt.id).where(Receipt.fingerprint == fingerprint, Receipt.status != "REJECTED").limit(1))
    if dup is not None:
        return reject("duplicate_receipt")

    claim_count = (
        db.scalar(
            select(text("count(*)"))
            .select_from(Receipt)
            .where(
                Receipt.user_id == user.id,
                Receipt.offer_id == offer.id,
                Receipt.status.in_(["APPROVED", "PAID"]),
            )
        )
        or 0
    )
    if claim_count >= offer.per_user_limit:
        return reject("user_limit_reached")

    if offer.reserved_cents + offer.spent_cents + offer.cashback_cents > offer.budget_cents:
        return reject("offer_budget_exhausted")

    # 3. approve or flag for review: budget consumption + receipt + wallet credit
    #    High-value receipts (>= flag threshold) go to REVIEWING; an admin decides.
    needs_review = body.total_cents >= settings.receipt_review_threshold_cents
    offer.spent_cents += offer.cashback_cents
    receipt = Receipt(
        user_id=user.id,
        offer_id=offer.id,
        merchant_name=body.merchant_name,
        purchase_date=body.purchase_date,
        total_cents=body.total_cents,
        receipt_number=body.receipt_number.strip(),
        card_last4=body.card_last4,
        fingerprint=fingerprint,
        status="REVIEWING" if needs_review else "APPROVED",
        cashback_cents=offer.cashback_cents,
        decided_at=None if needs_review else now,
    )
    db.add(receipt)
    db.flush()

    if not needs_review:
        db.add(
            WalletLedger(
                user_id=user.id,
                entry_type="RECEIPT_CASHBACK",
                amount_cents=offer.cashback_cents,
                source_id=receipt.id,
                reference_key=f"receipt:{receipt.id}",
                description=f"{offer.merchant_name} cashback",
            )
        )
        _notify(db, user, receipt)

    # Duplicate race (concurrent identical claim) → friendly rejection.
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        db.begin()
        return _friendly_duplicate(db, user, offer, body)

    return receipt


def _friendly_duplicate(db: Session, user: User, offer: Offer, body: ReceiptSubmitIn) -> Receipt:
    """After a rollback from a fingerprint race, write the REJECTED duplicate row."""
    receipt = Receipt(
        user_id=user.id,
        offer_id=offer.id,
        merchant_name=body.merchant_name,
        purchase_date=body.purchase_date,
        total_cents=body.total_cents,
        receipt_number=body.receipt_number.strip(),
        card_last4=body.card_last4,
        fingerprint=compute_fingerprint(
            body.merchant_name,
            body.purchase_date,
            body.total_cents,
            body.receipt_number,
            body.card_last4,
        )
        + ":dup",
        status="REJECTED",
        cashback_cents=0,
        rejection_reason="duplicate_receipt",
        decided_at=datetime.now(UTC),
    )
    db.add(receipt)
    db.flush()
    _notify(db, user, receipt)
    return receipt


def _notify(db: Session, user: User, receipt: Receipt) -> None:
    if not user.notify_receipts:
        return
    kind = "RECEIPT_APPROVED" if receipt.status == "APPROVED" else "RECEIPT_REJECTED"
    db.add(
        Notification(
            user_id=user.id,
            kind=kind,
            receipt_id=receipt.id,
            merchant_name=receipt.merchant_name,
            cashback_cents=receipt.cashback_cents,
        )
    )
    # Dispatch queued pushes for this user; failures must not break the claim TX.
    try:
        _dispatch_pending_push(db, user.id)
    except Exception:  # noqa: BLE001
        logger.warning("push dispatch failed for user %s", user.id, exc_info=True)


def _dispatch_pending_push(db: Session, user_id: uuid.UUID) -> None:
    """Best-effort inline push for unread notifications; pushed_at prevents re-sends."""
    pending = db.scalars(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.pushed_at.is_(None),
        )
    ).all()
    if not pending:
        return
    subs = db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id)).all()
    for n in pending:
        n.pushed_at = datetime.now(UTC)  # mark attempted even if no subs / send fails
    if not subs:
        return
    from src.internal.router import _web_push_sender  # noqa: PLC0415 (avoids import cycle)

    for n in pending:
        for sub in subs:
            _web_push_sender(
                sub,
                {
                    "title": "Receipt update",
                    "body": f"{n.merchant_name}: {n.kind.lower().replace('_', ' ')}",
                    "notification_id": str(n.id),
                },
            )


def list_receipts(db: Session, user: User, *, page: int, page_size: int, status: str | None) -> dict:
    stmt = select(Receipt).where(Receipt.user_id == user.id)
    if status:
        stmt = stmt.where(Receipt.status == status)
    stmt = stmt.order_by(Receipt.submitted_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total}


def get_receipt(db: Session, user: User, receipt_id: uuid.UUID) -> Receipt:
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.user_id == user.id))
    if receipt is None:
        raise NotFound()
    return receipt
