"""SQLAlchemy models for the VasoolKaro schema (17 tables)."""
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base, uuid7


def _uuid7(ctx):
    return uuid7()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class User(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=_uuid7
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(
        Enum("shopper", "retailer", name="user_account_type"),
        nullable=False, server_default="shopper"
    )
    business_name: Mapped[str | None] = mapped_column(String(80))
    phone_number: Mapped[str | None] = mapped_column(String(20))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    address: Mapped[str | None] = mapped_column(String(200))
    avatar_path: Mapped[str | None] = mapped_column(Text)
    referral_code: Mapped[str] = mapped_column(String(8), nullable=False, unique=True)
    referred_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    notify_offers: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notify_receipts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    personalised_offers: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "(account_type = 'shopper') OR (business_name IS NOT NULL AND char_length(business_name) BETWEEN 2 AND 80)",
            name="chk_users_retailer_business_name",
        ),
        CheckConstraint(
            "date_of_birth IS NULL OR date_of_birth <= CURRENT_DATE - INTERVAL '13 years'",
            name="chk_users_dob_age",
        ),
        CheckConstraint(
            "phone_number IS NULL OR phone_number ~ '^\\+?[0-9 ()-]{7,20}$'",
            name="chk_users_phone",
        ),
        Index("idx_users_referred_by", "referred_by"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")


class UserRole(Base, TimestampMixin):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(
        Enum("shopper", "retailer", "admin", "super_admin", name="user_role"), primary_key=True
    )

    user = relationship("User", back_populates="roles")


class Session(Base, TimestampMixin):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_sessions_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )


class PasswordResetToken(Base, TimestampMixin):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_prt_user", "user_id", "created_at"),)


class Offer(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    merchant_name: Mapped[str] = mapped_column(String(80), nullable=False)
    merchant_address: Mapped[str | None] = mapped_column(String(140))
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    cashback_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    budget_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    spent_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    min_purchase_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    per_user_limit: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("1")
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="chk_offers_window"),
        CheckConstraint("cashback_cents BETWEEN 1 AND 5000", name="chk_offers_cashback"),
        CheckConstraint("min_purchase_cents BETWEEN 0 AND 10000000", name="chk_offers_min_purchase"),
        CheckConstraint("per_user_limit BETWEEN 1 AND 100", name="chk_offers_per_user_limit"),
        CheckConstraint(
            "reserved_cents + spent_cents <= budget_cents", name="chk_offers_budget"
        ),
        CheckConstraint("budget_cents > 0", name="chk_offers_budget_positive"),
        Index("idx_offers_browse", "active", "ends_at"),
        Index("idx_offers_owner", "owner_id"),
    )


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="RESTRICT"), nullable=False
    )
    merchant_name: Mapped[str] = mapped_column(String(80), nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False)
    card_last4: Mapped[str | None] = mapped_column(String(4))
    fingerprint: Mapped[bytes] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("SUBMITTED", "REVIEWING", "APPROVED", "PAID", "REJECTED", "REVERSED",
             name="receipt_status"),
        nullable=False, server_default="SUBMITTED"
    )
    cashback_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("total_cents > 0 AND total_cents <= 10000000", name="chk_receipts_total"),
        CheckConstraint(
            "card_last4 IS NULL OR card_last4 ~ '^[0-9]{4}$'", name="chk_receipts_card_last4"
        ),
        Index(
            "uq_receipts_fingerprint_live",
            "fingerprint",
            unique=True,
            postgresql_where=text("status <> 'REJECTED'"),
        ),
        Index("idx_receipts_user_submitted", "user_id", "submitted_at"),
        Index("idx_receipts_offer_status", "offer_id", "status"),
    )


class WalletLedger(Base, TimestampMixin):
    __tablename__ = "wallet_ledger"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(
        Enum("RECEIPT_CASHBACK", "REFERRAL_BONUS", "REVERSAL", name="ledger_entry_type"),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reference_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(200))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reversal_of: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("wallet_ledger.id", use_alter=True)
    )

    __table_args__ = (
        CheckConstraint(
            "(entry_type = 'REVERSAL' AND amount_cents < 0 AND reversal_of IS NOT NULL)"
            " OR (entry_type <> 'REVERSAL' AND amount_cents > 0 AND reversal_of IS NULL)",
            name="chk_ledger_sign_rules",
        ),
        Index("idx_ledger_user_created", "user_id", "created_at"),
    )


class Payout(Base, TimestampMixin):
    __tablename__ = "payouts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    method: Mapped[str] = mapped_column(
        Enum("UPI", "CASH", name="payout_method"), nullable=False
    )
    upi_id: Mapped[str | None] = mapped_column(String(100))
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("REQUESTED", "PAID", "CANCELLED", name="payout_status"),
        nullable=False, server_default="REQUESTED"
    )
    payment_reference: Mapped[str | None] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(200))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="chk_payouts_amount"),
        CheckConstraint(
            "(method = 'UPI') = (upi_id IS NOT NULL)", name="chk_payouts_upi_pairing"
        ),
        CheckConstraint(
            "(status = 'PAID') = (payment_reference IS NOT NULL)", name="chk_payouts_paid_reference"
        ),
        CheckConstraint(
            "(status = 'CANCELLED') = (note IS NOT NULL)", name="chk_payouts_cancel_note"
        ),
        CheckConstraint(
            "(status = 'REQUESTED') = (settled_at IS NULL)", name="chk_payouts_settled_pairing"
        ),
        CheckConstraint(
            "upi_id IS NULL OR upi_id ~ '^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9-]{1,61}[a-zA-Z]$'",
            name="chk_payouts_upi_format",
        ),
        Index(
            "uq_payouts_one_open", "user_id", unique=True,
            postgresql_where=text("status = 'REQUESTED'"),
        ),
        Index(
            "uq_payouts_reference_paid", "payment_reference", unique=True,
            postgresql_where=text("status = 'PAID'"),
        ),
        Index("idx_payouts_user_requested", "user_id", "requested_at"),
        Index(
            "idx_payouts_open", "status",
            postgresql_where=text("status = 'REQUESTED'"),
        ),
    )


class PayoutEntry(Base):
    __tablename__ = "payout_entries"

    ledger_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wallet_ledger.id", ondelete="CASCADE"), primary_key=True
    )
    payout_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payouts.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (Index("idx_payout_entries_payout", "payout_id"),)


class ReferralBonus(Base, TimestampMixin):
    __tablename__ = "referral_bonuses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(
        Enum("INVITE_ACCEPTED", "INVITE_SENT", name="referral_reason"), nullable=False
    )
    counterpart_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="chk_referral_amount"),
        UniqueConstraint("user_id", "counterpart_id", "reason", name="uq_referral_pair"),
        Index("idx_referral_user", "user_id", "created_at"),
    )


class SavedOffer(Base, TimestampMixin):
    __tablename__ = "saved_offers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    offer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offers.id", ondelete="CASCADE"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "offer_id", name="uq_saved_offers"),
        Index("idx_saved_offers_offer", "offer_id"),
    )


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        Enum("RECEIPT_APPROVED", "RECEIPT_REJECTED", name="notification_kind"), nullable=False
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    merchant_name: Mapped[str] = mapped_column(String(80), nullable=False)
    cashback_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("receipt_id", "kind", name="uq_notifications_receipt_kind"),
        Index("idx_notifications_user", "user_id", "created_at"),
    )


class PushSubscription(Base, TimestampMixin):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    p256dh: Mapped[str] = mapped_column(String(256), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(256), nullable=False)

    __table_args__ = (Index("idx_push_user", "user_id"),)


class SupportRequest(Base, TimestampMixin, UpdatedAtMixin):
    __tablename__ = "support_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(
        Enum("ACCOUNT", "CASHBACK", "OFFERS", "OTHER", name="support_topic"), nullable=False
    )
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("OPEN", "ANSWERED", "CLOSED", name="support_status"),
        nullable=False, server_default="OPEN"
    )

    __table_args__ = (
        Index("idx_support_user", "user_id", "created_at"),
        Index("idx_support_status", "status", "created_at"),
    )


class Todo(Base, TimestampMixin):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (Index("idx_todos_user_due", "user_id", "due_on"),)


class RateLimitEvent(Base):
    __tablename__ = "rate_limit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_rle_window", "action", "subject_kind", "subject_id", "occurred_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_actor", "actor_user_id", "created_at"),
    )
