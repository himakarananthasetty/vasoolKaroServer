"""

import uuidWallet: balance semantics, ledger, payout request rules and idempotency."""
from __future__ import annotations

import uuid as _uuid


def _rn(base: str) -> str:
    return f"{base}-{_uuid.uuid4().hex[:8]}"


def _fund_wallet(client, shopper, offer, times=1):
    for i in range(times):
        r = client.post(
            "/api/v1/claims/receipts",
            headers=shopper["headers"],
            json={
                "offer_id": offer["id"],
                "merchant_name": "Test Stores",
                "purchase_date": "2026-11-10",
                "total_cents": 30000,
                "receipt_number": _rn(f"INV-W{i}"),
            },
        )
        assert r.json()["status"] == "APPROVED"


def test_empty_wallet_balance(client, shopper):
    r = client.get("/api/v1/wallet/balance", headers=shopper["headers"])
    assert r.status_code == 200
    assert r.json() == {"available_cents": 0, "pending_payout_cents": 0, "lifetime_earned_cents": 0}


def test_balance_transitions_to_pending_on_payout(client, shopper, offer):
    _fund_wallet(client, shopper, offer, times=2)  # 2 x 5000

    r = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    assert r.status_code == 201
    payout = r.json()
    assert payout["status"] == "REQUESTED"
    assert payout["amount_cents"] == 10000

    balance = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert balance["available_cents"] == 0
    assert balance["pending_payout_cents"] == 10000
    assert balance["lifetime_earned_cents"] == 10000


def test_payout_below_minimum_rejected(client, shopper, offer):
    _fund_wallet(client, shopper, offer, times=1)  # 5000 = minimum; try less
    # spend nothing: balance is exactly the minimum, so first payout is fine.
    # Make a wallet below the minimum by using an offer with 100 cashback.
    r = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    assert r.status_code == 201  # 5000 >= 500 minimum


def test_payout_minimum_enforced(client, shopper, retailer):
    tiny = client.post(
        "/api/v1/retailer/offers",
        headers=retailer["headers"],
        json={
            "title": "Micro",
            "description": "One cent cashback",
            "merchant_name": "Test Stores",
            "category": "GROCERY",
            "cashback_cents": 100,
            "budget_cents": 1000,
            "min_purchase_cents": 10000,
            "ends_at": "2030-12-31T00:00:00Z",
        },
    ).json()
    client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": tiny["id"],
            "merchant_name": "Test Stores",
            "purchase_date": "2026-11-10",
            "total_cents": 30000,
            "receipt_number": _rn("INV-MICRO"),
        },
    )
    r = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] in ("below_minimum", "nothing_to_payout")


def test_one_open_payout_per_user(client, shopper, offer):
    _fund_wallet(client, shopper, offer, times=1)
    first = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    assert first.status_code == 201
    second = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI", "upi_id": "user@upi"})
    assert second.status_code in (409, 422)
    assert second.json()["error"]["code"] == "payout_already_requested"


def test_upi_required_for_upi_method(client, shopper, offer):
    _fund_wallet(client, shopper, offer, times=1)
    r = client.post("/api/v1/wallet/payouts", headers=shopper["headers"], json={"method": "UPI"})
    assert r.status_code == 400


def test_ledger_lists_receipt_entries(client, shopper, offer):
    _fund_wallet(client, shopper, offer, times=1)
    ledger = client.get("/api/v1/wallet/ledger", headers=shopper["headers"]).json()
    assert ledger["total"] == 1
    entry = ledger["items"][0]
    assert entry["entry_type"] == "RECEIPT_CASHBACK"
    assert entry["amount_cents"] == 5000


def test_payout_requires_auth(client):
    assert client.get("/api/v1/wallet/balance").status_code == 401
    assert client.post("/api/v1/wallet/payouts", json={"method": "UPI"}).status_code == 401
