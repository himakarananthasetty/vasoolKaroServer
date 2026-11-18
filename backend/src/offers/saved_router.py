"""Saved offers endpoints (bookmarks)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user
from src.core.db import get_db
from src.core.errors import NotFound
from src.db.models import Offer, SavedOffer, User

router = APIRouter(prefix="/saved-offers", tags=["saved-offers"])


class SavedOfferIn(BaseModel):
    offer_id: uuid.UUID


@router.get("")
def list_saved(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedOffer).where(SavedOffer.user_id == user.id).order_by(SavedOffer.created_at.desc())).all()
    items = []
    for row in rows:
        offer = db.get(Offer, row.offer_id)
        items.append(
            {
                "saved_at": row.created_at,
                "offer": {
                    "id": offer.id,
                    "merchant_name": offer.merchant_name,
                    "merchant_address": offer.merchant_address,
                    "title": offer.title,
                    "description": offer.description,
                    "category": offer.category,
                    "cashback_cents": offer.cashback_cents,
                    "budget_cents": offer.budget_cents,
                    "spent_cents": offer.spent_cents,
                    "min_purchase_cents": offer.min_purchase_cents,
                    "per_user_limit": offer.per_user_limit,
                    "starts_at": offer.starts_at,
                    "ends_at": offer.ends_at,
                    "active": offer.active,
                }
                if offer
                else None,
            }
        )
    return {"items": items}


@router.post("", status_code=201)
def save_offer(
    body: SavedOfferIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offer = db.get(Offer, body.offer_id)
    if offer is None:
        raise NotFound()
    existing = db.scalar(select(SavedOffer).where(SavedOffer.user_id == user.id, SavedOffer.offer_id == body.offer_id))
    if existing is None:
        db.add(SavedOffer(user_id=user.id, offer_id=body.offer_id))
        db.commit()
    return {"ok": True}


@router.delete("/{offer_id}", status_code=204)
def unsave_offer(
    offer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.execute(delete(SavedOffer).where(SavedOffer.user_id == user.id, SavedOffer.offer_id == offer_id))
    db.commit()
