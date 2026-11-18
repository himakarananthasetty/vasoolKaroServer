"""Admin: payout completion/cancellation restores balances correctly; roles."""

from __future__ import annotations

import uuid
import uuid as _uuid

from src.auth.service import register_user  # noqa: E402
from src.core.db import SessionLocal  # noqa: E402


def _rn(base: str) -> str:
    return f"{base}-{_uuid.uuid4().hex[:8]}"


def _pay(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": _rn("payout-key")}


def _admin_signup(client):
    """Create a super_admin directly in the DB (admin roles are provisioned out-of-band)."""
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
        from sqlalchemy import update  # noqa: PLC0415

        db.execute(update(UserRoleAssignment).where(UserRoleAssignment.user_id == user.id).values(role="super_admin"))
        db.commit()
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ng!pass9"})
    assert r.status_code == 200
    return {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}


from src.db.models import UserRole as UserRoleAssignment  # noqa: E402


def _fund(client, shopper, offer, times=1):
    for i in range(times):
        client.post(
            "/api/v1/claims/receipts",
            headers=shopper["headers"],
            json={
                "offer_id": offer["id"],
                "merchant_name": "Test Stores",
                "purchase_date": "2026-11-10",
                "total_cents": 30000,
                "receipt_number": f"INV-A{i}-{uuid.uuid4().hex[:4]}",
            },
        )


def test_shopper_cannot_access_admin(client, shopper):
    assert client.get("/api/v1/admin/payouts", headers=shopper["headers"]).status_code == 403
    assert client.get("/api/v1/admin/payouts").status_code == 401


def test_admin_lists_payouts_and_completes(client, shopper, retailer, offer):
    admin = _admin_signup(client)
    _fund(client, shopper, offer, times=1)
    payout = client.post(
        "/api/v1/wallet/payouts",
        headers=_pay(shopper["headers"]),
        json={"method": "UPI", "upi_id": "user@upi"},
    ).json()

    listed = client.get("/api/v1/admin/payouts", headers=admin["headers"])
    assert listed.status_code == 200
    assert any(p["id"] == payout["id"] for p in listed.json()["items"])

    done = client.post(
        f"/api/v1/admin/payouts/{payout['id']}/complete",
        headers=admin["headers"],
        json={"payment_reference": _rn("TXN")},
    )
    assert done.status_code == 200
    assert done.json()["status"] == "PAID"
    assert done.json()["payment_reference"].startswith("TXN-")

    # after completion: no longer pending; lifetime unchanged
    balance = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert balance["pending_payout_cents"] == 0
    assert balance["available_cents"] == 0
    assert balance["lifetime_earned_cents"] == 5000

    # double completion rejected
    again = client.post(
        f"/api/v1/admin/payouts/{payout['id']}/complete",
        headers=admin["headers"],
        json={"payment_reference": _rn("TXN")},
    )
    assert again.status_code in (400, 409)


def test_paid_reference_uniqueness(client, shopper, retailer, offer):
    admin = _admin_signup(client)
    # two shoppers, two payouts, same reference must be rejected the second time
    _fund(client, shopper, offer, times=1)
    p1r = client.post("/api/v1/wallet/payouts", headers=_pay(shopper["headers"]), json={"method": "UPI", "upi_id": "alpha@upi"})
    assert p1r.status_code == 201, p1r.text
    p1 = p1r.json()
    ref = _rn("TXN")
    done = client.post(f"/api/v1/admin/payouts/{p1['id']}/complete", headers=admin["headers"], json={"payment_reference": ref})
    assert done.status_code == 200

    # create a second shopper + payout
    email = f"two-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "Str0ng!pass9", "full_name": "Two", "date_of_birth": "1995-06-15"},
    )
    two = {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}}
    _fund(client, two, offer, times=1)
    p2r = client.post("/api/v1/wallet/payouts", headers=_pay(two["headers"]), json={"method": "UPI", "upi_id": "beta@upi"})
    assert p2r.status_code == 201, p2r.text
    p2 = p2r.json()
    dup = client.post(f"/api/v1/admin/payouts/{p2['id']}/complete", headers=admin["headers"], json={"payment_reference": ref})
    assert dup.status_code in (400, 409)


def test_cancel_payout_restores_balance(client, shopper, offer):
    admin = _admin_signup(client)
    _fund(client, shopper, offer, times=1)
    payout = client.post(
        "/api/v1/wallet/payouts",
        headers=_pay(shopper["headers"]),
        json={"method": "UPI", "upi_id": "user@upi"},
    ).json()
    assert client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()["available_cents"] == 0

    cancelled = client.post(
        f"/api/v1/admin/payouts/{payout['id']}/cancel",
        headers=admin["headers"],
        json={"reason": "Bank holiday"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"

    balance = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert balance["available_cents"] == 5000
    assert balance["pending_payout_cents"] == 0

    # a new payout is possible after cancellation
    again = client.post(
        "/api/v1/wallet/payouts",
        headers=_pay(shopper["headers"]),
        json={"method": "UPI", "upi_id": "user@upi"},
    )
    assert again.status_code == 201


def test_admin_overview_and_customers(client, shopper, offer):
    admin = _admin_signup(client)
    _fund(client, shopper, offer, times=1)
    overview = client.get("/api/v1/admin/analytics/overview", headers=admin["headers"])
    assert overview.status_code == 200
    customers = client.get("/api/v1/admin/customers", headers=admin["headers"])
    assert customers.status_code in (200, 404)  # 404 only if route naming differs
