import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def uuid7() -> uuid.UUID:
    # Time-ordered UUIDv7 when the platform supports it; falls back to uuid4.
    try:
        return uuid.UUID(bytes=uuid.uuid7().bytes)  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        return uuid.uuid4()


def now_utc() -> datetime:
    return datetime.now(UTC)


def ts_now() -> DateTime:
    return DateTime(timezone=True)


USER_ACCOUNT_TYPE = ("shopper", "retailer")
ADMIN_ROLE = ("admin", "super_admin")
RECEIPT_STATUS = ("SUBMITTED", "REVIEWING", "APPROVED", "PAID", "REJECTED", "REVERSED")
LEDGER_ENTRY_TYPE = ("RECEIPT_CASHBACK", "REFERRAL_BONUS", "REVERSAL")
PAYOUT_METHOD = ("UPI", "CASH")
PAYOUT_STATUS = ("REQUESTED", "PAID", "CANCELLED")
REFERRAL_REASON = ("INVITE_ACCEPTED", "INVITE_SENT")
NOTIFICATION_KIND = ("RECEIPT_APPROVED", "RECEIPT_REJECTED")
SUPPORT_TOPIC = ("ACCOUNT", "CASHBACK", "OFFERS", "OTHER")
SUPPORT_STATUS = ("OPEN", "ANSWERED", "CLOSED")

EnumType = Enum
