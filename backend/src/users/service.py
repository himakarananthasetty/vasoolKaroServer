from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.errors import DobLocked, MinimumAge, NotFound, ValidationError
from src.db.models import Offer, Receipt, SavedOffer, Todo, User, WalletLedger

PHONE_RE = re.compile(r"^\+?[0-9 ()-]{7,20}$")

# Blockers for account deletion (existing product behavior).
DELETE_BLOCKERS = {
    "wallet_history": "Wallet history exists; the account cannot be deleted.",
    "open_payouts": "You have an open payout request.",
    "open_claims": "You have claims under review.",
    "has_offers": "Retailer accounts with offers cannot be deleted.",
}


def get_profile(db: Session, user: User) -> User:
    return user


def update_profile(
    db: Session,
    user: User,
    *,
    full_name: str | None = None,
    phone_number: str | None = None,
    date_of_birth=None,
    address: str | None = None,
    notify_offers: bool | None = None,
    notify_receipts: bool | None = None,
    marketing_opt_in: bool | None = None,
    personalised_offers: bool | None = None,
) -> User:
    if full_name is not None:
        user.full_name = full_name.strip() or None
    if phone_number is not None:
        if phone_number != "" and not PHONE_RE.match(phone_number):
            raise ValidationError("Invalid phone number.")
        user.phone_number = phone_number or None
    if date_of_birth is not None:
        if user.date_of_birth is not None:
            raise DobLocked()
        today = datetime.now(UTC).date()
        if date_of_birth > today:
            raise ValidationError("Date of birth cannot be in the future.")
        age = today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
        if age < 13:
            raise MinimumAge()
        user.date_of_birth = date_of_birth
    if address is not None:
        if len(address) > 200:
            raise ValidationError("Address is limited to 200 characters.")
        user.address = address or None
    if notify_offers is not None:
        user.notify_offers = notify_offers
    if notify_receipts is not None:
        user.notify_receipts = notify_receipts
    if marketing_opt_in is not None:
        user.marketing_opt_in = marketing_opt_in
    if personalised_offers is not None:
        user.personalised_offers = personalised_offers
    db.flush()
    return user


def deactivate(db: Session, user: User) -> None:
    user.deactivated_at = datetime.now(UTC)
    db.flush()


def reactivate(db: Session, user: User) -> None:
    user.deactivated_at = None
    db.flush()


def deletion_blockers(db: Session, user: User) -> str | None:
    has_ledger = db.scalar(select(WalletLedger.id).where(WalletLedger.user_id == user.id).limit(1))
    if has_ledger is not None:
        return "wallet_history"
    from src.db.models import Payout
    open_payout = db.scalar(
        select(Payout.id).where(Payout.user_id == user.id, Payout.status == "REQUESTED").limit(1)
    )
    if open_payout is not None:
        return "open_payouts"
    open_claim = db.scalar(
        select(Receipt.id).where(
            Receipt.user_id == user.id, Receipt.status.in_(["SUBMITTED", "REVIEWING"])
        ).limit(1)
    )
    if open_claim is not None:
        return "open_claims"
    has_offers = db.scalar(select(Offer.id).where(Offer.owner_id == user.id).limit(1))
    if has_offers is not None:
        return "has_offers"
    return None


def delete_account(db: Session, user: User) -> None:
    blocker = deletion_blockers(db, user)
    if blocker is not None:
        from src.core.errors import DeleteBlocked
        raise DeleteBlocked(blocker)

    # No financial history: remove personal app records (financial tables are
    # empty by definition of the blockers), then anonymize + soft-delete.
    db.query(Todo).filter(Todo.user_id == user.id).delete()
    db.query(SavedOffer).filter(SavedOffer.user_id == user.id).delete()
    from src.db.models import Notification, PushSubscription, Session as UserSession, SupportRequest
    db.query(Notification).filter(Notification.user_id == user.id).delete()
    db.query(PushSubscription).filter(PushSubscription.user_id == user.id).delete()
    db.query(SupportRequest).filter(SupportRequest.user_id == user.id).delete()
    db.query(UserSession).filter(UserSession.user_id == user.id).delete()

    user.full_name = None
    user.phone_number = None
    user.address = None
    user.avatar_path = None
    user.email = f"deleted-{user.id}@invalid.vasoolkaro"
    user.password_hash = "!"
    user.deleted_at = datetime.now(UTC)
    db.flush()


ALLOWED_AVATAR_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def save_avatar(db: Session, user: User, upload: UploadFile, content: bytes) -> str:
    settings = get_settings()
    if len(content) > settings.avatar_max_bytes:
        raise ValidationError("Avatar exceeds the 2 MB size limit.")
    ext = ALLOWED_AVATAR_TYPES.get(upload.content_type or "")
    if ext is None:
        raise ValidationError("Avatar must be JPEG, PNG, or WebP.")
    from pathlib import Path

    base = Path(settings.avatar_dir) / str(user.id)
    base.mkdir(parents=True, exist_ok=True)
    old = user.avatar_path
    path = base / f"avatar-{uuid.uuid4().hex[:12]}{ext}"
    path.write_bytes(content)
    user.avatar_path = str(path)
    db.flush()
    if old:
        try:
            Path(old).unlink(missing_ok=True)
        except OSError:
            pass
    return user.avatar_path
