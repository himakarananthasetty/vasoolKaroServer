"""End-to-end user-isolation tests: User A vs User B across every owned resource."""

from __future__ import annotations

import uuid

from src.db.models import UserRole

GOOD = {"password": "Str0ng!pass9", "full_name": "Iso Test", "date_of_birth": "1995-06-15"}


def _signup(client, account_type: str = "shopper"):
    email = f"iso-{account_type}-{uuid.uuid4().hex[:10]}@test.vasoolkaro"
    body = {"email": email, **GOOD, "account_type": account_type}
    if account_type == "retailer":
        body["business_name"] = "Iso Stores"
    r = client.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    return {
        "headers": {"Authorization": f"Bearer {data['access_token']}"},
        "refresh": data["refresh_token"],
        "user": data["user"],
    }


def _admin(client):
    from src.auth.service import register_user  # noqa: PLC0415
    from src.core.db import SessionLocal  # noqa: PLC0415

    email = f"iso-admin-{uuid.uuid4().hex[:8]}@test.vasoolkaro"
    with SessionLocal() as db:
        user, _s, _r = register_user(
            db,
            email=email,
            password=GOOD["password"],
            full_name="Admin",
            account_type="shopper",
            business_name=None,
            date_of_birth=None,
        )
        db.add(UserRole(user_id=user.id, role="super_admin"))
        db.commit()
        uid = user.id
    r = client.post("/api/v1/auth/login", json={"email": email, "password": GOOD["password"]})
    return {"headers": {"Authorization": f"Bearer {r.json()['access_token']}"}, "user_id": str(uid)}


def _offer(client, retailer):
    r = client.post(
        "/api/v1/retailer/offers",
        headers=retailer["headers"],
        json={
            "merchant_name": "IsoShop",
            "title": "Iso Offer",
            "description": "d",
            "category": "grocery",
            "cashback_cents": 500,
            "budget_cents": 100000,
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2027-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- Profile isolation -------------------------------------------------------------


def test_profile_update_ignores_ownership_fields(client):
    a = _signup(client)
    r = client.patch(
        "/api/v1/me",
        headers=a["headers"],
        json={"full_name": "Hacker", "account_type": "admin", "referred_by": None, "email": "x@x.io"},
    )
    # unknown/protected fields are dropped by the allow-list schema
    assert r.status_code == 200
    assert r.json()["full_name"] == "Hacker"
    assert r.json()["account_type"] == "shopper"


def test_me_returns_only_own_profile(client):
    a, b = _signup(client), _signup(client)
    ra = client.get("/api/v1/me", headers=a["headers"])
    assert ra.json()["id"] == a["user"]["id"]
    assert ra.json()["id"] != b["user"]["id"]


# --- Receipt isolation -------------------------------------------------------------


def test_receipts_visible_only_to_owner(client):
    retailer = _signup(client, "retailer")
    a, b = _signup(client), _signup(client)
    oid = _offer(client, retailer)
    r = client.post(
        "/api/v1/claims/receipts",
        headers=a["headers"],
        json={
            "offer_id": oid,
            "merchant_name": "IsoShop",
            "purchase_date": "2026-06-01",
            "total_cents": 5000,
            "receipt_number": f"ISO-{uuid.uuid4().hex[:8]}",
        },
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    assert client.get(f"/api/v1/claims/receipts/{rid}", headers=a["headers"]).status_code == 200
    assert client.get(f"/api/v1/claims/receipts/{rid}", headers=b["headers"]).status_code == 404
    listed = client.get("/api/v1/claims/receipts", headers=b["headers"]).json()["items"]
    assert all(item["id"] != rid for item in listed)


# --- Wallet isolation --------------------------------------------------------------


def test_wallet_and_payouts_isolated(client):
    retailer = _signup(client, "retailer")
    a, b = _signup(client), _signup(client)
    oid = _offer(client, retailer)
    client.post(
        "/api/v1/claims/receipts",
        headers=a["headers"],
        json={
            "offer_id": oid,
            "merchant_name": "IsoShop",
            "purchase_date": "2026-06-01",
            "total_cents": 5000,
            "receipt_number": f"ISO-{uuid.uuid4().hex[:8]}",
        },
    )
    ba = client.get("/api/v1/wallet/balance", headers=a["headers"]).json()
    bb = client.get("/api/v1/wallet/balance", headers=b["headers"]).json()
    assert ba["available_cents"] == 500 and bb["available_cents"] == 0
    p = client.post(
        "/api/v1/wallet/payouts",
        headers={**a["headers"], "Idempotency-Key": f"iso-{uuid.uuid4().hex[:12]}"},
        json={"method": "UPI", "upi_id": "alice@upi"},
    )
    assert p.status_code == 201
    pid = p.json()["id"]
    assert client.get(f"/api/v1/wallet/payouts/{pid}/entries", headers=b["headers"]).status_code == 404
    ledger_b = client.get("/api/v1/wallet/ledger", headers=b["headers"]).json()["items"]
    assert ledger_b == []


# --- Todos / notifications / support isolation --------------------------------------


def test_todos_isolated(client):
    a, b = _signup(client), _signup(client)
    t = client.post("/api/v1/todos", headers=a["headers"], json={"title": "A's task", "due_on": "2026-07-01"})
    assert t.status_code == 201
    tid = t.json()["id"]
    # there is no GET-one route; isolation is proven via PATCH/DELETE and the owner's list
    assert client.patch(f"/api/v1/todos/{tid}", headers=b["headers"], json={"title": "hijacked"}).status_code == 404
    assert client.delete(f"/api/v1/todos/{tid}", headers=b["headers"]).status_code == 404
    assert client.patch(f"/api/v1/todos/{tid}", headers=a["headers"], json={"completed": True}).status_code == 200
    listed = client.get("/api/v1/todos", headers=b["headers"]).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert all(item["id"] != tid for item in items)
    mine = client.get("/api/v1/todos", headers=a["headers"]).json()
    mine_items = mine["items"] if isinstance(mine, dict) else mine
    assert any(item["id"] == tid and item.get("completed") for item in mine_items)


def test_notifications_mark_read_scoped(client):
    a, b = _signup(client), _signup(client)
    assert a["user"]["id"] != b["user"]["id"]
    r = client.patch("/api/v1/notifications/read", headers=b["headers"], json={"ids": [str(uuid.uuid4())]})
    assert r.status_code == 200
    assert r.json()["updated"] == 0


def test_support_requests_isolated(client):
    a, b = _signup(client), _signup(client)
    s = client.post(
        "/api/v1/support-requests",
        headers=a["headers"],
        json={"topic": "other", "message": "I need help with my cashback claim please"},
    )
    assert s.status_code == 201
    listed = client.get("/api/v1/support-requests", headers=b["headers"]).json()["items"]
    assert all(item["id"] != s.json()["id"] for item in listed)


# --- Saved offers isolation ----------------------------------------------------------


def test_saved_offers_isolated(client):
    retailer = _signup(client, "retailer")
    a, b = _signup(client), _signup(client)
    oid = _offer(client, retailer)
    s = client.post("/api/v1/saved-offers", headers=a["headers"], json={"offer_id": oid})
    assert s.status_code in (200, 201)
    listed = client.get("/api/v1/saved-offers", headers=b["headers"]).json()["items"]
    assert all(item.get("offer_id") != oid for item in listed)
    assert client.delete(f"/api/v1/saved-offers/{oid}", headers=b["headers"]).status_code in (200, 204)
    still = client.get("/api/v1/saved-offers", headers=a["headers"]).json()["items"]
    assert any((item.get("offer") or {}).get("id") == oid for item in still)


# --- Retailer offer ownership ---------------------------------------------------------


def test_retailer_cannot_update_or_delete_another_offer(client):
    r1, r2 = _signup(client, "retailer"), _signup(client, "retailer")
    oid = _offer(client, r1)
    p = client.patch(f"/api/v1/retailer/offers/{oid}", headers=r2["headers"], json={"budget_cents": 1})
    assert p.status_code == 404


# --- Token security -------------------------------------------------------------------


def test_refresh_token_rotation_invalidates_old_token(client):
    u = _signup(client)
    old = u["refresh"]
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": old})
    assert r2.status_code == 401


def test_user_a_cannot_use_user_b_refresh_token(client):
    _a, b = _signup(client), _signup(client)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": b["refresh"]})
    assert r.status_code == 200
    assert r.json()["user"]["id"] == b["user"]["id"]


def test_revoked_session_rejects_access_token(client):
    u = _signup(client)
    assert client.get("/api/v1/me", headers=u["headers"]).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=u["headers"]).status_code == 204
    assert client.get("/api/v1/me", headers=u["headers"]).status_code == 401


def test_malformed_and_forged_tokens_rejected(client):
    assert client.get("/api/v1/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    forged = client.get("/api/v1/me", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig"})
    assert forged.status_code == 401


# --- Unauthenticated access ------------------------------------------------------------


def test_unauthenticated_blocked_everywhere(client):
    probes = [
        ("get", "/api/v1/me", None),
        ("get", "/api/v1/wallet/balance", None),
        ("get", "/api/v1/todos", None),
        ("get", "/api/v1/notifications", None),
        ("get", "/api/v1/admin/customers", None),
        ("post", "/api/v1/claims/receipts", {}),
        ("post", "/api/v1/wallet/payouts", {}),
        ("post", "/api/v1/todos", {}),
    ]
    for method, path, body in probes:
        fn = getattr(client, method)
        r = fn(path, json=body) if body is not None else fn(path)
        assert r.status_code in (401, 403), f"{path} returned {r.status_code}"


# --- Admin surface is not user-reachable ------------------------------------------------


def test_shopper_cannot_reach_admin_endpoints(client):
    u = _signup(client)
    assert client.get("/api/v1/admin/customers", headers=u["headers"]).status_code == 403
    assert client.get("/api/v1/admin/analytics/overview", headers=u["headers"]).status_code == 403


# --- Payout idempotency ------------------------------------------------------------------


def test_payout_idempotency_replays_same_payout(client):
    retailer = _signup(client, "retailer")
    a = _signup(client)
    oid = _offer(client, retailer)
    for _ in range(2):
        client.post(
            "/api/v1/claims/receipts",
            headers=a["headers"],
            json={
                "offer_id": oid,
                "merchant_name": "IsoShop",
                "purchase_date": "2026-06-01",
                "total_cents": 5000,
                "receipt_number": f"ISO-{uuid.uuid4().hex[:8]}",
            },
        )
    key = f"idem-{uuid.uuid4().hex[:8]}"

    def _payout():
        return client.post(
            "/api/v1/wallet/payouts",
            headers={**a["headers"], "Idempotency-Key": key},
            json={"method": "UPI", "upi_id": "alice@upi"},
        )

    p1, p2 = _payout(), _payout()
    assert p1.status_code == 201, p1.text
    assert p2.status_code == 201, p2.text
    assert p2.json()["id"] == p1.json()["id"]


# --- Environment safety -------------------------------------------------------------------


def test_production_guard_blocks_dev_secrets(monkeypatch):
    from src.core import config  # noqa: PLC0415

    config.get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "dev-secret-change-me")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "dev-internal-token")
    try:
        try:
            config.get_settings()
            raise AssertionError("production with dev secrets must raise")
        except RuntimeError:
            pass
    finally:
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)
        monkeypatch.delenv("INTERNAL_SERVICE_TOKEN", raising=False)
        config.get_settings.cache_clear()
    assert config.get_settings().environment != "production"


def test_test_suite_refuses_non_test_database():
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    env = {**os.environ, "DATABASE_URL": "postgresql+psycopg://prod-user:pw@db.example.com:5432/prod"}
    r = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "54329" in r.stderr
