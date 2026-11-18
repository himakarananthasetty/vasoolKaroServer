"""Auth: signup, login, refresh rotation, session revocation, password change."""
from __future__ import annotations

import uuid


def _u(local: str) -> str:
    return f"{local}-{uuid.uuid4().hex[:8]}@example.com"


def _signup(client, email: str, password: str = "Str0ng!pass9", **extra):
    body = {
        "email": email,
        "password": password,
        "full_name": "Test User",
        "date_of_birth": "1995-06-15",
        **extra,
    }
    return client.post("/api/v1/auth/signup", json=body)


def test_signup_login_me(client):
    email = _u("flow-auth")
    r = _signup(client, email)
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["user"]["email"] == email

    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = client.get("/api/v1/me", headers=h)
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_signup_duplicate_email_rejected(client):
    email = _u("dupe")
    assert _signup(client, email).status_code == 201
    r = _signup(client, email)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_already_registered"


def test_signup_case_insensitive_email(client):
    email = _u("case")
    assert _signup(client, email).status_code == 201
    r = _signup(client, email.upper())
    assert r.status_code == 409


def test_signup_retailer_requires_business_name(client):
    r = _signup(client, _u("nobiz"), account_type="retailer")
    assert r.status_code == 400


def test_signup_rejects_underage(client):
    r = client.post(
        "/api/v1/auth/signup",
        json={
            "email": _u("kid"),
            "password": "Str0ng!pass9",
            "full_name": "Kid",
            "date_of_birth": "2020-06-15",
        },
    )
    assert r.status_code == 400


def test_signup_weak_password_rejected(client):
    r = _signup(client, _u("weak"), password="short")
    assert r.status_code == 422


def test_login_success_and_failure(client):
    email = _u("login")
    assert _signup(client, email).status_code == 201
    ok = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ng!pass9"})
    assert ok.status_code == 200
    bad = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-pass"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"


def test_refresh_rotates_and_revokes_old_token(client):
    email = _u("rot")
    signup = _signup(client, email).json()

    first = client.post("/api/v1/auth/refresh", json={"refresh_token": signup["refresh_token"]})
    assert first.status_code == 200
    new_tokens = first.json()
    assert new_tokens["refresh_token"] != signup["refresh_token"]

    # old token is single-use: replaying must fail
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": signup["refresh_token"]})
    assert replay.status_code == 401

    # the new token still works
    second = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert second.status_code == 200


def test_logout_revokes_the_session(client):
    email = _u("out")
    signup = _signup(client, email).json()
    h = {"Authorization": f"Bearer {signup['access_token']}"}
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 204

    # the session is revoked: the paired refresh token can no longer be used
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": signup["refresh_token"]})
    assert r.status_code == 401


def test_password_change_revokes_other_sessions(client):
    email = _u("pw")
    signup = _signup(client, email).json()
    h = {"Authorization": f"Bearer {signup['access_token']}"}
    r = client.post(
        "/api/v1/auth/password/change",
        headers=h,
        json={"current_password": "Str0ng!pass9", "new_password": "N3w!strong-pass"},
    )
    assert r.status_code == 204
    # old password no longer logs in
    old = client.post("/api/v1/auth/login", json={"email": email, "password": "Str0ng!pass9"})
    assert old.status_code == 401
    new = client.post("/api/v1/auth/login", json={"email": email, "password": "N3w!strong-pass"})
    assert new.status_code == 200


def test_me_requires_auth(client):
    assert client.get("/api/v1/me").status_code == 401
    assert (
        client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-token"}).status_code
        == 401
    )
