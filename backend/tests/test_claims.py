"""Receipt submission: eligibility rules, dedup, budget, per-user limits.

The money loop (receipt -> ledger -> wallet -> payout) is exercised here
because submit_receipt performs all of it in one transaction.
"""
from __future__ import annotations

import uuid as _uuid


def _rn(base: str) -> str:
    return f"{base}-{_uuid.uuid4().hex[:8]}"


def _submit(client, shopper, offer, *, n=None, total=50000, date="2026-11-10"):
    n = n or _rn("INV")
    return client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Test Stores",
            "purchase_date": date,
            "total_cents": total,
            "receipt_number": n,
        },
    )


def test_receipt_approved_credits_wallet(client, shopper, offer):
    r = _submit(client, shopper, offer, n=_rn("INV"), total=50000)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "APPROVED"
    assert body["cashback_cents"] == offer["cashback_cents"]

    wallet = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert wallet["available_cents"] == offer["cashback_cents"]
    assert wallet["lifetime_earned_cents"] == offer["cashback_cents"]


def test_duplicate_receipt_rejected_no_double_credit(client, shopper, offer):
    same = _rn("INV")
    first = _submit(client, shopper, offer, n=same, total=50000)
    assert first.status_code == 201 and first.json()["status"] == "APPROVED"

    dup = _submit(client, shopper, offer, n=same, total=50000)
    assert dup.status_code == 201  # rejected outcomes still return 201 per contract
    assert dup.json()["status"] == "REJECTED"
    assert dup.json()["rejection_reason"] == "duplicate_receipt"

    wallet = client.get("/api/v1/wallet/balance", headers=shopper["headers"]).json()
    assert wallet["lifetime_earned_cents"] == offer["cashback_cents"]


def test_below_minimum_purchase_rejected(client, shopper, offer):
    r = _submit(client, shopper, offer, n=_rn("INV"), total=1000)
    assert r.json()["rejection_reason"] == "below_minimum_purchase"


def test_future_purchase_date_rejected(client, shopper, offer):
    r = _submit(client, shopper, offer, n=_rn("INV"), date="2035-01-01")
    assert r.status_code == 400


def test_merchant_mismatch_rejected(client, shopper, offer):
    r = client.post(
        "/api/v1/claims/receipts",
        headers=shopper["headers"],
        json={
            "offer_id": offer["id"],
            "merchant_name": "Other Merchant",
            "purchase_date": "2026-11-10",
            "total_cents": 50000,
            "receipt_number": _rn("INV-MM"),
        },
    )
    assert r.status_code == 201
    assert r.json()["rejection_reason"] == "merchant_name_mismatch"


def test_per_user_limit_enforced(client, shopper, offer):
    a = _submit(client, shopper, offer, n=_rn("INV"))
    b = _submit(client, shopper, offer, n=_rn("INV"))
    assert a.json()["status"] == "APPROVED"
    assert b.json()["status"] == "APPROVED"  # per_user_limit=2

    c = _submit(client, shopper, offer, n=_rn("INV"))
    assert c.json()["status"] == "REJECTED"
    assert c.json()["rejection_reason"] == "user_limit_reached"


def test_budget_tracking_and_exhaustion(client, shopper, retailer):
    # budget exactly two cashbacks
    made = client.post(
        "/api/v1/retailer/offers",
        headers=retailer["headers"],
        json={
            "title": "Tiny Budget",
            "description": "Only two claims fit",
            "merchant_name": "Test Stores",
            "category": "GROCERY",
            "cashback_cents": 2000,
            "budget_cents": 4000,
            "min_purchase_cents": 10000,
            "per_user_limit": 3,
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2030-12-31T00:00:00Z",
        },
    )
    assert made.status_code == 201
    tiny = made.json()

    h = shopper["headers"]
    b1 = _submit(client, shopper, tiny, n=_rn("INV"), total=10000).json()
    assert b1["status"] == "APPROVED", b1.get("rejection_reason")
    assert _submit(client, shopper, tiny, n=_rn("INV"), total=10000).json()["status"] == "APPROVED"
    third = _submit(client, shopper, tiny, n=_rn("INV"), total=10000)
    assert third.json()["rejection_reason"] == "offer_budget_exhausted"

    mine = client.get("/api/v1/retailer/offers", headers=retailer["headers"]).json()["items"]
    row = next(o for o in mine if o["id"] == tiny["id"])
    assert row["spent_cents"] == 4000


def test_receipt_list_is_owner_scoped(client, shopper, offer):
    other = _signup_other(client)
    _submit(client, shopper, offer, n=_rn("INV"))
    mine = client.get("/api/v1/claims/receipts", headers=shopper["headers"])
    theirs = client.get("/api/v1/claims/receipts", headers=other["headers"])
    assert mine.json()["total"] == 1
    assert theirs.json()["total"] == 0


def _signup_other(client):
    import uuid

    email = f"other-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    r = client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "Str0ng!pass9",
            "full_name": "Other",
            "date_of_birth": "1995-06-15",
        },
    )
    data = r.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}}
