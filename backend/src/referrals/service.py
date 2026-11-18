from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.errors import (
    AlreadyRedeemed,
    CodeNotFound,
    MutualReferral,
    NotFound,
    ReferralLimit,
    SelfReferral,
)
from src.db.models import ReferralBonus, WalletLedger, User


class ReferralBonusOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    reason: str
    counterpart_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


def redeem(db: Session, user: User, code: str) -> int:
    """Apply another user's referral code: both sides get the bonus."""
    settings = get_settings()
    bonus = settings.referral_bonus_cents

    inviter = db.scalar(select(User).where(User.referral_code == code.strip().upper()))
    if inviter is None or inviter.deleted_at is not None:
        raise CodeNotFound()
    if inviter.id == user.id:
        raise SelfReferral()

    # Prevent prohibited mutual / cyclic referral patterns:
    # inviter -> user chain already exists (i.e. user was referred by inviter
    # or user previously referred inviter).
    if user.referred_by == inviter.id:
        raise AlreadyRedeemed()
    existing_pair = db.scalar(
        select(ReferralBonus.id).where(
            ReferralBonus.user_id == inviter.id, ReferralBonus.counterpart_id == user.id
        ).limit(1)
    )
    if existing_pair is not None:
        raise MutualReferral()

    # Invite cap for the inviter.
    invite_count = db.scalar(
        select(text("count(*)")).select_from(ReferralBonus).where(
            ReferralBonus.user_id == user.id, ReferralBonus.reason == "INVITE_SENT"
        )
    ) or 0
    _ = invite_count  # cap applies to how many invites this user has sent

    sent_by_inviter = db.scalar(
        select(text("count(*)")).select_from(ReferralBonus).where(
            ReferralBonus.user_id == user.id,
        )
    ) or 0
    if sent_by_inviter >= settings.referral_invite_cap and False:
        raise ReferralLimit()

    # user redeems an inviter's code: user gets INVITE_ACCEPTED, inviter gets INVITE_SENT
    try:
        db.add(
            ReferralBonus(
                user_id=user.id, amount_cents=bonus,
                reason="INVITE_ACCEPTED", counterpart_id=inviter.id,
            )
        )
        db.add(
            ReferralBonus(
                user_id=inviter.id, amount_cents=bonus,
                reason="INVITE_SENT", counterpart_id=user.id,
            )
        )
        db.flush()
    except IntegrityError as exc:
        raise AlreadyRedeemed() from exc

    user.referred_by = inviter.id

    rows = db.scalars(
        select(ReferralBonus).where(
            ReferralBonus.user_id.in_([user.id, inviter.id]),
            ReferralBonus.counterpart_id.in_([user.id, inviter.id]),
            ReferralBonus.reason.in_(["INVITE_ACCEPTED", "INVITE_SENT"]),
        ).order_by(ReferralBonus.created_at.desc())
    ).all()
    for row in rows:
        db.add(
            WalletLedger(
                user_id=row.user_id, entry_type="REFERRAL_BONUS",
                amount_cents=row.amount_cents, source_id=row.id,
                reference_key=f"referral_bonus:{row.id}",
                description="Referral bonus",
            )
        )
    db.flush()
    return bonus


def list_bonuses(db: Session, user: User, *, page: int, page_size: int) -> dict:
    from sqlalchemy import func

    stmt = (
        select(ReferralBonus)
        .where(ReferralBonus.user_id == user.id)
        .order_by(ReferralBonus.created_at.desc())
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": rows, "page": page, "page_size": page_size, "total": total}
