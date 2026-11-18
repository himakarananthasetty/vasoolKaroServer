"""Audit-fix coverage: referral cap, receipt reversal, deactivated users, rate limits, avatar, ledger trigger."""

from __future__ import annotations

import uuid

from src.core.config import get_settings
from src.db.models import UserRole


def _rn(base: str) -> str:
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _signup(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    r = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "Str0ng!pass9",
            "full_name": "Test User",
            "account_type": "shopper",
            "date_of_birth": "1995-06-15",
        },
    )
    assert r.status_code == 201, r.json()
    data = r.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "user": data["user"]}


def _admin_signup(client):

    from src.auth.service import register_user  # noqa: PLC0415
    from src.core.db import SessionLocal  # noqa: PLC0415

    email = f"admin-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    with SessionLocal() as db:
        user, _session, _raw = register_user(
            db,
            email=email,
            password="Str0ng!pass9",
            full_name="Admin",
            account_type="shopper",
            business_name=None,
            date_of_birth=None,
        )
        db.add(UserRole(user_id=user.id, role="super_admin"))
        db.commit()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ng!pass9"})
    return {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


# --- Referral invite cap -------------------------------------------------------


def test_referral_invite_cap_enforced(client, shopper):
    code = shopper["user"].get("referral_code")
    cap = get_settings().referral_invite_cap
    from src.core.db import SessionLocal  # noqa: PLC0415
    from src.db.models import RateLimitEvent  # noqa: PLC0415

    for _ in range(cap):
        with SessionLocal() as _db:
            _db.query(RateLimitEvent).delete()
            _db.commit()
        other = _signup(client)
        r = client.post("/api/v1/referrals/redeem", headers=other["headers"], json={"code": code})
        assert r.status_code == 200, r.json()
    over = _signup(client)
    r = client.post("/api/v1/referrals/redeem", headers=over["headers"], json={"code": code})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "referral_limit"


# --- Receipt reversal ----------------------------------------------------------


def test_receipt_reversal_restores_balance(client, shopper, offer, retailer):
    admin = _admin_signup(client)
    sub = client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Test Stores",
            "purchase_date": "2026-11-10",
            "total_cents": 30000,
            "receipt_number": _rn("INV-R"),
        },
    )
    assert sub.json()["status"] == "APPROVED"
    before = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert before["available_cents"] == 5000

    r = client.post(
        f"/api/v1/admin/receipts/{sub.json()['id']}/reverse",
        headers=admin["headers"],
        json={"reason": " fraudulent submission "},
    )
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "REVERSED"

    after = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert after["available_cents"] == 0

    # Second reversal is rejected
    r2 = client.post(
        f"/api/v1/admin/receipts/{sub.json()['id']}/reverse",
        headers=admin["headers"],
        json={"reason": "trying again"},
    )
    assert r2.status_code == 400


def test_receipt_reversal_requires_admin(client, shopper, offer):
    sub = client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Test Stores",
            "purchase_date": "2026-11-10",
            "total_cents": 30000,
            "receipt_number": _rn("INV-RR"),
        },
    )
    assert sub.json()["status"] == "APPROVED"
    r = client.post(
        f"/api/v1/admin/receipts/{sub.json()['id']}/reverse",
        headers=shopper["headers"],
        json={"reason": "not an admin"},
    )
    assert r.status_code == 403


# --- Deactivated users ---------------------------------------------------------


def test_deactivated_user_token_rejected(client, shopper):
    r = client.get("/api/v1/me", headers=shopper["headers"])
    assert r.status_code == 200
    from datetime import UTC, datetime  # noqa: PLC0415

    from src.core.db import SessionLocal  # noqa: PLC0415
    from src.db.models import User  # noqa: PLC0415

    with SessionLocal() as db:
        row = db.get(User, shopper["user"]["id"])
        row.deactivated_at = datetime.now(UTC)
        db.commit()
    r2 = client.get("/api/v1/me", headers=shopper["headers"])
    assert r2.status_code == 403


# --- Rate limits on push registration and support -------------------------------


def test_push_registration_ip_rate_limited(client, shopper):
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from src.core.db import SessionLocal  # noqa: PLC0415
    from src.db.models import RateLimitEvent  # noqa: PLC0415

    with SessionLocal() as db:
        db.add(
            RateLimitEvent(action="push_register", subject_kind="ip", subject_id="testclient", occurred_at=datetime.now(UTC))
        )
        for i in range(20):
            db.add(
                RateLimitEvent(
                    action="push_register",
                    subject_kind="ip",
                    subject_id="testclient",
                    occurred_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        db.commit()
    r = client.post(
        "/api/v1/push/subscriptions",
        headers=shopper["headers"],
        json={"endpoint": f"https://push.example/{uuid.uuid4().hex}", "p256dh": "k" * 40, "auth_key": "a" * 40},
    )
    assert r.status_code == 429


def test_push_subscription_requires_https(client, shopper):
    r = client.post(
        "/api/v1/push/subscriptions",
        headers=shopper["headers"],
        json={"endpoint": "http://insecure.example/abc", "p256dh": "k" * 40, "auth_key": "a" * 40},
    )
    assert r.status_code == 422


# --- Avatar upload + serve -------------------------------------------------------


def test_avatar_upload_and_fetch(client, shopper):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    up = client.put("/api/v1/me/avatar", headers=shopper["headers"], files={"avatar": ("avatar.png", png, "image/png")})
    assert up.status_code == 200, up.json()
    got = client.get("/api/v1/me/avatar", headers=shopper["headers"])
    assert got.status_code == 200
    assert got.content == png
    assert got.headers["content-type"].startswith("image/png")


def test_avatar_delete(client, shopper):
    png = b"\x89PNG\r\n\x1a\n" + b"1" * 64
    up = client.put("/api/v1/me/avatar", headers=shopper["headers"], files={"avatar": ("avatar.png", png, "image/png")})
    assert up.status_code == 200
    gone = client.delete("/api/v1/me/avatar", headers=shopper["headers"])
    assert gone.status_code == 204
    got = client.get("/api/v1/me/avatar", headers=shopper["headers"])
    assert got.status_code == 404
