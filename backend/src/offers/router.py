from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.auth.dependencies import get_current_user, require_roles
from src.core.db import get_db
from src.db.models import User
from src.offers import service
from src.offers.service import OfferCreateIn, OfferUpdateIn

router = APIRouter(tags=["offers"])
retailer_router = APIRouter(prefix="/retailer", tags=["retailer"])


@router.get("/offers")
def list_offers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = None,
    q: str | None = None,
    sort: str = Query(default="ending_soon", pattern="^(ending_soon|cashback|newest)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_public_offers(db, page=page, page_size=page_size, category=category, q=q, sort=sort)


@router.get("/offers/{offer_id}")
def get_offer(
    offer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offer = service.get_public_offer(db, offer_id, user)
    return service.OfferOut.model_validate(offer)


@retailer_router.post("/offers", status_code=201)
def create_offer(
    body: OfferCreateIn,
    user: User = Depends(require_roles("admin", "super_admin", "retailer")),
    db: Session = Depends(get_db),
):
    offer = service.create_offer(db, user, body)
    db.commit()
    return service.RetailerOfferOut.model_validate(offer)


@retailer_router.get("/offers", response_model=None)
def list_my_offers(
    user: User = Depends(require_roles("admin", "super_admin", "retailer")),
    db: Session = Depends(get_db),
):
    return {"items": service.list_retailer_offers(db, user)}


@retailer_router.patch("/offers/{offer_id}")
def update_offer(
    offer_id: uuid.UUID,
    body: OfferUpdateIn,
    user: User = Depends(require_roles("admin", "super_admin", "retailer")),
    db: Session = Depends(get_db),
):
    offer = service.update_offer(db, user, offer_id, body)
    db.commit()
    return service.RetailerOfferOut.model_validate(offer)


@retailer_router.get("/offers/stats")
def offer_stats(
    user: User = Depends(require_roles("admin", "super_admin", "retailer")),
    db: Session = Depends(get_db),
):
    return {"items": service.retailer_claim_stats(db, user)}
