# VasoolKaro — Independent Database Design

**Target stack:** self-hosted PostgreSQL 16 + SQLAlchemy 2.0 ORM + Alembic migrations, consumed by the new FastAPI backend. **No Supabase dependency** — no `auth.uid()`, no RLS, no PostgREST, no Supabase Storage, no `pg_net` triggers.

**Source of truth for the analysis of the existing system:** `BACKEND_HANDOFF.md` (snapshot 2026-11-17) and `DATA_MODEL.md`. The live production Supabase database was not connected to this workspace; it was not modified and must not be.

---

## 1. Design principles

| Principle | How it is applied |
|---|---|
| Money is exact | All amounts are `BIGINT` cents. No floats anywhere. `BIGINT` (proposed upgrade from the current `integer`) removes the 2,147,483,647-cent ceiling on totals. |
| Financial history is append-only | `wallet_ledger` rows can never be updated or deleted (DB trigger + revoked grants). Corrections are new rows. |
| Atomic money operations | Receipt approval + budget consumption + ledger credit commit in **one transaction** with `SELECT ... FOR UPDATE` on the offer row. Payout request links ledger entries and inserts the payout in one transaction with a profile-level advisory lock. |
| Idempotency at the database level | `reference_key` (ledger), receipt fingerprint (partial unique index), payment reference (partial unique index), one-open-payout (partial unique index) — the same guarantees the old RLS+RPC design achieved, kept as declarative constraints. |
| Authorization moves to the backend | RLS is replaced by a deny-by-default service layer: every query is scoped by `current_user.id` taken from a verified access token, never from a request body. The database user the app connects with has only table-level grants; ownership checks live in repositories. |
| Triggers → service code (mostly) | Profile creation, receipt→wallet credit, receipt→notification, referral→wallet credit become explicit service-layer steps inside the same transaction. Kept as DB triggers only: ledger immutability and the `updated_at` touch (deterministic, data-integrity critical). Push dispatch moves from a `pg_net` trigger to a durable background job with retries. |
| Identity is app-owned | `auth.users` + `profiles` are consolidated into one `users` table plus a `sessions` table. One row per account, one join fewer everywhere. |
| Scalable by default | UUID v7 primary keys (time-ordered, index-friendly), covering indexes for every hot query path, enum-typed statuses, and a generalized rate-limit table. |

### What is deliberately NOT copied

| Supabase mechanism | Replacement |
|---|---|
| `auth.users` / Auth client SDK | `users` table + argon2id password hashes + JWT access tokens + opaque hashed refresh tokens in `sessions` |
| RLS policies + column grants | Repository-level scoping + Pydantic write-schemas that only accept allowed fields + least-privilege DB grants |
| `SECURITY DEFINER` RPCs | Plain service functions called by routers inside an explicit transaction |
| Auth signup trigger → `profiles` | Profile/row created in the same registration transaction |
| `pg_net` + Vault push dispatch | Background worker job (durable, retryable, `pushed_at` guard preserved) |
| Storage bucket `avatars` | Local/ S3-compatible object storage behind a backend upload endpoint; DB stores only the object path |
| `submit_log` | Generalized `rate_limit_events` (per subject, still DB-backed so it works across API instances) |

---

## 2. Table catalog

Each entry uses the required documentation format. Tables marked **[new]** do not exist in Supabase; tables marked **[redesigned]** exist but changed materially. All others remain conceptually unchanged (details in `SUPABASE_TO_POSTGRES_MAPPING.md`).

---

### 2.1 `users` [redesigned — consolidates `auth.users` + `profiles`]

| Field | Value |
|---|---|
| **Table Name** | `users` |
| **Purpose** | One row per account: identity, credentials, profile details, notification preferences, and account state. |
| **Business Logic** | Registration, login, profile editing, preference management, deactivation/reactivation, deletion. Enforces age ≥ 13, date-of-birth set-once, retailer business-name requirement, referral code ownership. |
| **Columns** | `id`, `email`, `password_hash`, `full_name`, `account_type`, `business_name`, `phone_number`, `date_of_birth`, `address`, `avatar_path`, `referral_code`, `referred_by`, `notify_offers`, `notify_receipts`, `marketing_opt_in`, `personalised_offers`, `deactivated_at`, `deleted_at`, `created_at`, `updated_at` |
| **Data Types** | `id uuid pk`; `email citext unique not null`; `password_hash text not null`; `full_name text`; `account_type user_account_type enum not null default 'shopper'`; `business_name text`; `phone_number text`; `date_of_birth date`; `address varchar(200)`; `avatar_path text`; `referral_code varchar(8) unique not null` (server-generated, immutable); `referred_by uuid fk → users.id`; preference flags `boolean not null`; `deactivated_at timestamptz`; `deleted_at timestamptz` (soft-delete marker; hard delete only via the deletion workflow); `created_at`/`updated_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `referred_by → users.id ON DELETE SET NULL` (self-referential) |
| **Indexes** | unique on `email`; unique on `referral_code`; `idx_users_referred_by (referred_by)` |
| **Used By** | `POST /api/v1/auth/*`, `GET/PATCH /me`, `POST /me/deactivate|reactivate|delete`, `POST /referrals/redeem`, every ownership-scoped endpoint |

**Constraints (application + DB):**

- `email` canonicalized to lowercase before insert; uniqueness is case-insensitive via `citext`.
- `account_type ∈ {shopper, retailer}`; `business_name` required (2–80 chars) when `account_type = 'retailer'`.
- `date_of_birth`, once set, is immutable (enforced in the update service; DB CHECK `chk_users_dob_age`: `date_of_birth IS NULL OR date_of_birth <= current_date - interval '13 years'`).
- `phone_number` matches `^\+?[0-9 ()-]{7,20}$` when present.
- Client-updatable fields (via `PATCH /me`) are only: `full_name`, `phone_number`, `date_of_birth` (while empty), `address`, and the four preference flags. Email, password, account type, referral fields, and state columns are server-controlled.

### 2.2 `user_roles` [new]

| Field | Value |
|---|---|
| **Table Name** | `user_roles` |
| **Purpose** | Server-controlled administrative roles, replacing the `profiles.admin_level` column. |
| **Business Logic** | Grants `admin` (payout management, spending reports) or `super_admin` (customer-level reports). Roles are granted/revoked by operators directly in the database or a CLI script — never through the API, never through user-editable metadata. |
| **Columns** | `user_id`, `role`, `granted_at` |
| **Data Types** | `user_id uuid not null`; `role admin_role enum not null` (`admin`, `super_admin`); `granted_at timestamptz not null default now()` |
| **Primary Key** | `(user_id, role)` composite |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | PK covers `(user_id, role)`; `idx_user_roles_role (role)` for listing admins |
| **Used By** | All `/api/v1/admin/*` endpoints (role check middleware), `POST /internal/push/send` (service-token auth, not this table) |

### 2.3 `sessions` [new]

| Field | Value |
|---|---|
| **Table Name** | `sessions` |
| **Purpose** | Refresh-token store and session registry, replacing Supabase Auth session handling. |
| **Business Logic** | Login issues an access JWT (15 min) plus an opaque refresh token (30 days) stored only as a SHA-256 hash. Supports sign-out (single session), sign-out-everywhere-else, and revocation on password change or account deletion. |
| **Columns** | `id`, `user_id`, `token_hash`, `user_agent`, `ip_address`, `expires_at`, `revoked_at`, `last_used_at`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `token_hash bytea not null` (sha-256 digest); `user_agent text`; `ip_address inet`; `expires_at timestamptz not null`; `revoked_at timestamptz`; `last_used_at timestamptz`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | unique on `token_hash`; `idx_sessions_user_active (user_id) WHERE revoked_at IS NULL` |
| **Used By** | `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-other-sessions`, `POST /auth/password/change`, `POST /me/delete` |

### 2.4 `password_reset_tokens` [new — closes a known gap]

| Field | Value |
|---|---|
| **Table Name** | `password_reset_tokens` |
| **Purpose** | Single-use tokens for the password-recovery email flow (the current product has none — this is the explicit recovery endpoint the handoff recommends adding). |
| **Business Logic** | Request creates a random token (hashed at rest, 1-hour expiry). Confirm verifies the token, sets the new password, revokes all sessions, marks the token used. |
| **Columns** | `id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `token_hash bytea not null`; `expires_at timestamptz not null`; `used_at timestamptz`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | unique on `token_hash`; `(user_id, created_at)` |
| **Used By** | `POST /auth/password/recovery`, `POST /auth/password/recovery/confirm` |

### 2.5 `offers`

Conceptually unchanged. See `SUPABASE_TO_POSTGRES_MAPPING.md` for the money-type change and audit column.

| Field | Value |
|---|---|
| **Table Name** | `offers` |
| **Purpose** | A retailer-created cashback offer with its own budget. |
| **Business Logic** | Public catalog for shoppers; budget accounting (`budget/reserved/spent`); eligibility rules (window, minimum purchase, per-user limit) applied during receipt submission; retailer edit restrictions (cashback amount and merchant identity frozen after creation). |
| **Columns** | `id`, `owner_id`, `merchant_name`, `merchant_address`, `title`, `description`, `category`, `cashback_cents`, `budget_cents`, `reserved_cents`, `spent_cents`, `min_purchase_cents`, `per_user_limit`, `starts_at`, `ends_at`, `active`, `created_at`, `updated_at` |
| **Data Types** | `id uuid pk (uuidv7)`; `owner_id uuid null`; money columns `bigint not null`; `per_user_limit smallint not null default 1`; `merchant_address varchar(140)`; `category varchar(40) not null` (UI-extensible, CHECK-constrained against the known set); `starts_at`/`ends_at timestamptz not null`; `active boolean not null default true`; timestamps |
| **Primary Key** | `id` |
| **Foreign Keys** | `owner_id → users.id ON DELETE SET NULL` (offers outlive a deleted retailer, become admin-managed) |
| **Indexes** | `idx_offers_browse (active, ends_at)` for the shopper catalog; `idx_offers_owner (owner_id)`; CHECK constraints: `ends_at > starts_at`, `cashback_cents BETWEEN 1 AND 5000`, `min_purchase_cents BETWEEN 0 AND 10000000`, `per_user_limit BETWEEN 1 AND 100`, `reserved_cents + spent_cents <= budget_cents` |
| **Used By** | `GET /offers`, `GET /offers/{offerId}`, `POST /retailer/offers`, `PATCH /retailer/offers/{offerId}`, `GET /retailer/offers/stats`, `POST /claims/receipts`, admin analytics |

### 2.6 `receipts`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `receipts` |
| **Purpose** | One submitted receipt claim, and its review/award state machine. |
| **Business Logic** | Created only by the submission service. Statuses: `SUBMITTED → REVIEWING → APPROVED → PAID`, plus `REJECTED` (reason required) and `REVERSED` (cashback clawed back). Auto-approval after validation, as in the current product. |
| **Columns** | `id`, `user_id`, `offer_id`, `merchant_name`, `purchase_date`, `total_cents`, `receipt_number`, `card_last4`, `fingerprint`, `status`, `cashback_cents`, `rejection_reason`, `submitted_at`, `decided_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `offer_id uuid not null`; `merchant_name varchar(80) not null`; `purchase_date date not null`; `total_cents bigint not null`; `receipt_number varchar(40) not null`; `card_last4 varchar(4)`; `fingerprint bytea not null` (sha-256 of the normalized duplicate-detection string — proposed upgrade from MD5); `status receipt_status enum not null default 'SUBMITTED'`; `cashback_cents bigint not null default 0`; `rejection_reason text`; `submitted_at timestamptz not null default now()`; `decided_at timestamptz` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE`; `offer_id → offers.id` (restrict: claims are financial evidence) |
| **Indexes** | unique partial on `fingerprint WHERE status <> 'REJECTED'` (duplicate protection; rejected attempts stay visible in history); `idx_receipts_user_submitted (user_id, submitted_at DESC)`; `idx_receipts_offer_status (offer_id, status)` for retailer stats and budget queries |
| **Used By** | `POST /claims/receipts`, `GET /claims/receipts`, `GET /claims/receipts/{receiptId}`, retailer stats, admin analytics, `POST /internal/receipts/{receiptId}/reverse` |

### 2.7 `wallet_ledger`

Conceptually unchanged — the financial core.

| Field | Value |
|---|---|
| **Table Name** | `wallet_ledger` |
| **Purpose** | Append-only source of truth for every wallet movement: cashback credits, referral bonuses, reversals. |
| **Business Logic** | Credits are positive; reversals are negative and point at the original row. Balance available for payout = sum of rows not yet linked to a payout. Immutability enforced by a `BEFORE UPDATE OR DELETE` trigger that raises. |
| **Columns** | `id`, `user_id`, `entry_type`, `amount_cents`, `source_id`, `reference_key`, `description`, `transaction_id`, `reversal_of`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `entry_type ledger_entry_type enum not null` (`RECEIPT_CASHBACK`, `REFERRAL_BONUS`, `REVERSAL`); `amount_cents bigint not null`; `source_id uuid`; `reference_key varchar(120) unique not null` (e.g. `receipt:<id>`, `referral_bonus:<id>`); `description varchar(200)`; `transaction_id uuid` (groups rows of one business event); `reversal_of uuid` self-FK; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE RESTRICT` (financial records outlive account deletion); `reversal_of → wallet_ledger.id` |
| **Indexes** | unique `reference_key` (idempotency); `idx_ledger_user_created (user_id, created_at DESC)`; `idx_ledger_unlinked (user_id) WHERE id NOT IN (SELECT ledger_id FROM payout_entries)` is replaced by the cheaper anti-join query using `idx_payout_entries_payout`; trigger `wallet_ledger_immutable` raises on any `UPDATE`/`DELETE` |
| **Used By** | receipt submission (credit), referral redemption (credit), reversal, `GET /wallet/balance`, `GET /wallet/ledger`, payout request, admin payout views |

**CHECK invariants:** non-reversal rows: `amount_cents > 0 AND reversal_of IS NULL`; reversal rows: `amount_cents < 0 AND reversal_of IS NOT NULL`.

### 2.8 `payouts`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `payouts` |
| **Purpose** | A shopper's cash-out request, settled by an administrator. |
| **Business Logic** | Shopper requests UPI or cash payout of the full available balance (links all unlinked ledger rows). Minimum 500 cents. At most one `REQUESTED` payout per user. Admin completes (unique payment reference) or cancels (links released, balance restored). |
| **Columns** | `id`, `user_id`, `method`, `upi_id`, `amount_cents`, `status`, `payment_reference`, `note`, `requested_at`, `settled_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `method payout_method enum not null` (`UPI`, `CASH`); `upi_id varchar(100)`; `amount_cents bigint not null`; `status payout_status enum not null default 'REQUESTED'`; `payment_reference varchar(64)`; `note varchar(200)`; `requested_at timestamptz not null default now()`; `settled_at timestamptz` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE RESTRICT` |
| **Indexes** | unique partial `(user_id) WHERE status = 'REQUESTED'` (one open payout); unique partial `(payment_reference) WHERE status = 'PAID'`; `idx_payouts_user_requested (user_id, requested_at DESC)`; `idx_payouts_status (status) WHERE status = 'REQUESTED'` for the admin queue; CHECKs: `amount_cents > 0`, `(method = 'UPI') = (upi_id IS NOT NULL)`, `(status = 'PAID') = (payment_reference IS NOT NULL)`, `(status = 'CANCELLED') = (note IS NOT NULL)`, `(status = 'REQUESTED') = (settled_at IS NULL)` |
| **Used By** | `POST /wallet/payouts`, `GET /wallet/payouts`, `GET /wallet/payouts/{payoutId}/entries`, `GET /admin/payouts`, `POST /admin/payouts/{payoutId}/complete|cancel` |

### 2.9 `payout_entries`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `payout_entries` |
| **Purpose** | Links each ledger row to the payout that settles it, without touching ledger history. |
| **Business Logic** | Created when a payout is requested; deleted when the payout is cancelled (restoring availability). One ledger row can be linked at most once (`ledger_id` PK). |
| **Columns** | `ledger_id`, `payout_id` |
| **Data Types** | `ledger_id uuid pk`; `payout_id uuid not null` |
| **Primary Key** | `ledger_id` |
| **Foreign Keys** | `ledger_id → wallet_ledger.id ON DELETE CASCADE`; `payout_id → payouts.id ON DELETE CASCADE` |
| **Indexes** | PK covers point lookups; `idx_payout_entries_payout (payout_id)` for listing a payout's entries |
| **Used By** | payout request, payout cancel, `GET /wallet/payouts/{payoutId}/entries`, `GET /admin/payouts/{payoutId}/transactions`, available-balance calculation |

### 2.10 `referral_bonuses`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `referral_bonuses` |
| **Purpose** | Immutable record of a referral reward, per side of the referral. |
| **Business Logic** | Created only by the redemption service: both inviter and invitee get 500 cents, no self-referral, no mutual/cyclic referrals, capped invite activity (20). |
| **Columns** | `id`, `user_id`, `amount_cents`, `reason`, `counterpart_id`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `amount_cents bigint not null` (`> 0`); `reason referral_reason enum not null` (`INVITE_ACCEPTED`, `INVITE_SENT`); `counterpart_id uuid not null`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE`; `counterpart_id → users.id` |
| **Indexes** | unique partial `(user_id, counterpart_id, reason)` prevents double-awarding the same referral pair; `(user_id, created_at)` |
| **Used By** | `POST /referrals/redeem`, `GET /referrals/bonuses`, wallet credit service |

### 2.11 `saved_offers`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `saved_offers` |
| **Purpose** | A shopper's bookmarked offers. |
| **Business Logic** | Idempotent save (unique constraint), unsave by offer id. |
| **Columns** | `id`, `user_id`, `offer_id`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `offer_id uuid not null`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE`; `offer_id → offers.id ON DELETE CASCADE` |
| **Indexes** | unique `(user_id, offer_id)`; `(offer_id)` |
| **Used By** | `GET/POST /saved-offers`, `DELETE /saved-offers/{offerId}` |

### 2.12 `notifications`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `notifications` |
| **Purpose** | In-app alert per receipt outcome. |
| **Business Logic** | Created by the receipt service in the same transaction as the status change; one alert per `(receipt, outcome)`; `pushed_at` guards against double push delivery. |
| **Columns** | `id`, `user_id`, `kind`, `receipt_id`, `merchant_name`, `cashback_cents`, `read_at`, `pushed_at`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `kind notification_kind enum not null` (`RECEIPT_APPROVED`, `RECEIPT_REJECTED`); `receipt_id uuid not null`; `merchant_name varchar(80) not null`; `cashback_cents bigint not null`; `read_at timestamptz`; `pushed_at timestamptz`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE`; `receipt_id → receipts.id ON DELETE CASCADE` |
| **Indexes** | unique `(receipt_id, kind)`; `(user_id, created_at DESC)` for the inbox |
| **Used By** | receipt submission, `GET /notifications`, `PATCH /notifications/read`, push dispatch worker |

### 2.13 `push_subscriptions`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `push_subscriptions` |
| **Purpose** | One Web Push subscription per browser/device endpoint. |
| **Business Logic** | Registered/refreshed by authenticated users (upsert on endpoint). Worker sends with 24 h TTL and removes endpoints answering 404/410. |
| **Columns** | `id`, `user_id`, `endpoint`, `p256dh`, `auth_key`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `endpoint text unique not null` (HTTPS, ≤ 2048); `p256dh varchar(256) not null`; `auth_key varchar(256) not null`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | unique `endpoint`; `(user_id)` |
| **Used By** | `POST /push/subscriptions`, `DELETE /push/subscriptions/{endpoint}`, push worker |

### 2.14 `support_requests`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `support_requests` |
| **Purpose** | A shopper's message to support. |
| **Business Logic** | User sets only topic and message; ownership and status are server-controlled; admins update status. |
| **Columns** | `id`, `user_id`, `topic`, `message`, `status`, `created_at`, `updated_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `topic support_topic enum not null` (`ACCOUNT`, `CASHBACK`, `OFFERS`, `OTHER`); `message varchar(2000) not null` (10–2000 after trim); `status support_status enum not null default 'OPEN'`; timestamps |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | `(user_id, created_at DESC)`; `(status, created_at)` for the admin queue |
| **Used By** | `GET/POST /support-requests`, `PATCH /admin/support-requests/{id}` (admin status update) |

### 2.15 `todos`

Conceptually unchanged.

| Field | Value |
|---|---|
| **Table Name** | `todos` |
| **Purpose** | Private planner items shown on the calendar. |
| **Business Logic** | Full owner-scoped CRUD; month-range listing. |
| **Columns** | `id`, `user_id`, `title`, `due_on`, `completed`, `created_at` |
| **Data Types** | `id uuid pk`; `user_id uuid not null`; `title varchar(200) not null` (1–200 after trim); `due_on date not null`; `completed boolean not null default false`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `user_id → users.id ON DELETE CASCADE` |
| **Indexes** | `(user_id, due_on)` for month lookups |
| **Used By** | `GET/POST /todos`, `PATCH/DELETE /todos/{todoId}` |

### 2.16 `rate_limit_events` [redesigned — replaces `submit_log`]

| Field | Value |
|---|---|
| **Table Name** | `rate_limit_events` |
| **Purpose** | Durable, DB-backed sliding-window rate limiting that works across multiple API instances. |
| **Business Logic** | Receipt submissions: max 12 per user per rolling hour (the existing rule). Generalized subject key so the same mechanism can also cover referral redemption and other endpoints without new tables. Old rows are pruned opportunistically. |
| **Columns** | `id`, `subject_kind`, `subject_id`, `action`, `occurred_at` |
| **Data Types** | `id bigint generated always as identity pk`; `subject_kind varchar(20) not null` (`user`, `ip`); `subject_id text not null` (user uuid or IP literal); `action varchar(40) not null` (e.g. `receipt_submit`); `occurred_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | none (by design — keeps limiter writes cheap and avoids user-delete contention) |
| **Indexes** | `(action, subject_kind, subject_id, occurred_at)` — window count and prune are index-only range scans |
| **Used By** | `POST /claims/receipts` (insert + count inside the submission transaction), other abuse-sensitive endpoints |

### 2.17 `audit_log` [new]

| Field | Value |
|---|---|
| **Table Name** | `audit_log` |
| **Purpose** | Tamper-evident record of privileged actions (payout settlement/cancellation, reversals, role grants, account deletions). |
| **Business Logic** | Written by the services performing the action, in the same transaction. Never exposed to end users; queried by super_admin for investigations. |
| **Columns** | `id`, `actor_user_id`, `actor_kind`, `action`, `entity_type`, `entity_id`, `detail`, `created_at` |
| **Data Types** | `id bigint generated always as identity pk`; `actor_user_id uuid null` (null for system jobs); `actor_kind varchar(20) not null` (`user`, `admin`, `system`); `action varchar(60) not null` (e.g. `payout.complete`, `receipt.reverse`); `entity_type varchar(40) not null`; `entity_id text not null`; `detail jsonb not null default '{}'`; `created_at timestamptz not null default now()` |
| **Primary Key** | `id` |
| **Foreign Keys** | `actor_user_id → users.id ON DELETE SET NULL` |
| **Indexes** | `(entity_type, entity_id)`; `(actor_user_id, created_at DESC)` |
| **Used By** | payout completion/cancellation, receipt reversal, admin role changes, account deletion |

---

## 3. Proposed new functionality (clearly separated from existing behavior)

| Proposal | Rationale |
|---|---|
| `sessions` + refresh-token rotation | Handoff requirement §2.4; Supabase did this before. |
| `password_reset_tokens` + recovery endpoints | Handoff §16: password recovery "not implemented" — recommended addition. |
| `user_roles` table | Handoff §9: replace `admin_level` column with a server-controlled role table. |
| `audit_log` | Fintech-grade traceability for money-touching admin actions; supports dispute resolution. |
| `rate_limit_events` generalization + IP subjects | Handoff §11: current limiter is per-user only; adds the IP layer it recommends. |
| `BIGINT` money, SHA-256 fingerprints, `updated_at` on offers/support | Correctness and future-proofing; no behavior change. |
| Admin support-request status endpoint | The old schema had statuses but no documented admin path to change them. |
| `users.deleted_at` soft-delete marker | Lets the deletion workflow anonymize rather than hard-delete when financial history blocks deletion, satisfying retention needs. |

Everything else (offers, receipts, ledger, payouts, referrals, notifications, push, support, todos, deactivation/deletion blockers, rate limits, admin reports) preserves the existing product behavior exactly as documented in `BACKEND_HANDOFF.md`.
