from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from src.auth import service
from src.auth.dependencies import client_ip, get_user_session
from src.auth.schemas import (
    LoginIn,
    PasswordChangeIn,
    PasswordRecoveryConfirmIn,
    PasswordRecoveryIn,
    ProfileOut,
    RefreshIn,
    SignupIn,
    TokenOut,
)
from src.common.email import send_recovery_email
from src.common.rate_limit import check_rate_limit
from src.core.db import get_db
from src.core.errors import RateLimited
from src.core.security import create_access_token_with_session
from src.db.models import Session as UserSession
from src.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(db: Session, user: User, session: UserSession, raw_refresh: str) -> TokenOut:
    access, ttl = create_access_token_with_session(str(user.id), user.account_type, session.id)
    return TokenOut(
        access_token=access,
        refresh_token=raw_refresh,
        expires_in=ttl,
        user=ProfileOut.model_validate(user),
    )


@router.post("/signup", response_model=TokenOut, status_code=201)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(
        db,
        action="signup",
        subject_kind="ip",
        subject_id=client_ip(request),
        limit=10,
        window_seconds=3600,
    )
    user, session, raw_refresh = service.register_user(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        account_type=body.account_type,
        business_name=body.business_name,
        date_of_birth=body.date_of_birth,
    )
    db.commit()
    return _tokens(db, user, session, raw_refresh)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_rate_limit(
        db,
        action="login",
        subject_kind="ip",
        subject_id=ip,
        limit=10,
        window_seconds=900,
        error_factory=lambda wait: RateLimited("Too many login attempts.", retry_after_seconds=wait),
    )
    user, session, raw_refresh = service.login(db, body.email, body.password)
    db.commit()
    return _tokens(db, user, session, raw_refresh)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    user, session, raw_refresh = service.rotate_refresh_token(db, body.refresh_token)
    db.commit()
    return _tokens(db, user, session, raw_refresh)


@router.post("/logout", status_code=204)
def logout(
    session: UserSession = Depends(get_user_session),
    db: Session = Depends(get_db),
):
    service.revoke_session(db, session.id)
    db.commit()


@router.post("/logout-other-sessions")
def logout_other_sessions(
    session: UserSession = Depends(get_user_session),
    db: Session = Depends(get_db),
):
    revoked = service.revoke_all_other_sessions(db, session.user_id, session.id)
    db.commit()
    return {"revoked": revoked}


@router.post("/password/change", status_code=204)
def password_change(
    body: PasswordChangeIn,
    session: UserSession = Depends(get_user_session),
    db: Session = Depends(get_db),
):
    user = db.get(User, session.user_id)
    assert user is not None
    service.change_password(db, user, body.current_password, body.new_password)
    service.revoke_all_other_sessions(db, user.id, session.id)
    db.commit()


@router.post("/password/recovery", status_code=202)
def password_recovery(body: PasswordRecoveryIn, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(
        db,
        action="password_recovery",
        subject_kind="ip",
        subject_id=client_ip(request),
        limit=5,
        window_seconds=3600,
    )
    raw = service.request_password_reset(db, body.email)
    db.commit()
    # Email sending is a pluggable adapter; in dev the token is logged, not returned.
    send_recovery_email(body.email, raw)
    return {"ok": True}


@router.post("/password/recovery/confirm", status_code=204)
def password_recovery_confirm(body: PasswordRecoveryConfirmIn, db: Session = Depends(get_db)):
    service.confirm_password_reset(db, body.token, body.new_password)
    db.commit()
