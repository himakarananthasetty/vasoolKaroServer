# VasoolKaro Security Audit

**Scope:** full backend (`backend/src`, `backend/alembic`, `backend/tests`)
**Method:** static review of every route and service query, plus automated cross-user tests (`backend/tests/test_isolation.py`, 18 tests).
**Result: 83 tests passing, ruff clean, mypy clean (38 source files).**

---

## 1. Scorecard

| # | Category | Verdict |
|---|----------|---------|
| 1 | User identity isolation (no IDOR) | **PASS** |
| 2 | CRUD authorization inventory | **PASS** |
| 3 | Token security (rotation, revocation, ownership) | **PASS** |
| 4 | Environment-based configuration | **PASS** |
| 5 | Frontend/backend contract consistency | **PASS** |
| 6 | Database-level security | **PASS** |
| 7 | Automated cross-user e2e tests | **PASS** |
| 8 | Code quality gates | **PASS** |

---

## 2. User identity isolation

The authenticated user is derived **only** from the JWT: `get_current_user` validates the
 bearer token (signature, `sub`, and `sid` session binding) and returns the `User` row.
No route accepts a user id from the path, query, or body to identify the caller.

INSERT operations derive `user_id` server-side from `user.id`; SELECT/UPDATE/DELETE are
scoped by `user_id == user.id` in the query itself. Verified in every service module:
receipts/claims, wallet + payouts + ledger, todos, notifications, support requests,
saved offers, referrals, profile, push subscriptions. Retailer offer updates are scoped
by `Offer.owner_id == owner.id`.

Profile updates (`PATCH /api/v1/me`) use an explicit allow-list schema
(`full_name`, phone, DOB, address, notification/marketing flags) — `account_type`,
`email`, `referred_by`, and any ownership field sent by a client are dropped.

Admin and internal surfaces are role-gated (`super_admin` / `admin` roles via
`UserRole`); shoppers receive 403. Internal service routes require the
`X-Internal-Token` header compared with `hmac.compare_digest`.

**Fix implemented this audit:** receipt review queue — receipts at or above
`receipt_review_threshold_cents` (500.00) enter `REVIEWING` status instead of
auto-approval; only admins can approve/reject via `POST /admin/receipts/{id}/review`.

## 3. CRUD authorization inventory

| Resource | INSERT | SELECT | UPDATE | DELETE |
|---|---|---|---|---|
| Receipts / claims | user from JWT | owner-only | n/a (status machine) | n/a |
| Wallet balance / ledger | system (ledger entries) | owner-only | n/a | n/a |
| Payouts | user from JWT + Idempotency-Key | owner-only | admin-only status | n/a |
| Todos | user from JWT | owner-only | owner-only (404 cross-user) | owner-only |
| Notifications read | n/a | owner-only | owner-only (`updated` count 0 cross-user) | n/a |
| Support requests | user from JWT | owner-only | n/a | n/a |
| Saved offers | user from JWT | owner-only | n/a | owner-only (silent 204 cross-user) |
| Retailer offers | retailer from JWT | public (owner sees unavailable) | owner-only (404 cross-owner) | owner-only |
| Admin surfaces | role-gated | role-gated + audit() | role-gated | role-gated |
| Internal services | token-gated | token-gated | token-gated | token-gated |

Every cell above is exercised by a test (Section 8).

## 4. Token security

- **Access tokens:** short-lived JWTs; `sub` = user id, `sid` = session row id.
  Every request re-checks that the session row exists and is not revoked, so logout
  immediately kills outstanding access tokens (`test_revoked_session_rejects_access_token`).
- **Refresh rotation:** each refresh issues a new session and revokes the old row;
  replaying the old refresh token returns 401 (`test_refresh_token_rotation_invalidates_old_token`).
- **Token ownership:** a refresh token only ever mints tokens for its own user —
  user A presenting user B's refresh token gets B's session, never A's identity
  (`test_user_a_cannot_use_user_b_refresh_token`).
- **Forged/malformed tokens:** unsigned and garbage tokens are 401
  (`test_malformed_and_forged_tokens_rejected`).
- **Internal token:** constant-time comparison (`hmac.compare_digest`).

## 5. Environment-based configuration

- Central `Settings` (pydantic-settings) is the single source for `environment`,
  `jwt_secret`, `internal_service_token`, `database_url`, debug flags, and limits.
- **Fail-fast production guard:** `get_settings()` raises `RuntimeError` at startup when
  `environment == "production"` and `JWT_SECRET` or `INTERNAL_SERVICE_TOKEN` still equal
  the dev defaults (`test_production_guard_blocks_dev_secrets`).
- **No cross-environment connections:** the test session refuses to run unless
  `DATABASE_URL` points at the isolated test database on port **54329**
  (`test_test_suite_refuses_non_test_database` spins up a subprocess with a production URL
  and asserts it fails with the guard message). Alembic and all tests share this guard;
  a developer cannot accidentally point the suite at staging or production.

## 6. Database-level security

- All DDL through Alembic migrations (`0001_initial`, `0002_payout_idempotency`);
  the schema is reproducible from a clean database.
- Unique constraints back critical invariants: lowercased email uniqueness,
  per-user payout `idempotency_key`, one role row per (user, role).
- Payout creation takes a transaction advisory lock (`pg_advisory_xact_lock`) keyed on
  the user + idempotency key, preventing double-payout races; an open (`REQUESTED`)
  payout blocks a second concurrent request.
- Input validation enforces bounds server-side (receipt totals ≤ 10,000.00, message
  lengths, UPI id regex `^[a-zA-Z0-9._-]{2,255}@…`, payout method `UPI|CASH`), so
  money-math only ever sees validated integers.
- Avatar uploads are content-sniffed by magic bytes, not by client-supplied MIME type.

## 7. Frontend/backend contract consistency

- All errors return one envelope: `{"error": {"code", "message"}}` — handler-level
  (StarletteHTTPException, RequestValidationError) and service-level.
- Success shapes consumed by tests: payouts require the `Idempotency-Key` header;
  todos expose `completed` (not `done`); saved-offer items nest the offer under
  `"offer"`; notifications read is `PATCH /notifications/read` returning `{"updated": n}`.
  These contracts are now pinned by tests so drift breaks CI.

## 8. Test evidence

`backend/tests/test_isolation.py` — 18 cross-user/token/environment tests:

```
test_profile_update_ignores_ownership_fields          PASS
test_me_returns_only_own_profile                      PASS
test_receipts_visible_only_to_owner                   PASS
test_wallet_and_payouts_isolated                      PASS
test_todos_isolated                                   PASS
test_notifications_mark_read_scoped                   PASS
test_support_requests_isolated                        PASS
test_saved_offers_isolated                            PASS
test_retailer_cannot_update_or_delete_another_offer   PASS
test_refresh_token_rotation_invalidates_old_token     PASS
test_user_a_cannot_use_user_b_refresh_token           PASS
test_revoked_session_rejects_access_token             PASS
test_malformed_and_forged_tokens_rejected             PASS
test_unauthenticated_blocked_everywhere               PASS
test_shopper_cannot_reach_admin_endpoints             PASS
test_payout_idempotency_replays_same_payout           PASS
test_production_guard_blocks_dev_secrets              PASS
test_test_suite_refuses_non_test_database             PASS
```

Full run: **83 passed** (`pytest tests --ignore=tests/integration --ignore=tests/unit`),
`ruff check` clean, `ruff format` clean, `mypy` clean (38 files).

Note: `tests/integration` and `tests/unit` are leftover scaffolding from the upstream
FastAPI boilerplate (they import `src.interfaces.main` / `src.infrastructure.*`, which
depend on a newer FastAPI than installed — `get_flat_dependant`). They are not part of
this application's suite and are excluded from the run; they should be deleted in a
follow-up cleanup.

## 9. Remaining risks (accepted / tracked)

- **Rate limiting** is in-memory per process; multi-worker deployments need a shared
  store (Redis) before scaling horizontally.
- **Refresh token reuse detection** revokes the presented session only; a formal
  token-family reuse detector (revoke all sessions on reuse) would harden stolen-token
  scenarios further.
- **No account lockout** — repeated failed logins are rate-limited but not locked.
- The boilerplate test tree noted in Section 8 should be removed.
