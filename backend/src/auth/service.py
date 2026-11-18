from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.errors import (
    BusinessNameRequired,
    EmailAlreadyRegistered,
    InvalidCredentials,
    MinimumAge,
    Unauthorized,
    WeakPassword,
)
from src.core.security import (
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from src.db.models import PasswordResetToken, User, UserRole
from src.db.models import Session as UserSession

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_referral_code(db: Session) -> str:
    for _ in range(50):
        code = "".join(CODE_ALPHABET[int(c, 16) % len(CODE_ALPHABET)] for c in uuid.uuid4().hex)[:8]
        exists = db.scalar(select(User.id).where(User.referral_code == code))
        if exists is None:
            return code
    raise RuntimeError("could not generate referral code")


def _age_ok(dob: date | None) -> bool:
    if dob is None:
        return True
    today = datetime.now(UTC).date()
    return dob <= today - timedelta(days=13 * 365.2425)


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str | None,
    account_type: str,
    business_name: str | None,
    date_of_birth,
) -> tuple[User, UserSession, str]:
    if len(password) < 8:
        raise WeakPassword()
    if account_type == "retailer" and not (business_name and 2 <= len(business_name.strip()) <= 80):
        raise BusinessNameRequired()
    if not _age_ok(date_of_birth):
        raise MinimumAge()

    email = email.strip().lower()
    exists = db.scalar(select(User.id).where(User.email == email))
    if exists is not None:
        raise EmailAlreadyRegistered()

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=(full_name or "").strip() or None,
        account_type=account_type,
        business_name=business_name.strip() if business_name else None,
        date_of_birth=date_of_birth,
        referral_code=generate_referral_code(db),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise EmailAlreadyRegistered() from exc

    # Role-based authorization reads user_roles; signup grants the role that
    # matches the account type. Admin/super_admin are provisioned out-of-band.
    db.add(UserRole(user_id=user.id, role=account_type))

    session = _create_session(db, user)
    return user, session, _raw_refresh_of(session)


def _create_session(db: Session, user: User) -> UserSession:
    raw, token_hash, expires_at = new_refresh_token()
    session = UserSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    db.add(session)
    db.flush()
    # stash raw token on the transient object so the caller can return it once
    session.__dict__["_raw_token"] = raw
    return session


def _raw_refresh_of(session: UserSession) -> str:
    raw: str = session.__dict__.get("_raw_token", "")
    return raw


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.deleted_at is not None:
        raise InvalidCredentials()
    if not verify_password(user.password_hash, password):
        raise InvalidCredentials()
    return user


def login(db: Session, email: str, password: str) -> tuple[User, UserSession, str]:
    user = authenticate(db, email, password)
    # Login reactivates a deactivated account (existing behavior).
    if user.deactivated_at is not None:
        user.deactivated_at = None
    session = _create_session(db, user)
    return user, session, _raw_refresh_of(session)


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, UserSession, str]:
    token_hash = hash_token(raw_token)
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash, UserSession.revoked_at.is_(None)))
    if session is None or session.expires_at < datetime.now(UTC):
        if session is not None:
            session.revoked_at = datetime.now(UTC)
        raise Unauthorized(message="Invalid or expired refresh token.")
    session.revoked_at = datetime.now(UTC)
    session.last_used_at = datetime.now(UTC)
    user = db.get(User, session.user_id)
    if user is None or user.deleted_at is not None:
        raise Unauthorized()
    new_session = _create_session(db, user)
    return user, new_session, _raw_refresh_of(new_session)


def revoke_session(db: Session, session_id: uuid.UUID) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def revoke_all_other_sessions(db: Session, user_id: uuid.UUID, keep_session_id: uuid.UUID) -> int:
    res = db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.id != keep_session_id,
            UserSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    return int(res.rowcount or 0)  # type: ignore[attr-defined]


def revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise WeakPassword()
    if not verify_password(user.password_hash, current_password):
        raise InvalidCredentials()
    user.password_hash = hash_password(new_password)


def request_password_reset(db: Session, email: str) -> str | None:
    """Create a single-use reset token. Returns raw token (to email), or None
    when the email is unknown — the endpoint responds identically either way."""
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or user.deleted_at is not None:
        return None
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=datetime.now(UTC) + timedelta(seconds=get_settings().password_reset_ttl_seconds),
    )
    db.add(row)
    return raw


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> None:
    if len(new_password) < 8:
        raise WeakPassword()
    row = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_token(raw_token),
            PasswordResetToken.used_at.is_(None),
        )
    )
    if row is None or row.expires_at < datetime.now(UTC):
        raise Unauthorized(message="Invalid or expired reset token.")
    row.used_at = datetime.now(UTC)
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise Unauthorized(message="Invalid or expired reset token.")
    user.password_hash = hash_password(new_password)
    revoke_all_sessions(db, user.id)
