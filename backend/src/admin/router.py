from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.admin import service
from src.admin.service import CancelPayoutIn, CompletePayoutIn, ReverseReceiptIn, SupportStatusIn
from src.auth.dependencies import require_roles
from src.core.db import get_db
from src.db.models import User
from src.support.service import SupportOut
from src.wallet.service import PayoutOut

router = APIRouter(prefix="/admin", tags=["admin"])

_admin = Depends(require_roles("admin", "super_admin"))
_super = Depends(require_roles("super_admin"))


@router.get("/analytics/overview")
def analytics_overview(
    user: User = _admin,
    db: Session = Depends(get_db),
):
    return {"items": service.spending_overview(db)}


@router.get("/payouts")
def list_payouts(
    status: str | None = Query(default=None, pattern="^(REQUESTED|PAID|CANCELLED)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = _admin,
    db: Session = Depends(get_db),
):
    return service.list_payouts(db, status=status, page=page, page_size=page_size)


@router.get("/payouts/{payout_id}/transactions")
def payout_transactions(
    payout_id: uuid.UUID,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    return {"items": service.payout_transactions(db, payout_id)}


@router.post("/payouts/{payout_id}/complete")
def complete_payout(
    payout_id: uuid.UUID,
    body: CompletePayoutIn,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    payout = service.complete_payout(db, user, payout_id, body.payment_reference)
    db.commit()
    return PayoutOut.model_validate(payout)


@router.post("/payouts/{payout_id}/cancel")
def cancel_payout(
    payout_id: uuid.UUID,
    body: CancelPayoutIn,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    payout = service.cancel_payout(db, user, payout_id, body.reason)
    db.commit()
    return PayoutOut.model_validate(payout)


@router.get("/customers")
def customers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = _super,
    db: Session = Depends(get_db),
):
    service.audit(db, user, "customers.list", "user", "batch", {"page": page, "page_size": page_size})
    db.commit()
    return service.customer_summary(db, page=page, page_size=page_size)


@router.get("/customers/{user_id}/merchant-breakdown")
def customer_breakdown(
    user_id: uuid.UUID,
    user: User = _super,
    db: Session = Depends(get_db),
):
    service.audit(db, user, "customers.merchant_breakdown", "user", str(user_id), {})
    db.commit()
    return {"items": service.customer_merchant_breakdown(db, user_id)}


@router.get("/customers/{user_id}/transactions")
def customer_transactions(
    user_id: uuid.UUID,
    user: User = _super,
    db: Session = Depends(get_db),
):
    service.audit(db, user, "customers.transactions", "user", str(user_id), {})
    db.commit()
    return {"items": service.customer_transactions(db, user_id)}


@router.get("/receipts", response_model=None)
def list_review_queue(
    status: str = Query(default="REVIEWING", pattern="^(REVIEWING|APPROVED|REJECTED|REVERSED)$"),
    user: User = _admin,
    db: Session = Depends(get_db),
):
    return {"items": service.review_queue(db, status)}


@router.post("/receipts/{receipt_id}/review")
def decide_receipt_review(
    receipt_id: uuid.UUID,
    body: service.ReviewDecisionIn,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    receipt = service.decide_review(db, user, receipt_id, body.approve, body.reason)
    db.commit()
    return {"id": receipt.id, "status": receipt.status, "rejection_reason": receipt.rejection_reason}


@router.post("/receipts/{receipt_id}/reverse")
def reverse_receipt(
    receipt_id: uuid.UUID,
    body: ReverseReceiptIn,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    receipt = service.reverse_receipt_credit(db, user, receipt_id, body.reason)
    db.commit()
    return {"id": receipt.id, "status": receipt.status, "rejection_reason": receipt.rejection_reason}


@router.patch("/support-requests/{request_id}")
def support_status(
    request_id: uuid.UUID,
    body: SupportStatusIn,
    user: User = _admin,
    db: Session = Depends(get_db),
):
    row = service.update_support_status(db, user, request_id, body.status)
    db.commit()
    return SupportOut.model_validate(row)
