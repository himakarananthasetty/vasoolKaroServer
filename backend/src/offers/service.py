from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.errors import NotFound, ValidationError
from src.db.models import Offer, Receipt, User

CATEGORIES = {
    "grocery", "dining", "retail", "outdoors", "health", "fuel", "electronics", "other",
}

RETAILER_EDITABLE = {"title", "description", "merchant_address", "budget_cents", "ends_at", "active"}


class OfferCreateIn(BaseModel):
    merchant_name: str = Field(min_length=2, max_length=80)
    merchant_address: str | None = Field(default=None, max_length=140)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    category: str = Field(max_length=40)
    cashback_cents: int = Field(gt=0, le=5000)
    budget_cents: int = Field(gt=0)
    min_purchase_cents: int = Field(default=0, ge=0, le=10_000_000)
    per_user_limit: int = Field(default=1, ge=1, le=100)
    starts_at: datetime | None = None
    ends_at: datetime

    @field_validator("merchant_name", "merchant_address", "title", "description")
    @classmethod
    def strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in CATEGORIES:
            raise ValueError(f"category must be one of: {sorted(CATEGORIES)}")
        return v

    @field_validator("merchant_address")
    @classmethod
    def address_len(cls, v: str | None) -> str | None:
        if v is not None and v != "" and not (5 <= len(v) <= 140):
            raise ValueError("merchant_address must be 5-140 characters")
        return v or None


class OfferUpdateIn(BaseModel):
    """Field allow-list — cashback and merchant name are frozen after creation."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    merchant_address: str | None = Field(default=None, max_length=140)
    budget_cents: int | None = Field(default=None, gt=0)
    ends_at: datetime | None = None
    active: bool | None = None


class OfferOut(BaseModel):
    id: uuid.UUID
    merchant_name: str
    merchant_address: str | None
    title: str
    description: str
    category: str
    cashback_cents: int
    budget_cents: int
    spent_cents: int
    min_purchase_cents: int
    per_user_limit: int
    starts_at: datetime
    ends_at: datetime
    active: bool

    model_config = {"from_attributes": True}


class RetailerOfferOut(OfferOut):
    reserved_cents: int
    owner_id: uuid.UUID | None


def _available(offer: Offer) -> bool:
    now = datetime.now(UTC)
    return offer.active and offer.ends_at > now and offer.reserved_cents + offer.spent_cents < offer.budget_cents


def list_public_offers(
    db: Session, *, page: int, page_size: int, category: str | None,
    q: str | None, sort: str,
) -> dict:
    now = datetime.now(UTC)
    stmt = select(Offer).where(
        Offer.active.is_(True),
        Offer.ends_at > now,
        Offer.reserved_cents + Offer.spent_cents < Offer.budget_cents,
    )
    if category:
        stmt = stmt.where(Offer.category == category.lower())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Offer.merchant_name.ilike(like) | Offer.title.ilike(like))
    if sort == "cashback":
        stmt = stmt.order_by(Offer.cashback_cents.desc())
    elif sort == "newest":
        stmt = stmt.order_by(Offer.created_at.desc())
    else:
        stmt = stmt.order_by(Offer.ends_at.asc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [OfferOut.model_validate(o) for o in rows],
        "page": page, "page_size": page_size, "total": total,
    }


def get_public_offer(db: Session, offer_id: uuid.UUID, user: User) -> Offer:
    offer = db.get(Offer, offer_id)
    if offer is None:
        raise NotFound()
    if not _available(offer) and offer.owner_id != user.id:
        raise NotFound()
    return offer


def create_offer(db: Session, owner: User, body: OfferCreateIn) -> Offer:
    if body.budget_cents < body.cashback_cents:
        raise ValidationError("Budget must cover the cashback amount.")
    starts_at = body.starts_at or datetime.now(UTC)
    if body.ends_at <= starts_at:
        raise ValidationError("ends_at must be after starts_at.")
    offer = Offer(
        owner_id=owner.id,
        merchant_name=body.merchant_name,
        merchant_address=body.merchant_address,
        title=body.title,
        description=body.description,
        category=body.category,
        cashback_cents=body.cashback_cents,
        budget_cents=body.budget_cents,
        min_purchase_cents=body.min_purchase_cents,
        per_user_limit=body.per_user_limit,
        starts_at=starts_at,
        ends_at=body.ends_at,
    )
    db.add(offer)
    db.flush()
    return offer


def update_offer(db: Session, owner: User, offer_id: uuid.UUID, body: OfferUpdateIn) -> Offer:
    offer = db.scalar(select(Offer).where(Offer.id == offer_id, Offer.owner_id == owner.id))
    if offer is None:
        raise NotFound()
    data = body.model_dump(exclude_unset=True)
    if "budget_cents" in data and data["budget_cents"] is not None:
        if data["budget_cents"] < offer.reserved_cents + offer.spent_cents:
            raise ValidationError("Budget cannot be lower than reserved + spent.")
        offer.budget_cents = data["budget_cents"]
    if "ends_at" in data and data["ends_at"] is not None:
        if data["ends_at"] <= offer.starts_at:
            raise ValidationError("ends_at must be after starts_at.")
        offer.ends_at = data["ends_at"]
    for field in ("title", "description", "merchant_address", "active"):
        if field in data and data[field] is not None:
            setattr(offer, field, data[field])
    db.flush()
    return offer


def list_retailer_offers(db: Session, owner: User) -> list[RetailerOfferOut]:
    rows = db.scalars(
        select(Offer).where(Offer.owner_id == owner.id).order_by(Offer.created_at.desc())
    ).all()
    return [RetailerOfferOut.model_validate(o) for o in rows]


def retailer_claim_stats(db: Session, owner: User) -> list[dict]:
    rows = db.execute(
        select(
            Receipt.offer_id,
            func.count().label("claims"),
            func.sum(func.cast(Receipt.status.in_(["APPROVED", "PAID"]), __import__("sqlalchemy").Integer)).label("approved"),
            func.sum(func.cast(Receipt.status == "REJECTED", __import__("sqlalchemy").Integer)).label("rejected"),
            func.coalesce(func.sum(
                func.cast(Receipt.status.in_(["APPROVED", "PAID"]), __import__("sqlalchemy").Integer) * Receipt.cashback_cents
            ), 0).label("approved_total_cents"),
        )
        .join(Offer, Offer.id == Receipt.offer_id)
        .where(Offer.owner_id == owner.id)
        .group_by(Receipt.offer_id)
    ).all()
    return [
        {
            "offer_id": r.offer_id,
            "claims": r.claims,
            "approved": int(r.approved or 0),
            "rejected": int(r.rejected or 0),
            "approved_total_cents": int(r.approved_total_cents or 0),
        }
        for r in rows
    ]
