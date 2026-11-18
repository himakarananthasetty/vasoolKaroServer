# VasoolKaro — Database Data Dictionary

Complete column-level reference for the new PostgreSQL schema. Conventions: all money is `bigint` cents; all timestamps are `timestamptz` with `now()` defaults; all primary keys are `uuid` unless marked identity. `DEF` = server-generated default.

## users

One row per account — identity, credentials, profile, preferences, account state. Consolidates Supabase `auth.users` + `profiles`.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Account id (UUIDv7). |
| `email` | citext | NO | — | UNIQUE | Canonical lowercase email. Case-insensitive unique. |
| `password_hash` | text | NO | — | — | Argon2id hash. Never returned by any API. |
| `full_name` | varchar(120) | YES | — | — | Display name. |
| `account_type` | ENUM `user_account_type` | NO | `'shopper'` | IN (shopper, retailer) | Account kind. |
| `business_name` | varchar(80) | YES* | — | 2–80 chars when retailer | Retailer business name. *Required when `account_type='retailer'` (CHECK). |
| `phone_number` | varchar(20) | YES | — | regex `^\+?[0-9 ()-]{7,20}$` | Optional phone. |
| `date_of_birth` | date | YES | — | age ≥ 13; set-once | Locked after first set. |
| `address` | varchar(200) | YES | — | — | Optional address. |
| `avatar_path` | text | YES | — | — | Object-storage path of the avatar. |
| `referral_code` | varchar(8) | NO | gen | UNIQUE, immutable | Server-generated referral code. |
| `referred_by` | uuid | YES | — | FK → users.id ON DELETE SET NULL | Inviting user. |
| `notify_offers` | boolean | NO | `true` | — | Offer alert preference. |
| `notify_receipts` | boolean | NO | `true` | — | Receipt alert preference. |
| `marketing_opt_in` | boolean | NO | `false` | — | Marketing preference. |
| `personalised_offers` | boolean | NO | `true` | — | Personalisation preference. |
| `deactivated_at` | timestamptz | YES | — | — | Set by deactivation, cleared on reactivate. |
| `deleted_at` | timestamptz | YES | — | — | Soft-delete marker (anonymized account). |
| `created_at` | timestamptz | NO | `now()` | — | Creation time. |
| `updated_at` | timestamptz | NO | `now()` | trigger-maintained | Last update time. |

Indexes: `uq_users_email (email)` unique, `uq_users_referral_code (referral_code)` unique, `idx_users_referred_by (referred_by)`.

## user_roles

Server-controlled admin roles.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `user_id` | uuid | NO | — | PK part, FK → users.id CASCADE | Admin user. |
| `role` | ENUM `admin_role` | NO | — | PK part; IN (admin, super_admin) | Role level. |
| `granted_at` | timestamptz | NO | `now()` | — | Grant time. |

Indexes: PK `(user_id, role)`; `idx_user_roles_role (role)`.

## sessions

Refresh-token registry (one row per logged-in device).

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Session id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Owner. |
| `token_hash` | bytea | NO | — | UNIQUE | SHA-256 of the refresh token. Raw token never stored. |
| `user_agent` | text | YES | — | — | Device description at login. |
| `ip_address` | inet | YES | — | — | Login IP. |
| `expires_at` | timestamptz | NO | — | — | Refresh token expiry (30 d). |
| `revoked_at` | timestamptz | YES | — | — | Set on logout/revoke. |
| `last_used_at` | timestamptz | YES | — | — | Last refresh use. |
| `created_at` | timestamptz | NO | `now()` | — | Login time. |

Indexes: `uq_sessions_token_hash (token_hash)` unique; `idx_sessions_user_active (user_id) WHERE revoked_at IS NULL`.

## password_reset_tokens

Single-use recovery tokens.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Token row id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Account. |
| `token_hash` | bytea | NO | — | UNIQUE | SHA-256 of the emailed token. |
| `expires_at` | timestamptz | NO | — | — | 1-hour validity. |
| `used_at` | timestamptz | YES | — | — | Set on successful use (single use). |
| `created_at` | timestamptz | NO | `now()` | — | Request time. |

Indexes: `uq_prt_token_hash (token_hash)` unique; `idx_prt_user (user_id, created_at)`.

## offers

Cashback offers with budgets, owned by retailers.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Offer id. |
| `owner_id` | uuid | YES | — | FK → users.id ON DELETE SET NULL | Retailer owner (null = admin-managed/seeded). |
| `merchant_name` | varchar(80) | NO | — | — | Store name. Immutable after creation (service rule). |
| `merchant_address` | varchar(140) | YES | — | 5–140 chars when present | Address for offer/map display. |
| `title` | varchar(120) | NO | — | — | Offer title. |
| `description` | text | NO | — | — | Offer description. |
| `category` | varchar(40) | NO | — | CHECK in known set | UI category (grocery, dining, retail, outdoors, health, fuel, electronics, other). |
| `cashback_cents` | bigint | NO | — | 1–5000 | Cashback per approved claim. Immutable after creation. |
| `budget_cents` | bigint | NO | — | > 0 | Maximum offer budget. |
| `reserved_cents` | bigint | NO | `0` | ≥ 0 | Reserved amount (retained from current model). |
| `spent_cents` | bigint | NO | `0` | ≥ 0 | Committed by approved claims. |
| `min_purchase_cents` | bigint | NO | `0` | 0–10,000,000 | Minimum receipt total. |
| `per_user_limit` | smallint | NO | `1` | 1–100 | Max qualifying claims per user. |
| `starts_at` | timestamptz | NO | — | — | Offer start. |
| `ends_at` | timestamptz | NO | — | `ends_at > starts_at` | Offer end. |
| `active` | boolean | NO | `true` | — | Whether the offer can be selected. |
| `created_at` | timestamptz | NO | `now()` | — | Creation time. |
| `updated_at` | timestamptz | NO | `now()` | trigger-maintained | Last update time. |

Indexes: `idx_offers_browse (active, ends_at)`; `idx_offers_owner (owner_id)`; CHECK `chk_offers_budget (reserved_cents + spent_cents <= budget_cents)`.

## receipts

One submitted receipt claim and its state machine.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Claim id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Shopper. |
| `offer_id` | uuid | NO | — | FK → offers.id (RESTRICT) | Claimed offer. |
| `merchant_name` | varchar(80) | NO | — | 2–80 chars | Merchant as submitted. |
| `purchase_date` | date | NO | — | not in future; within offer window | Date on receipt. |
| `total_cents` | bigint | NO | — | > 0, ≤ 10,000,000 | Receipt total. |
| `receipt_number` | varchar(40) | NO | — | 3–40 chars | Receipt identifier. |
| `card_last4` | varchar(4) | YES | — | exactly 4 digits when present | Optional card suffix. |
| `fingerprint` | bytea | NO | — | UNIQUE partial (`WHERE status <> 'REJECTED'`) | SHA-256 of the normalized duplicate key. |
| `status` | ENUM `receipt_status` | NO | `'SUBMITTED'` | IN (SUBMITTED, REVIEWING, APPROVED, PAID, REJECTED, REVERSED) | Claim state. |
| `cashback_cents` | bigint | NO | `0` | ≥ 0 | Awarded cashback. |
| `rejection_reason` | text | YES | — | required when REJECTED | User-readable reason. |
| `submitted_at` | timestamptz | NO | `now()` | — | Submission time. |
| `decided_at` | timestamptz | YES | — | — | Decision time. |

Indexes: `uq_receipts_fingerprint_live (fingerprint) WHERE status <> 'REJECTED'`; `idx_receipts_user_submitted (user_id, submitted_at DESC)`; `idx_receipts_offer_status (offer_id, status)`.

## wallet_ledger

Append-only financial ledger. Rows are never updated or deleted (trigger-enforced).

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Ledger row id. |
| `user_id` | uuid | NO | — | FK → users.id RESTRICT | Wallet owner. |
| `entry_type` | ENUM `ledger_entry_type` | NO | — | IN (RECEIPT_CASHBACK, REFERRAL_BONUS, REVERSAL) | Movement kind. |
| `amount_cents` | bigint | NO | — | credits > 0 & reversal_of NULL; reversals < 0 & reversal_of NOT NULL | Signed amount. |
| `source_id` | uuid | YES | — | — | Receipt or referral bonus id (or original ledger row for a reversal). |
| `reference_key` | varchar(120) | NO | — | UNIQUE | Idempotency key, e.g. `receipt:<uuid>`. |
| `description` | varchar(200) | YES | — | — | Human-readable explanation. |
| `transaction_id` | uuid | YES | — | — | Groups rows of one business event. |
| `reversal_of` | uuid | YES | — | FK → wallet_ledger.id | Original row for reversals. |
| `created_at` | timestamptz | NO | `now()` | — | Entry time. |

Indexes: `uq_ledger_reference_key (reference_key)` unique; `idx_ledger_user_created (user_id, created_at DESC)`. Trigger `wallet_ledger_immutable` raises on `UPDATE`/`DELETE`.

## payouts

Shopper cash-out requests settled by admins.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Payout id. |
| `user_id` | uuid | NO | — | FK → users.id RESTRICT | Requester. |
| `method` | ENUM `payout_method` | NO | — | IN (UPI, CASH) | Settlement channel. |
| `upi_id` | varchar(100) | YES* | — | required iff UPI; UPI-format CHECK | UPI address. *CHECK `(method='UPI') = (upi_id IS NOT NULL)`. |
| `amount_cents` | bigint | NO | — | > 0 | Amount. |
| `status` | ENUM `payout_status` | NO | `'REQUESTED'` | IN (REQUESTED, PAID, CANCELLED) | State. |
| `payment_reference` | varchar(64) | YES* | — | required iff PAID, unique when PAID | External payment reference. |
| `note` | varchar(200) | YES* | — | required iff CANCELLED | Cancellation reason. |
| `requested_at` | timestamptz | NO | `now()` | — | Request time. |
| `settled_at` | timestamptz | YES* | — | NULL iff REQUESTED | Settlement time. |

Indexes: `uq_payouts_one_open (user_id) WHERE status = 'REQUESTED'`; `uq_payouts_reference_paid (payment_reference) WHERE status = 'PAID'`; `idx_payouts_user_requested (user_id, requested_at DESC)`; `idx_payouts_open (status) WHERE status = 'REQUESTED'`.

## payout_entries

Ledger-to-payout links. `ledger_id` is the PK: one ledger row links to at most one payout.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `ledger_id` | uuid | NO | — | PK, FK → wallet_ledger.id CASCADE | Settled ledger row. |
| `payout_id` | uuid | NO | — | FK → payouts.id CASCADE | Settling payout. |

Indexes: PK; `idx_payout_entries_payout (payout_id)`.

## referral_bonuses

Immutable referral reward records.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Bonus id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Receiving user. |
| `amount_cents` | bigint | NO | — | > 0 | Bonus amount (500 today). |
| `reason` | ENUM `referral_reason` | NO | — | IN (INVITE_ACCEPTED, INVITE_SENT) | Which side of the referral. |
| `counterpart_id` | uuid | NO | — | FK → users.id | Other user in the pair. |
| `created_at` | timestamptz | NO | `now()` | — | Award time. |

Indexes: `uq_referral_pair (user_id, counterpart_id, reason)` unique partial (no double awarding); `idx_referral_user (user_id, created_at)`.

## saved_offers

Shopper bookmarks.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Save id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Owner. |
| `offer_id` | uuid | NO | — | FK → offers.id CASCADE | Saved offer. |
| `created_at` | timestamptz | NO | `now()` | — | Save time. |

Indexes: `uq_saved_offers (user_id, offer_id)` unique; `idx_saved_offers_offer (offer_id)`.

## notifications

In-app receipt-outcome alerts.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Notification id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Owner. |
| `kind` | ENUM `notification_kind` | NO | — | IN (RECEIPT_APPROVED, RECEIPT_REJECTED) | Outcome kind. |
| `receipt_id` | uuid | NO | — | FK → receipts.id CASCADE | Related claim. |
| `merchant_name` | varchar(80) | NO | — | — | Merchant shown in the alert. |
| `cashback_cents` | bigint | NO | — | ≥ 0 | Amount stored for the in-app record. |
| `read_at` | timestamptz | YES | — | — | Null until marked read. |
| `pushed_at` | timestamptz | YES | — | — | Set after a push attempt (never pushed twice). |
| `created_at` | timestamptz | NO | `now()` | — | Creation time. |

Indexes: `uq_notifications_receipt_kind (receipt_id, kind)` unique; `idx_notifications_user (user_id, created_at DESC)`.

## push_subscriptions

Web Push endpoints per device.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Subscription id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Owner. |
| `endpoint` | text | NO | — | UNIQUE, HTTPS, ≤ 2048 chars | Browser push endpoint. |
| `p256dh` | varchar(256) | NO | — | — | Web Push encryption key. |
| `auth_key` | varchar(256) | NO | — | — | Web Push auth key. |
| `created_at` | timestamptz | NO | `now()` | — | Registration time. |

Indexes: `uq_push_endpoint (endpoint)` unique; `idx_push_user (user_id)`.

## support_requests

Shopper messages to support.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Request id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Author. |
| `topic` | ENUM `support_topic` | NO | — | IN (ACCOUNT, CASHBACK, OFFERS, OTHER) | Topic. |
| `message` | varchar(2000) | NO | — | 10–2000 chars after trim | Message body. |
| `status` | ENUM `support_status` | NO | `'OPEN'` | IN (OPEN, ANSWERED, CLOSED) | State (admin-controlled). |
| `created_at` | timestamptz | NO | `now()` | — | Created. |
| `updated_at` | timestamptz | NO | `now()` | trigger-maintained | Last change. |

Indexes: `idx_support_user (user_id, created_at DESC)`; `idx_support_status (status, created_at)`.

## todos

Private planner items.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | uuid | NO | gen | PK | Todo id. |
| `user_id` | uuid | NO | — | FK → users.id CASCADE | Owner. |
| `title` | varchar(200) | NO | — | 1–200 chars after trim | Item text. |
| `due_on` | date | NO | — | — | Planned date. |
| `completed` | boolean | NO | `false` | — | Done flag. |
| `created_at` | timestamptz | NO | `now()` | — | Created. |

Indexes: `idx_todos_user_due (user_id, due_on)`.

## rate_limit_events

Durable sliding-window rate limiter (replaces `submit_log`).

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | bigint identity | NO | gen | PK | Event id. |
| `subject_kind` | varchar(20) | NO | — | IN (user, ip) | Subject type. |
| `subject_id` | text | NO | — | — | User uuid or IP literal. |
| `action` | varchar(40) | NO | — | — | Limited action, e.g. `receipt_submit`. |
| `occurred_at` | timestamptz | NO | `now()` | — | Attempt time. |

Indexes: `idx_rle_window (action, subject_kind, subject_id, occurred_at)`.

## audit_log

Privileged-action trail.

| Column | Type | Null | Default | Constraints | Meaning |
|---|---|---|---|---|---|
| `id` | bigint identity | NO | gen | PK | Entry id. |
| `actor_user_id` | uuid | YES | — | FK → users.id SET NULL | Acting user (null = system). |
| `actor_kind` | varchar(20) | NO | — | IN (user, admin, system) | Actor class. |
| `action` | varchar(60) | NO | — | — | e.g. `payout.complete`, `receipt.reverse`. |
| `entity_type` | varchar(40) | NO | — | — | e.g. `payout`, `receipt`. |
| `entity_id` | text | NO | — | — | Affected entity id. |
| `detail` | jsonb | NO | `'{}'` | — | Action details (no secrets). |
| `created_at` | timestamptz | NO | `now()` | — | When it happened. |

Indexes: `idx_audit_entity (entity_type, entity_id)`; `idx_audit_actor (actor_user_id, created_at DESC)`.

## Enum types

| Enum | Values |
|---|---|
| `user_account_type` | shopper, retailer |
| `admin_role` | admin, super_admin |
| `receipt_status` | SUBMITTED, REVIEWING, APPROVED, PAID, REJECTED, REVERSED |
| `ledger_entry_type` | RECEIPT_CASHBACK, REFERRAL_BONUS, REVERSAL |
| `payout_method` | UPI, CASH |
| `payout_status` | REQUESTED, PAID, CANCELLED |
| `referral_reason` | INVITE_ACCEPTED, INVITE_SENT |
| `notification_kind` | RECEIPT_APPROVED, RECEIPT_REJECTED |
| `support_topic` | ACCOUNT, CASHBACK, OFFERS, OTHER |
| `support_status` | OPEN, ANSWERED, CLOSED |
