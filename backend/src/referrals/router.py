from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.db.models import User
from src.referrals import service

router = APIRouter(prefix="/referrals", tags=["referrals"])


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=8)


@router.post("/redeem")
def redeem(
    body: RedeemIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bonus = service.redeem(db, user, body.code)
    db.commit()
    return {"bonus_cents": bonus}


@router.get("/bonuses")
def bonuses(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = service.list_bonuses(db, user, page=page, page_size=page_size)
    return {
        "items": [service.ReferralBonusOut.model_validate(r) for r in result["items"]],
        "page": result["page"], "page_size": result["page_size"], "total": result["total"],
    }
