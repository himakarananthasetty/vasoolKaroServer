from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.claims import service
from src.claims.service import ReceiptOut, ReceiptSubmitIn
from src.core.db import get_db
from src.db.models import User

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("/receipts", response_model=ReceiptOut, status_code=201)
def submit_receipt(
    body: ReceiptSubmitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    receipt = service.submit_receipt(db, user, body)
    db.commit()
    out = ReceiptOut.model_validate(receipt)
    return out


@router.get("/receipts")
def list_receipts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(
        default=None,
        pattern="^(SUBMITTED|REVIEWING|APPROVED|PAID|REJECTED|REVERSED)$",
    ),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_receipts(db, user, page=page, page_size=page_size, status=status)


@router.get("/receipts/{receipt_id}", response_model=ReceiptOut)
def get_receipt(
    receipt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.get_receipt(db, user, receipt_id)
