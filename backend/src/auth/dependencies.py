"""Auth dependencies: resolve current user / roles from the bearer token."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.db import get_db
from src.core.errors import Forbidden, InvalidCredentials, Unauthorized
from src.core.security import verify_access_token
from src.db.models import Session as UserSession
from src.db.models import User, UserRole

_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise Unauthorized()
    payload = verify_access_token(credentials.credentials)
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.deleted_at is not None:
        raise InvalidCredentials()
    return user


def require_roles(*allowed: str):
    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        roles = db.scalars(select(UserRole.role).where(UserRole.user_id == user.id)).all()
        if not any(r in allowed for r in roles):
            raise Forbidden()
        return user

    return checker


def get_user_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UserSession:
    if credentials is None:
        raise Unauthorized()
    payload = verify_access_token(credentials.credentials)
    session = db.get(UserSession, uuid.UUID(payload.get("sid", "00000000-0000-0000-0000-000000000000")))
    if session is None or session.revoked_at is not None:
        raise Unauthorized()
    return session


def client_ip(request: Request) -> str:
    return _client_ip(request)
