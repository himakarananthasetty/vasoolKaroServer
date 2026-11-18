# VasoolKaro — REST API Reference

Base URL: `https://<your-server>/api/v1`. All bodies are JSON. All timestamps are ISO-8601 UTC. All money fields are integer cents (`*_cents`).

**Authentication** unless stated otherwise: `Authorization: Bearer <access_token>` (JWT, 15-minute expiry). Roles: any authenticated user unless marked **shopper**, **retailer**, or **admin**/**super_admin**.

**Common status codes:** `200` OK · `201` Created · `204` No Content · `400` validation error · `401` unauthenticated · `403` forbidden/insufficient role · `404` not found or not owned · `409` conflict (duplicate, state machine violation) · `422` business-rule rejection · `429` rate limited · `500` server error.

**Error envelope:**

```json
{ "error": { "code": "duplicate_receipt", "message": "This receipt was already submitted." } }
```

Codes are stable; messages may change. Unauthenticated responses never reveal whether an email exists.

---

## Module 1 — Authentication & sessions

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 1.1 | `POST /auth/signup` | Create an account (shopper or retailer) | none | `users`, `sessions` |
| 1.2 | `POST /auth/login` | Password login, issues tokens | none | `users`, `sessions` |
| 1.3 | `POST /auth/refresh` | Exchange refresh token for new tokens | refresh token | `sessions` |
| 1.4 | `POST /auth/logout` | Revoke the current session | bearer | `sessions` |
| 1.5 | `POST /auth/logout-other-sessions` | Revoke all other sessions | bearer | `sessions` |
| 1.6 | `POST /auth/password/change` | Change password (revokes other sessions) | bearer | `users`, `sessions` |
| 1.7 | `POST /auth/password/recovery` | Email a reset link | none (IP-limited) | `password_reset_tokens` |
| 1.8 | `POST /auth/password/recovery/confirm` | Set a new password with a reset token | none (token) | `password_reset_tokens`, `users`, `sessions` |

### 1.1 `POST /auth/signup`

Request:

```json
{
  "email": "user@example.com",
  "password": "at-least-8-chars",
  "full_name": "Himakar Ananthasetty",
  "account_type": "shopper",
  "business_name": null,
  "date_of_birth": "1995-04-12"
}
```

`account_type` is `shopper` | `retailer`; `business_name` (2–80 chars) is required for retailers; `date_of_birth` must give age ≥ 13.

Response `201`:

```json
{ "access_token": "<jwt>", "refresh_token": "<opaque>", "token_type": "bearer", "expires_in": 900,
  "user": { "id": "uuid", "email": "user@example.com", "full_name": "Himakar Ananthasetty", "account_type": "shopper", "referral_code": "VK3F8Q2A" } }
```

Errors: `400 email_already_registered`, `400 weak_password`, `400 business_name_required`, `400 minimum_age`. Immediate-session signup is preserved (matching the current client).

### 1.2 `POST /auth/login`

Request `{ "email": "...", "password": "..." }` → `200` same shape as signup. Login also **reactivates** a deactivated account (existing behavior). Errors: `401 invalid_credentials` (ambiguous by design).

### 1.3 `POST /auth/refresh`

Request `{ "refresh_token": "..." }` → `200` new token pair (refresh-token rotation; the presented token is marked revoked and replaced). Errors: `401 invalid_refresh_token`.

### 1.6 `POST /auth/password/change`

Request `{ "current_password": "...", "new_password": "..." }`. Verifies the current password (matching today's `signInWithPassword` + `updateUser` flow). `204`. Revokes all other sessions. Errors: `401 invalid_credentials`, `400 weak_password`.

### 1.7 / 1.8 Password recovery *(proposed addition — the current product has no recovery flow)*

1.7 request `{ "email": "..." }` → always `202` (never reveals whether the email exists). 1.8 request `{ "token": "...", "new_password": "..." }` → `204`; single-use token, revokes all sessions.

**Business logic:** argon2id verification; refresh tokens stored as SHA-256 hashes; user id always derived from the token, never the body; login/signup/refresh/recovery are IP-rate-limited.

---

## Module 2 — Profile (`/me`)

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 2.1 | `GET /me` | Current profile | bearer | `users` |
| 2.2 | `PATCH /me` | Update allowed profile fields | bearer | `users` |
| 2.3 | `POST /me/deactivate` | Deactivate own account | bearer | `users` |
| 2.4 | `POST /me/reactivate` | Reactivate own account | bearer | `users` |
| 2.5 | `POST /me/delete` | Delete own account (blocker-checked) | bearer | `users`, `receipts`, `saved_offers`, `todos`, `wallet_ledger`, `payouts`, `sessions` |
| 2.6 | `PUT /me/avatar` | Upload avatar (JPEG/PNG/WebP, ≤ 2 MB) | bearer | `users` |
| 2.7 | `GET /me/avatar-url` | Short-lived signed avatar URL | bearer | `users` |

### 2.1 `GET /me` → `200`

```json
{ "id": "uuid", "email": "user@example.com", "full_name": "...", "account_type": "shopper",
  "business_name": null, "phone_number": "+91 98765 43210", "date_of_birth": "1995-04-12",
  "address": null, "avatar_path": "avatars/uuid/avatar-1731.png",
  "referral_code": "VK3F8Q2A", "referred_by": null,
  "notify_offers": true, "notify_receipts": true, "marketing_opt_in": false, "personalised_offers": true,
  "deactivated_at": null, "created_at": "...", "updated_at": "..." }
```

### 2.2 `PATCH /me`

Request (only these fields are accepted; all optional):

```json
{ "full_name": "...", "phone_number": "+91...", "date_of_birth": "1995-04-12",
  "address": "…≤200 chars", "notify_offers": true, "notify_receipts": true,
  "marketing_opt_in": false, "personalised_offers": true }
```

→ `200` updated profile. Errors: `400 dob_locked` (already set), `400 minimum_age`, `400 invalid_phone`. Attempts to send `email`, `account_type`, `referral_code`, or state fields are rejected by the schema. *(Same allow-list as the old column-level grants.)*

### 2.3 / 2.4 Deactivate / reactivate

`204` each. Deactivate sets `deactivated_at`; reactivate clears it (also invoked implicitly by login). Reactivating a non-deactivated account is idempotent.

### 2.5 `POST /me/delete`

Request: none. Response `200` on success: `{ "ok": true }`. Blocked → `409`:

```json
{ "error": { "code": "delete_blocked", "reason": "wallet_history",
  "message": "Wallet history exists; the account cannot be deleted." } }
```

Blocker `reason` values (existing behavior): `wallet_history` (any ledger row), `open_payouts`, `open_claims` (SUBMITTED/REVIEWING receipt), `has_offers` (retailer with offers). On success: personal records deleted, sessions revoked; when financial retention applies, the account is anonymized (soft delete) rather than erased.

**Business logic:** blockers re-checked inside one transaction; deletion is idempotent on retry.

---

## Module 3 — Offers (public catalog) & retailer offer management

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 3.1 | `GET /offers` | Browse active offers | bearer (any) | `offers` |
| 3.2 | `GET /offers/{offerId}` | Offer detail | bearer (any) | `offers` |
| 3.3 | `GET /saved-offers` | List saved offers with offer data | bearer | `saved_offers`, `offers` |
| 3.4 | `POST /saved-offers` | Save an offer (idempotent) | bearer | `saved_offers` |
| 3.5 | `DELETE /saved-offers/{offerId}` | Unsave an offer | bearer | `saved_offers` |
| 3.6 | `GET /retailer/offers` | Own offers incl. inactive | retailer | `offers` |
| 3.7 | `POST /retailer/offers` | Create an offer | retailer | `offers` |
| 3.8 | `PATCH /retailer/offers/{offerId}` | Update own offer (restricted fields) | retailer | `offers` |
| 3.9 | `GET /retailer/offers/stats` | Claim stats for own offers | retailer | `offers`, `receipts` |

### 3.1 `GET /offers`

Query params: `page` (default 1), `page_size` (default 20, max 100), `category`, `q` (merchant/title search), `sort` (`ending_soon` default | `cashback` | `newest`).

Returns only `active = true AND ends_at > now()` and remaining budget > 0 (existing availability rule), ordered by `ends_at` ascending for `ending_soon`.

Response `200`:

```json
{ "items": [ { "id": "uuid", "merchant_name": "FreshMart", "merchant_address": "12 MG Road, Bengaluru",
  "title": "₹25 back on ₹300", "description": "...", "category": "grocery",
  "cashback_cents": 2500, "budget_cents": 100000, "spent_cents": 40000,
  "min_purchase_cents": 30000, "per_user_limit": 1, "starts_at": "...", "ends_at": "..." } ],
  "page": 1, "page_size": 20, "total": 42 }
```

(`reserved_cents` is internal and not exposed.)

### 3.7 `POST /retailer/offers`

Request:

```json
{ "merchant_name": "FreshMart", "merchant_address": "12 MG Road, Bengaluru", "title": "₹25 back on ₹300",
  "description": "Shop for ₹300 or more", "category": "grocery", "cashback_cents": 2500,
  "budget_cents": 100000, "min_purchase_cents": 30000, "per_user_limit": 1, "ends_at": "2026-12-31T23:59:59Z" }
```

→ `201` offer. `owner_id` is taken from the session. Errors: `400 ends_after_start`, `400 cashback_out_of_range`, `400 budget_exceeded_input`, etc.

### 3.8 `PATCH /retailer/offers/{offerId}`

Only `title`, `description`, `merchant_address`, `budget_cents`, `ends_at`, `active` are accepted — **cashback amount and merchant name are frozen after creation** (existing rule). Budget may not be set below `reserved + spent`. → `200`; `404` if not owned by the caller.

### 3.9 `GET /retailer/offers/stats` → `200`

```json
{ "items": [ { "offer_id": "uuid", "claims": 12, "approved": 10, "rejected": 2, "approved_total_cents": 25000 } ] }
```

No shopper identities returned (existing privacy rule).

---

## Module 4 — Receipt claims (receipt verification)

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 4.1 | `POST /claims/receipts` | Submit a receipt claim | bearer (shopper) | `receipts`, `offers`, `wallet_ledger`, `notifications`, `rate_limit_events` |
| 4.2 | `GET /claims/receipts` | Own claim history | bearer | `receipts`, `offers` |
| 4.3 | `GET /claims/receipts/{receiptId}` | Own claim detail | bearer | `receipts`, `offers` |

### 4.1 `POST /claims/receipts`

Request:

```json
{ "offer_id": "uuid", "merchant_name": "FreshMart", "purchase_date": "2026-11-15",
  "total_cents": 35000, "receipt_number": "FM-2026-88123", "card_last4": "4242" }
```

Response `201` (claim accepted — approved or business-rejected):

```json
{ "id": "uuid", "offer_id": "uuid", "status": "APPROVED", "cashback_cents": 2500,
  "rejection_reason": null, "submitted_at": "..." }
```

**Business-rejection** (validation passed, rule failed) still returns `201` with `status: "REJECTED"`, `cashback_cents: 0`, and a user-readable `rejection_reason` — matching `submit_receipt`'s friendly-rejection contract. Possible reasons: `offer_inactive`, `outside_offer_window`, `purchase_date_outside_offer`, `merchant_name_mismatch`, `below_minimum_purchase`, `duplicate_receipt`, `user_limit_reached`, `offer_budget_exhausted`.

Errors: `400 invalid_input` (malformed fields — no row created), `404 offer_not_found`, `429 rate_limited` (12 submissions/user/hour; includes `retry_after_seconds`).

**Transaction logic (single commit):** lock offer row → re-check budget → insert receipt (`APPROVED` w/ cashback or `REJECTED` w/ reason) → on approval increment `offers.spent_cents` → insert idempotent `wallet_ledger` credit (`reference_key = receipt:<id>`) → insert notification → insert `rate_limit_events` row. A lost duplicate-fingerprint race is converted to the friendly `duplicate_receipt` rejection, never a 500.

### 4.2 `GET /claims/receipts`

Query: `page`, `page_size`, `status` filter. → `200` paged list, newest first, each with `offer_title`. `404` on another user's receipt id (ownership enforced in the query).

---

## Module 5 — Wallet & payouts

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 5.1 | `GET /wallet/balance` | Available balance | bearer | `wallet_ledger`, `payout_entries` |
| 5.2 | `GET /wallet/ledger` | Own ledger history | bearer | `wallet_ledger` |
| 5.3 | `POST /wallet/payouts` | Request payout of full available balance | bearer (shopper) | `payouts`, `wallet_ledger`, `payout_entries` |
| 5.4 | `GET /wallet/payouts` | Own payout history | bearer | `payouts` |
| 5.5 | `GET /wallet/payouts/{payoutId}/entries` | Ledger rows in own payout | bearer | `payout_entries`, `wallet_ledger` |

### 5.1 `GET /wallet/balance` → `200`

```json
{ "available_cents": 12500, "pending_payout_cents": 0, "lifetime_earned_cents": 45000 }
```

Available = sum of ledger rows not linked to a payout (existing `my_wallet_balance_cents` definition). `pending_payout_cents` = sum of rows linked to the open payout, when one exists.

### 5.2 `GET /wallet/ledger` → `200` (paged, newest first)

```json
{ "items": [ { "id": "uuid", "entry_type": "RECEIPT_CASHBACK", "amount_cents": 2500,
  "description": "FreshMart cashback", "source_id": "uuid", "created_at": "..." } ] }
```

### 5.3 `POST /wallet/payouts`

Requires the `Idempotency-Key` header (8–64 characters, letters/digits/`.`/`_`/`-`). A network retry with the same key returns the original payout (`201`) instead of creating a second one; keys are scoped per user.

Request:

```json
{ "method": "UPI", "upi_id": "himakar@upi" }
```

`method` `UPI` (valid UPI id required) or `CASH` (`upi_id` must be omitted). Response `201`:

```json
{ "id": "uuid", "method": "UPI", "amount_cents": 12500, "status": "REQUESTED", "idempotency_key": "...", "requested_at": "..." }
```

Errors: `422` for a missing/invalid idempotency key, `409 payout_already_requested`, `422 below_minimum` (500-cent minimum), `422 nothing_to_payout`.

**Transaction logic:** replay lookup by `(user_id, idempotency_key)` → advisory lock on the user (serializes concurrent requests, replacing the profile-row lock) → reject a second open payout (also guarded by the partial unique index) → select unlinked ledger rows `FOR UPDATE` → link them via `payout_entries` → amount = linked sum → insert payout with the key. A concurrent same-key race is resolved by the `(user_id, idempotency_key)` unique index and replayed. `204`-style errors for negative sums are impossible by ledger invariants.

---

## Module 6 — Referrals

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 6.1 | `POST /referrals/redeem` | Apply another user's referral code | bearer | `users`, `referral_bonuses`, `wallet_ledger` |
| 6.2 | `GET /referrals/bonuses` | Own referral bonuses | bearer | `referral_bonuses` |

### 6.1 `POST /referrals/redeem`

Request `{ "code": "VK3F8Q2A" }` → `200` `{ "bonus_cents": 500 }`. Errors: `404 code_not_found`, `409 self_referral`, `409 mutual_referral`, `409 already_redeemed`, `422 referral_limit` (20-invite cap).

**Transaction logic:** resolve code → checks → insert both `referral_bonuses` rows (invitee `INVITE_ACCEPTED`, inviter `INVITE_SENT`) → insert both ledger credits (`reference_key = referral_bonus:<bonus_id>`). 500 cents per side (existing design).

---

## Module 7 — Notifications & push

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 7.1 | `GET /notifications` | Inbox | bearer | `notifications` |
| 7.2 | `PATCH /notifications/read` | Mark notifications read | bearer | `notifications` |
| 7.3 | `POST /push/subscriptions` | Register/refresh a push subscription | bearer | `push_subscriptions` |
| 7.4 | `DELETE /push/subscriptions/{endpoint}` | Remove a subscription | bearer | `push_subscriptions` |
| 7.5 | `POST /internal/push/dispatch` | Worker entry point | service token only | `notifications`, `push_subscriptions` |

### 7.1 `GET /notifications` → `200` (paged, newest first; client caps at 50 today)

```json
{ "items": [ { "id": "uuid", "kind": "RECEIPT_APPROVED", "receipt_id": "uuid",
  "merchant_name": "FreshMart", "cashback_cents": 2500, "read_at": null, "created_at": "..." } ],
  "unread_count": 3 }
```

### 7.2 `PATCH /notifications/read`

Request `{ "ids": ["uuid", "..."] }` → `200` `{ "updated": 2 }`. Only `read_at` is writable (existing column grant), only on own rows, only when currently unread.

### 7.3 `POST /push/subscriptions`

Request `{ "endpoint": "https://push…", "p256dh": "...", "auth_key": "..." }` → `204`. Endpoint must be HTTPS ≤ 2048 chars; keys ≤ 256 chars; upsert on endpoint; owner always taken from the session (existing `register_push_subscription` rules).

### 7.5 `POST /internal/push/dispatch`

Server-only (bearer = internal service token, never public). Request `{ "notification_id": "uuid" }`. Sends Web Push (24 h TTL) to the user's subscriptions, prunes endpoints answering 404/410, sets `pushed_at`. Idempotent: skipped if `pushed_at` set. Text never exposes cashback amounts (existing privacy rule). Responses: `200` `{ "sent": 2, "removed": 0, "failed": 0 }`, `404` unknown id, `401` bad token.

---

## Module 8 — Todos (planner)

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 8.1 | `GET /todos` | List own todos in a month | bearer | `todos` |
| 8.2 | `POST /todos` | Create a todo | bearer | `todos` |
| 8.3 | `PATCH /todos/{todoId}` | Toggle complete / edit | bearer | `todos` |
| 8.4 | `DELETE /todos/{todoId}` | Delete a todo | bearer | `todos` |

8.1 query: `month=2026-11` (defaults to current month) → items ordered by `created_at` ascending. 8.2 request `{ "title": "…1–200 chars", "due_on": "2026-11-25" }` → `201`. 8.3 accepts `{ "completed": true }` and/or `{ "title", "due_on" }` → `200`. All owner-scoped; `404` on foreign ids.

---

## Module 9 — Support

| # | Method & route | Purpose | Auth | Tables |
|---|---|---|---|---|
| 9.1 | `GET /support-requests` | Own requests | bearer | `support_requests` |
| 9.2 | `POST /support-requests` | Create a request | bearer | `support_requests` |
| 9.3 | `PATCH /admin/support-requests/{id}` | Update status | admin | `support_requests` |

9.2 request `{ "topic": "CASHBACK", "message": "…10–2000 chars" }` → `201` (ownership, status `OPEN`, timestamps server-set). 9.3 *(proposed)* `{ "status": "ANSWERED" }` → `200`.

---

## Module 10 — Admin

All require `user_roles` membership. `admin` covers 10.1–10.5; `super_admin` additionally covers 10.6–10.8 (customer-level reporting, existing restriction).

| # | Method & route | Purpose | Tables |
|---|---|---|---|
| 10.1 | `GET /admin/analytics/overview` | Spending overview by merchant/category | `receipts`, `offers` |
| 10.2 | `GET /admin/payouts` | List all payouts | `payouts`, `users` |
| 10.3 | `GET /admin/payouts/{payoutId}/transactions` | Ledger rows in a payout | `payout_entries`, `wallet_ledger` |
| 10.4 | `POST /admin/payouts/{payoutId}/complete` | Mark payout paid | `payouts`, `audit_log` |
| 10.5 | `POST /admin/payouts/{payoutId}/cancel` | Cancel payout, release ledger links | `payouts`, `payout_entries`, `audit_log` |
| 10.6 | `GET /admin/customers` | Customer summary | `receipts`, `users` |
| 10.7 | `GET /admin/customers/{userId}/merchant-breakdown` | One customer per merchant | `receipts` |
| 10.8 | `GET /admin/customers/{userId}/transactions` | One customer's receipts (≤ 200) | `receipts` |

### 10.1 `GET /admin/analytics/overview` → `200`

```json
{ "items": [ { "merchant_name": "FreshMart", "category": "grocery", "claim_count": 58,
  "spend_cents": 2100000, "cashback_cents": 145000 } ] }
```

### 10.2 `GET /admin/payouts` (query: `status`, default `REQUESTED`) → `200`

```json
{ "items": [ { "id": "uuid", "user_id": "uuid", "full_name": "...", "email": "...", "method": "UPI",
  "upi_id": "...@upi", "amount_cents": 12500, "status": "REQUESTED", "payment_reference": null,
  "note": null, "requested_at": "...", "settled_at": null, "transaction_count": 4 } ] }
```

### 10.4 `POST /admin/payouts/{payoutId}/complete`

Request `{ "payment_reference": "UPIR-99182736" }` (4–64 chars) → `200` payout with `status: "PAID"`. Errors: `409 not_requested` (state machine), `409 reference_in_use` (uniqueness among paid payouts). Writes `audit_log` (`payout.complete`) in the same transaction.

### 10.5 `POST /admin/payouts/{payoutId}/cancel`

Request `{ "reason": "…3–200 chars" }` → `200` payout with `status: "CANCELLED"`. Cancelling deletes the payout's `payout_entries` links (balance restored) without touching ledger history (existing rule). Audit-logged.

### 10.6 `GET /admin/customers` → `200`

```json
{ "items": [ { "user_id": "uuid", "full_name": "...", "email": "...", "claim_count": 12,
  "spend_cents": 96000, "cashback_cents": 25000, "last_purchase_date": "2026-11-14" } ] }
```

10.7 → per-merchant rows for one customer. 10.8 → up to 200 receipt rows for one customer (`receipt_id`, `merchant_name`, `offer_title`, `category`, `purchase_date`, `total_cents`, `cashback_cents`, `status`).

**Fraud-prevention controls in the API surface** (not a separate module): duplicate receipt fingerprint, per-user + per-IP rate limits, one-open-payout rule, payment-reference idempotency, frozen offer economics, reversal state machine, audit log on money-touching admin actions.

---

## Endpoint summary count

44 endpoints across 10 modules: auth 8 · profile 7 · offers/saved 9 · claims 3 · wallet/payouts 5 · referrals 2 · notifications/push 5 · todos 4 · support 3 · admin 8 (module totals include sub-paths as listed above).
