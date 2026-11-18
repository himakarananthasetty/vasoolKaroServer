from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.db.models import User
from src.wallet import service
from src.wallet.service import PayoutCreateIn

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/balance", response_model=service.WalletBalanceOut)
def balance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.get_balance(db, user)


@router.get("/ledger")
def ledger(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_ledger(db, user, page=page, page_size=page_size)
    return {
        "items": [service.LedgerOut.model_validate(r) for r in result["items"]],
        "page": result["page"], "page_size": result["page_size"], "total": result["total"],
    }


@router.post("/payouts", response_model=service.PayoutOut, status_code=201)
def request_payout(
    body: PayoutCreateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payout = service.request_payout(db, user, body)
    db.commit()
    return payout


@router.get("/payouts")
def list_payouts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_payouts(db, user, page=page, page_size=page_size)
    return {
        "items": [service.PayoutOut.model_validate(r) for r in result["items"]],
        "page": result["page"], "page_size": result["page_size"], "total": result["total"],
    }


@router.get("/payouts/{payout_id}/entries")
def payout_entries(
    payout_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = service.payout_entries(db, user, payout_id)
    return {"items": [service.LedgerOut.model_validate(r) for r in rows]}
