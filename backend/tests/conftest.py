"""Shared fixtures: real Postgres (PGlite wire server) + TestClient per test.

Start the disposable database first:
    cd tests && npm install && node pglite-server.cjs &
Then run pytest with DATABASE_URL pointing at it (see DEVELOPMENT_GUIDE.md).
"""
from __future__ import annotations

import os
import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@127.0.0.1:54329/postgres"
)
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only-0123456789abcdef")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-token")

from src.main import app  # noqa: E402  (after env vars are set)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Ensure the schema exists via the real Alembic migration path."""
    subprocess.run(
        ["python3", "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        check=True,
        capture_output=True,
    )


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c
        from src.core.db import SessionLocal
        from src.db.models import RateLimitEvent
        with SessionLocal() as db:
            db.query(RateLimitEvent).delete()
            db.commit()


def _signup(client: TestClient, *, account_type: str = "shopper", email: str | None = None):
    email = email or f"{account_type}-{uuid.uuid4().hex[:10]}@test.vasoolkaro"
    body = {
        "email": email,
        "password": "Str0ng!pass9",
        "full_name": "Test User",
        "account_type": account_type,
        "date_of_birth": "1995-06-15",
    }
    if account_type == "retailer":
        body["business_name"] = "Test Stores"
    r = client.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    return {"headers": headers, "user": data["user"], "tokens": data}


@pytest.fixture
def shopper(client):
    return _signup(client, account_type="shopper")


@pytest.fixture
def retailer(client):
    return _signup(client, account_type="retailer")


@pytest.fixture
def offer(client, retailer):
    r = client.post(
        "/api/v1/retailer/offers",
        headers=retailer["headers"],
        json={
            "title": "Test Cashback",
            "description": "Cashback for tests",
            "merchant_name": "Test Stores",
            "category": "GROCERY",
            "cashback_cents": 5000,
            "budget_cents": 100000,
            "min_purchase_cents": 20000,
            "per_user_limit": 2,
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2030-12-31T00:00:00Z",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
