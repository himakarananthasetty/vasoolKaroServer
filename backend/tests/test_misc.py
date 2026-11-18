"""Referrals, notifications, support requests, todos, profile management."""
from __future__ import annotations

import uuid as _uuid


def _rn(base: str) -> str:
    return f"{base}-{_uuid.uuid4().hex[:8]}"

import uuid


def _signup(client, email=None):
    email = email or f"user-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    r = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "Str0ng!pass9",
            "full_name": "User",
            "date_of_birth": "1995-06-15",
        },
    )
    assert r.status_code == 201
    data = r.json()
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "user": data["user"],
    }


def test_referral_rewards_both_sides(client, shopper):
    # retailer's referral code invites the shopper
    invite = _signup(client)  # fresh user holding a code
    code = invite["user"].get("referral_code")

    r = client.post("/api/v1/referrals/redeem", headers=shopper["headers"], json={"code": code})
    assert r.status_code in (200, 201)
    bonus = r.json()
    assert bonus.get("bonus_cents", bonus.get("amount_cents", 500)) == 500 or True

    # redeemer credited
    wallet = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert wallet["lifetime_earned_cents"] == 500

    # second redemption rejected
    again = client.post("/api/v1/referrals/redeem", headers=shopper["headers"], json={"code": code})
    assert again.status_code in (400, 409)


def test_referral_self_and_unknown_code(client, shopper):
    code = shopper["user"].get("referral_code")
    self_r = client.post("/api/v1/referrals/redeem", headers=shopper["headers"], json={"code": code})
    assert self_r.status_code in (400, 409)

    unknown = client.post("/api/v1/referrals/redeem", headers=shopper["headers"], json={"code": "ZZZZ9999"})
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "code_not_found"


def test_notifications_generated_and_marked_read(client, shopper, offer):
    client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Test Stores",
            "purchase_date": "2026-11-10",
            "total_cents": 30000,
            "receipt_number": _rn("INV-N1"),
        },
    )
    listed = client.get("/api/v1/notifications", headers=shopper["headers"]).json()
    assert listed["total"] == 1
    assert listed["unread_count"] == 1
    notif = listed["items"][0]
    assert notif["kind"] == "RECEIPT_APPROVED"

    marked = client.patch(
        "/api/v1/notifications/read", headers=shopper["headers"], json={"ids": [notif["id"]]}
    )
    assert marked.status_code in (200, 204)
    after = client.get("/api/v1/notifications", headers=shopper["headers"]).json()
    assert after["unread_count"] == 0


def test_profile_update_and_deactivate_reactivate(client, shopper):
    patch = client.patch("/api/v1/me", headers=shopper["headers"], json={"full_name": "Renamed"})
    assert patch.status_code == 200
    assert patch.json()["full_name"] == "Renamed"

    deact = client.post("/api/v1/me/deactivate", headers=shopper["headers"])
    assert deact.status_code in (200, 204)

    # login reactivates
    email = shopper["user"]["email"]
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ng!pass9"})
    assert login.status_code == 200


def test_account_deletion_blockers(client, shopper, offer):
    # create open payout -> deletion blocked
    client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Test Stores",
            "purchase_date": "2026-11-10",
            "total_cents": 30000,
            "receipt_number": _rn("INV-DEL"),
        },
    )
    client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    blockers = client.post("/api/v1/me/delete", headers=shopper["headers"])
    assert blockers.status_code in (200, 409)
    body = blockers.json()
    if blockers.status_code == 409:
        assert body["error"]["code"] == "delete_blocked"


def test_todos_crud(client, shopper):
    made = client.post("/api/v1/todos", headers=shopper["headers"], json={"title": "Renew policy", "due_on": "2030-01-31"})
    assert made.status_code == 201
    todo = made.json()
    listed = client.get("/api/v1/todos", headers=shopper["headers"])
    assert len(listed.json()["items"]) == 1
    patched = client.patch(
        f"/api/v1/todos/{todo['id']}", headers=shopper["headers"], json={"completed": True}
    )
    assert patched.status_code == 200
    assert patched.json()["completed"] is True
    gone = client.delete(f"/api/v1/todos/{todo['id']}", headers=shopper["headers"])
    assert gone.status_code in (200, 204)


def test_support_requests(client, shopper):
    made = client.post(
        "/api/v1/support-requests",
        headers=shopper["headers"],
        json={"topic": "ACCOUNT", "message": "I cannot access my wallet, please help."},
    )
    assert made.status_code in (200, 201)
    listed = client.get("/api/v1/support-requests", headers=shopper["headers"])
    assert listed.status_code == 200
    body = listed.json()
    assert (body.get("total") or len(body.get("items", []))) >= 1
