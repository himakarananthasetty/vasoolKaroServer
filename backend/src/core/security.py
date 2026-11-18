import uuid
from datetime import UTC, datetime, timedelta

import hashlib
import secrets

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from src.core.config import get_settings
from src.core.errors import InvalidCredentials

_settings = get_settings()
_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_access_token(user_id: str, account_type: str) -> tuple[str, int]:
    now = datetime.now(UTC)
    ttl = _settings.access_token_ttl_seconds
    payload = {
        "sub": str(user_id),
        "role": account_type,
        "typ": "access",
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm), ttl


def create_access_token_with_session(user_id: str, account_type: str, session_id) -> tuple[str, int]:
    now = datetime.now(UTC)
    ttl = _settings.access_token_ttl_seconds
    payload = {
        "sub": str(user_id),
        "role": account_type,
        "typ": "access",
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm), ttl


def verify_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise InvalidCredentials() from exc
    if payload.get("typ") != "access":
        raise InvalidCredentials()
    return payload


def new_refresh_token() -> tuple[str, str, datetime]:
    """Return (raw_token, sha256_hash, expires_at)."""
    raw = secrets.token_urlsafe(48)
    ttl = _settings.refresh_token_ttl_seconds
    return raw, hash_token(raw), datetime.now(UTC) + timedelta(seconds=ttl)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
