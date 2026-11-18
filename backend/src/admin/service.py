from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from src.core.errors import Forbidden, NotFound, PayoutNotRequested, ReferenceInUse, ValidationError
from src.db.models import AuditLog, Offer, Payout, PayoutEntry, Receipt, SupportRequest, User, UserRole, WalletLedger

ADMIN_LEVELS = ("admin", "super_admin")
SUPER_ONLY = ("super_admin",)


class PayoutActionIn(BaseModel):
    pass


class CompletePayoutIn(BaseModel):
    payment_reference: str = Field(min_length=4, max_length=64)


class CancelPayoutIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


class SupportStatusIn(BaseModel):
    status: str = Field(pattern="^(OPEN|ANSWERED|CLOSED)$")


class ReverseReceiptIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


def _require_admin(db: Session, user: User, super_only: bool = False) -> str:
    roles = db.scalars(select(UserRole.role).where(UserRole.user_id == user.id)).all()
    allowed = SUPER_ONLY if super_only else ADMIN_LEVELS
    if not any(r in allowed for r in roles):
        raise Forbidden()
    return roles[0]


def audit(db: Session, actor: User, action: str, entity_type: str, entity_id: str, detail: dict) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_kind="admin",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=detail,
        )
    )


def spending_overview(db: Session) -> list[dict]:
    rows = db.execute(
        select(
            Offer.merchant_name,
            Offer.category,
            func.count(Receipt.id).label("claim_count"),
            func.coalesce(func.sum(Receipt.total_cents), 0).label("spend_cents"),
            func.coalesce(func.sum(Receipt.cashback_cents), 0).label("cashback_cents"),
        )
        .join(Receipt, Receipt.offer_id == Offer.id)
        .where(Receipt.status.in_(["APPROVED", "PAID"]))
        .group_by(Offer.merchant_name, Offer.category)
        .order_by(text("spend_cents DESC"))
    ).all()
    return [
        {
            "merchant_name": r.merchant_name,
            "category": r.category,
            "claim_count": r.claim_count,
            "spend_cents": int(r.spend_cents),
            "cashback_cents": int(r.cashback_cents),
        }
        for r in rows
    ]


def list_payouts(db: Session, *, status: str | None, page: int, page_size: int) -> dict:
    stmt = select(Payout)
    if status:
        stmt = stmt.where(Payout.status == status)
    stmt = stmt.order_by(Payout.requested_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    items = []
    for p in rows:
        owner = db.get(User, p.user_id)
        txn_count = db.scalar(select(func.count()).select_from(PayoutEntry).where(PayoutEntry.payout_id == p.id)) or 0
        items.append(
            {
                "id": p.id,
                "user_id": p.user_id,
                "full_name": owner.full_name if owner else None,
                "email": owner.email if owner else None,
                "method": p.method,
                "upi_id": p.upi_id,
                "amount_cents": p.amount_cents,
                "status": p.status,
                "payment_reference": p.payment_reference,
                "note": p.note,
                "requested_at": p.requested_at,
                "settled_at": p.settled_at,
                "transaction_count": int(txn_count),
            }
        )
    return {"items": items, "page": page, "page_size": page_size, "total": total}


def payout_transactions(db: Session, payout_id: uuid.UUID) -> list[dict]:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise NotFound()
    rows = db.execute(
        select(
            WalletLedger.id,
            WalletLedger.entry_type,
            WalletLedger.amount_cents,
            WalletLedger.description,
            WalletLedger.created_at,
        )
        .join(PayoutEntry, PayoutEntry.ledger_id == WalletLedger.id)
        .where(PayoutEntry.payout_id == payout_id)
        .order_by(WalletLedger.created_at.asc())
    ).all()
    return [
        {
            "ledger_id": r.id,
            "entry_type": r.entry_type,
            "amount_cents": int(r.amount_cents),
            "description": r.description,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def complete_payout(db: Session, admin: User, payout_id: uuid.UUID, reference: str) -> Payout:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise NotFound()
    if payout.status != "REQUESTED":
        raise PayoutNotRequested()
    reference = reference.strip()
    if not (4 <= len(reference) <= 64):
        raise ValidationError("Payment reference must be 4-64 characters.")
    in_use = db.scalar(select(Payout.id).where(Payout.payment_reference == reference, Payout.status == "PAID").limit(1))
    if in_use is not None:
        raise ReferenceInUse()
    payout.status = "PAID"
    payout.payment_reference = reference
    payout.settled_at = datetime.now(UTC)
    audit(db, admin, "payout.complete", "payout", str(payout.id), {"reference": reference, "amount_cents": payout.amount_cents})
    db.flush()
    return payout


def cancel_payout(db: Session, admin: User, payout_id: uuid.UUID, reason: str) -> Payout:
    payout = db.get(Payout, payout_id)
    if payout is None:
        raise NotFound()
    if payout.status != "REQUESTED":
        raise PayoutNotRequested()
    reason = reason.strip()
    if not (3 <= len(reason) <= 200):
        raise ValidationError("Reason must be 3-200 characters.")
    # Release the linked ledger rows — balance restored, history untouched.
    db.execute(delete(PayoutEntry).where(PayoutEntry.payout_id == payout.id))
    payout.status = "CANCELLED"
    payout.note = reason
    payout.settled_at = datetime.now(UTC)
    audit(db, admin, "payout.cancel", "payout", str(payout.id), {"reason": reason, "amount_cents": payout.amount_cents})
    db.flush()
    return payout


def customer_summary(db: Session, *, page: int, page_size: int) -> dict:
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            User.email,
            func.count(Receipt.id).label("claim_count"),
            func.coalesce(func.sum(Receipt.total_cents), 0).label("spend_cents"),
            func.coalesce(func.sum(Receipt.cashback_cents), 0).label("cashback_cents"),
            func.max(Receipt.purchase_date).label("last_purchase_date"),
        )
        .join(Receipt, Receipt.user_id == User.id)
        .group_by(User.id, User.full_name, User.email)
        .order_by(text("spend_cents DESC"))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    total = db.scalar(select(func.count(func.distinct(Receipt.user_id)))) or 0
    return {
        "items": [
            {
                "user_id": r.id,
                "full_name": r.full_name,
                "email": r.email,
                "claim_count": r.claim_count,
                "spend_cents": int(r.spend_cents),
                "cashback_cents": int(r.cashback_cents),
                "last_purchase_date": r.last_purchase_date,
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": int(total),
    }


def customer_merchant_breakdown(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(
            Offer.merchant_name,
            Offer.category,
            func.count(Receipt.id).label("claim_count"),
            func.coalesce(func.sum(Receipt.total_cents), 0).label("spend_cents"),
            func.coalesce(func.sum(Receipt.cashback_cents), 0).label("cashback_cents"),
            func.max(Receipt.purchase_date).label("last_purchase_date"),
        )
        .join(Receipt, Receipt.offer_id == Offer.id)
        .where(Receipt.user_id == user_id, Receipt.status.in_(["APPROVED", "PAID"]))
        .group_by(Offer.merchant_name, Offer.category)
    ).all()
    return [
        {
            "merchant_name": r.merchant_name,
            "category": r.category,
            "claim_count": r.claim_count,
            "spend_cents": int(r.spend_cents),
            "cashback_cents": int(r.cashback_cents),
            "last_purchase_date": r.last_purchase_date,
        }
        for r in rows
    ]


def customer_transactions(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(
        select(
            Receipt.id,
            Receipt.merchant_name,
            Offer.title.label("offer_title"),
            Offer.category,
            Receipt.purchase_date,
            Receipt.total_cents,
            Receipt.cashback_cents,
            Receipt.status,
        )
        .join(Offer, Offer.id == Receipt.offer_id)
        .where(Receipt.user_id == user_id)
        .order_by(Receipt.submitted_at.desc())
        .limit(200)
    ).all()
    return [
        {
            "receipt_id": r.id,
            "merchant_name": r.merchant_name,
            "offer_title": r.offer_title,
            "category": r.category,
            "purchase_date": r.purchase_date,
            "total_cents": int(r.total_cents),
            "cashback_cents": int(r.cashback_cents),
            "status": r.status,
        }
        for r in rows
    ]


def reverse_receipt_credit(db: Session, admin: User, receipt_id: uuid.UUID, reason: str) -> Receipt:
    """§6.17: reverse an approved receipt's cashback with a compensating ledger row."""
    receipt = db.get(Receipt, receipt_id)
    if receipt is None:
        raise NotFound()
    if receipt.status not in ("APPROVED", "PAID"):
        raise ValidationError("Only approved or paid receipts can be reversed.")
    reason = reason.strip()
    if not (3 <= len(reason) <= 200):
        raise ValidationError("Reason must be 3-200 characters.")

    original = db.scalar(
        select(WalletLedger).where(WalletLedger.source_id == receipt.id, WalletLedger.entry_type == "RECEIPT_CASHBACK")
    )
    if original is None:
        raise NotFound()

    already = db.scalar(select(WalletLedger.id).where(WalletLedger.reversal_of == original.id).limit(1))
    if already is not None:
        raise ValidationError("Receipt has already been reversed.")

    receipt.status = "REVERSED"
    receipt.rejection_reason = reason

    # §6.17: reversal releases the offer budget, never below zero.
    offer_row = db.get(Offer, receipt.offer_id) if receipt.offer_id else None
    if offer_row is not None:
        offer_row.spent_cents = max(0, offer_row.spent_cents - original.amount_cents)

    db.add(
        WalletLedger(
            user_id=receipt.user_id,
            entry_type="REVERSAL",
            amount_cents=-original.amount_cents,
            source_id=receipt.id,
            reversal_of=original.id,
            reference_key=f"reversal:{receipt.id}",
            description=f"Reversal: {reason[:180]}",
        )
    )
    audit(db, admin, "receipt.reverse", "receipt", str(receipt.id), {"reason": reason, "amount_cents": original.amount_cents})
    db.flush()
    return receipt


def update_support_status(db: Session, admin: User, request_id: uuid.UUID, status: str) -> SupportRequest:
    row = db.get(SupportRequest, request_id)
    if row is None:
        raise NotFound()
    row.status = status
    audit(db, admin, "support.status", "support_request", str(row.id), {"status": status})
    db.flush()
    return row
