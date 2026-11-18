from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.errors import (
    BelowMinimum,
    NotFound,
    NothingToPayout,
    PayoutAlreadyRequested,
    ValidationError,
)
from src.db.models import Payout, PayoutEntry, User, WalletLedger

UPI_RE = re.compile(r"^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9-]{1,61}[a-zA-Z]$")


class WalletBalanceOut(BaseModel):
    available_cents: int
    pending_payout_cents: int
    lifetime_earned_cents: int


class LedgerOut(BaseModel):
    id: uuid.UUID
    entry_type: str
    amount_cents: int
    description: str | None
    source_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PayoutCreateIn(BaseModel):
    method: str = Field(pattern="^(UPI|CASH)$")
    upi_id: str | None = Field(default=None, max_length=100)


class PayoutOut(BaseModel):
    id: uuid.UUID
    method: str
    upi_id: str | None
    amount_cents: int
    status: str
    payment_reference: str | None
    note: str | None
    requested_at: datetime
    settled_at: datetime | None

    model_config = {"from_attributes": True}


def get_balance(db: Session, user: User) -> WalletBalanceOut:
    rows = db.execute(
        text(
            """
            SELECT
              COALESCE(SUM(CASE WHEN pe.ledger_id IS NULL THEN l.amount_cents ELSE 0 END), 0) AS available,
              COALESCE(SUM(CASE WHEN pe.ledger_id IS NOT NULL AND p.status = 'REQUESTED'
                                THEN l.amount_cents ELSE 0 END), 0) AS pending,
              COALESCE(SUM(CASE WHEN l.amount_cents > 0 THEN l.amount_cents ELSE 0 END), 0) AS lifetime
            FROM wallet_ledger l
            LEFT JOIN payout_entries pe ON pe.ledger_id = l.id
            LEFT JOIN payouts p ON p.id = pe.payout_id
            WHERE l.user_id = :uid
            """
        ),
        {"uid": str(user.id)},
    ).one()
    return WalletBalanceOut(
        available_cents=int(rows.available),
        pending_payout_cents=int(rows.pending),
        lifetime_earned_cents=int(rows.lifetime),
    )


def list_ledger(db: Session, user: User, *, page: int, page_size: int) -> dict:
    stmt = select(WalletLedger).where(WalletLedger.user_id == user.id).order_by(WalletLedger.created_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total}


def request_payout(db: Session, user: User, body: PayoutCreateIn) -> Payout:
    settings = get_settings()

    upi_id = None
    if body.method == "UPI":
        upi_id = (body.upi_id or "").strip()
        if not upi_id or not UPI_RE.match(upi_id):
            raise ValidationError("A valid UPI id is required for UPI payouts.")
    # CASH ignores any submitted upi_id

    open_payout = db.scalar(select(Payout.id).where(Payout.user_id == user.id, Payout.status == "REQUESTED").limit(1))
    if open_payout is not None:
        raise PayoutAlreadyRequested()

    # Serialize concurrent payout requests per user (advisory lock).
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"payout:{user.id}"})

    # Re-check under the lock.
    open_payout = db.scalar(select(Payout.id).where(Payout.user_id == user.id, Payout.status == "REQUESTED").limit(1))
    if open_payout is not None:
        raise PayoutAlreadyRequested()

    unlinked = db.scalars(
        select(WalletLedger)
        .where(
            WalletLedger.user_id == user.id,
            WalletLedger.id.not_in(select(PayoutEntry.ledger_id)),
        )
        .with_for_update()
        .order_by(WalletLedger.created_at.asc())
    ).all()

    total = sum(row.amount_cents for row in unlinked)
    if total < settings.payout_minimum_cents:
        if total <= 0:
            raise NothingToPayout()
        raise BelowMinimum(f"Minimum payout is {settings.payout_minimum_cents} cents.")

    payout = Payout(user_id=user.id, method=body.method, upi_id=upi_id, amount_cents=total)
    db.add(payout)
    db.flush()
    for row in unlinked:
        db.add(PayoutEntry(ledger_id=row.id, payout_id=payout.id))
    db.flush()
    return payout


def list_payouts(db: Session, user: User, *, page: int, page_size: int) -> dict:
    stmt = select(Payout).where(Payout.user_id == user.id).order_by(Payout.requested_at.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total}


def payout_entries(db: Session, user: User, payout_id: uuid.UUID) -> list[WalletLedger]:
    payout = db.scalar(select(Payout).where(Payout.id == payout_id, Payout.user_id == user.id))
    if payout is None:
        raise NotFound()
    rows = db.scalars(
        select(WalletLedger)
        .join(PayoutEntry, PayoutEntry.ledger_id == WalletLedger.id)
        .where(PayoutEntry.payout_id == payout.id)
        .order_by(WalletLedger.created_at.asc())
    ).all()
    return list(rows)
