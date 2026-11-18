"""Offers: browsing, retailer CRUD, role authorization, saved offers."""

from __future__ import annotations

from src.core.db import SessionLocal
from src.db.models import Offer


def test_offer_create_requires_retailer_role(client, shopper):
    r = client.post(
        "/api/v1/retailer/offers",
        headers=shopper["headers"],
        json={
            "title": "Nope",
            "description": "Shoppers cannot create offers",
            "merchant_name": "Nope Stores",
            "category": "GROCERY",
            "cashback_cents": 100,
            "budget_cents": 1000,
            "ends_at": "2030-12-31T00:00:00Z",
        },
    )
    assert r.status_code == 403


def test_offer_create_requires_auth(client):
    r = client.post(
        "/api/v1/retailer/offers",
        json={
            "title": "Nope",
            "description": "Anonymous",
            "merchant_name": "Nope Stores",
            "category": "GROCERY",
            "cashback_cents": 100,
            "budget_cents": 1000,
            "ends_at": "2030-12-31T00:00:00Z",
        },
    )
    assert r.status_code == 401


def test_retailer_create_list_update_offer(client, retailer):
    create = client.post(
        "/api/v1/retailer/offers",
        headers=retailer["headers"],
        json={
            "title": "Ramadan Cashback",
            "description": "Special promo",
            "merchant_name": "Test Stores",
            "category": "GROCERY",
            "cashback_cents": 3000,
            "budget_cents": 50000,
            "min_purchase_cents": 10000,
            "ends_at": "2030-06-30T00:00:00Z",
        },
    )
    assert create.status_code == 201
    offer = create.json()
    assert offer["cashback_cents"] == 3000
    assert offer["spent_cents"] == 0

    mine = client.get("/api/v1/retailer/offers", headers=retailer["headers"])
    assert mine.status_code == 200
    assert any(o["id"] == offer["id"] for o in mine.json()["items"])

    stats = client.get("/api/v1/retailer/offers/stats", headers=retailer["headers"])
    assert stats.status_code == 200

    patch = client.patch(
        f"/api/v1/retailer/offers/{offer['id']}",
        headers=retailer["headers"],
        json={"title": "Ramadan Special", "budget_cents": 80000},
    )
    assert patch.status_code == 200
    assert patch.json()["title"] == "Ramadan Special"
    assert patch.json()["budget_cents"] == 80000


def test_budget_cannot_drop_below_spent(client, retailer, offer):
    # offer has spent_cents=0 here; simulate committed spend directly
    with SessionLocal() as db:
        row = db.get(Offer, offer["id"])
        row.spent_cents = 500
        db.commit()
    r = client.patch(
        f"/api/v1/retailer/offers/{offer['id']}",
        headers=retailer["headers"],
        json={"budget_cents": 1},
    )
    assert r.status_code in (400, 409, 422)


def test_offer_browse_and_get(client, shopper, offer):
    browse = client.get("/api/v1/offers?page_size=100&sort=newest", headers=shopper["headers"])
    assert browse.status_code == 200
    items = browse.json()["items"]
    assert any(o["id"] == offer["id"] for o in items)

    one = client.get(f"/api/v1/offers/{offer['id']}", headers=shopper["headers"])
    assert one.status_code == 200
    assert one.json()["id"] == offer["id"]

    missing = client.get("/api/v1/offers/00000000-0000-0000-0000-000000000000", headers=shopper["headers"])
    assert missing.status_code == 404


def test_saved_offers_flow(client, shopper, offer):
    save = client.post("/api/v1/saved-offers", headers=shopper["headers"], json={"offer_id": offer["id"]})
    assert save.status_code == 201

    # idempotent re-save
    resp = client.post("/api/v1/saved-offers", headers=shopper["headers"], json={"offer_id": offer["id"]})
    assert resp.status_code in (200, 201)

    listed = client.get("/api/v1/saved-offers", headers=shopper["headers"])
    assert listed.status_code == 200
    assert any(item["offer"] and item["offer"]["id"] == offer["id"] for item in listed.json()["items"])

    removed = client.delete(f"/api/v1/saved-offers/{offer['id']}", headers=shopper["headers"])
    assert removed.status_code in (200, 204)
    after = client.get("/api/v1/saved-offers", headers=shopper["headers"])
    assert all(not item["offer"] or item["offer"]["id"] != offer["id"] for item in after.json()["items"])
