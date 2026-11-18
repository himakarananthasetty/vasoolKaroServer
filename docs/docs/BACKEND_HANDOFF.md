# VasoolKaro Backend Handoff

## Purpose

This document describes the backend that currently powers the VasoolKaro receipt-cashback app. It is intended as a migration specification for rebuilding the backend on another stack.

It documents:

- The authentication and session model.
- The database tables, relationships, constraints, and indexes.
- The HTTP-style APIs exposed by the current backend.
- The database RPC functions that implement business logic.
- Row-level security and write permissions.
- Triggers and asynchronous push notification delivery.
- Customer, retailer, administrator, wallet, payout, reversal, and account-deletion workflows.
- A recommended order for rebuilding the system elsewhere.

This is a behavior and contract handoff, not a database dump. It intentionally contains no passwords, secret values, access tokens, private keys, or user records.

**Current snapshot:** 2026-11-17

## 1. Current backend architecture

The current app does not have a separate Fastify or REST API server in this project. It uses Supabase in three ways:

1. **Supabase Auth**
   - Email/password registration and login.
   - Persistent browser/mobile sessions.
   - Token refresh handled by the Supabase client.

2. **Supabase Data API**
   - Direct authenticated queries against tables in the `public` schema.
   - The client uses the Supabase JavaScript SDK, which calls table endpoints internally.
   - Row-level security and column-level grants determine what each user can see or change.

3. **Postgres RPC functions**
   - Business-critical operations are database functions called through `supabase.rpc(...)`.
   - Receipt submission, wallet credits, referrals, payouts, admin actions, account state changes, and push subscription registration are not trusted to ordinary client inserts.
   - These functions validate the caller with `auth.uid()` and run atomically where money or ownership is involved.

There are also two Supabase Edge Functions:

- `delete-account`: authenticated account-deletion service.
- `send-push`: internal push-delivery service called by a database trigger.

### Current roles

- `anon`: unauthenticated requests. The app should not use this role for protected data.
- `authenticated`: a signed-in app user. RLS policies scope this role to the current user's records or explicitly permitted shared records.
- `service_role`: server-side administrative role. It bypasses RLS and must never be exposed to the client.
- `postgres`: database owner/maintenance role.

The current public data model is single-tenant at the application level but multi-user at the row level: users share the offer catalog, while personal data, claims, wallet records, payouts, notifications, and preferences are owner-scoped.

## 2. Authentication and login API

### 2.1 Account creation

The client calls Supabase Auth email/password signup:

```ts
supabase.auth.signUp({
  email,
  password,
  options: {
    data: {
      full_name,
      account_type,
      business_name,
      date_of_birth,
    },
  },
});
```

The signup metadata is used by the database trigger that creates the matching `profiles` row.

#### Signup input

| Field | Type | Rules |
|---|---|---|
| `email` | string | Trimmed before sending. Must satisfy Supabase Auth email validation. |
| `password` | string | The app requires at least 8 characters. The server dashboard password policy must be kept at least this strong. |
| `full_name` | string | Stored in `profiles.full_name`. |
| `account_type` | `shopper` or `retailer` | Stored in the profile. |
| `business_name` | string or null | Required for retailer accounts by the profile constraint. |
| `date_of_birth` | ISO date string or null | Stored once in the profile. Database prevents changing it after it is set and requires age 13 or older. |

The current client expects signup to return an active session. If email confirmation is enabled in the Supabase dashboard, signup may return no session and the current client reports a signed-up-but-not-signed-in error. A replacement backend must either preserve immediate-session signup or update the client to support a verification-email state.

### 2.2 Automatic profile creation

An `AFTER INSERT` trigger on the built-in `auth.users` table calls `public.handle_new_user()`.

The trigger creates one `profiles` record:

- `profiles.id = auth.users.id`
- `profiles.email = auth.users.email`
- `profiles.full_name = raw_user_meta_data.full_name`
- `profiles.date_of_birth = raw_user_meta_data.date_of_birth`
- Other profile defaults are applied by the table.

The operation is idempotent with `ON CONFLICT (id) DO NOTHING`.

In a replacement stack, create the profile within the same registration transaction or through a reliable post-registration job with retry and uniqueness on the account id.

### 2.3 Login

The client calls:

```ts
supabase.auth.signInWithPassword({ email, password });
```

After a successful login, the app calls `reactivate_my_account()` so a previously deactivated account becomes active again. If reactivation fails, the client signs the user back out and reports an error.

### 2.4 Session restoration

The client creates one Supabase client with:

- `persistSession: true`
- `autoRefreshToken: true`
- `detectSessionInUrl: false`

On app startup it calls `supabase.auth.getSession()` and subscribes to `supabase.auth.onAuthStateChange(...)`. The listener updates the active session and is unsubscribed when the provider unmounts.

Replacement requirements:

- Store refresh tokens securely, not in ordinary application data.
- Refresh access tokens before expiry.
- Revoke refresh tokens when the user signs out or is deleted.
- Do not trust a client-provided user id; derive the user id from the verified access token on every request.
- Handle expired sessions as an unauthenticated state and redirect to login.

### 2.5 Sign out

The client calls:

```ts
supabase.auth.signOut();
```

Other session management calls already used by the app:

```ts
supabase.auth.signOut({ scope: 'others' });
supabase.auth.signOut({ scope: 'local' });
```

- `scope: 'others'` is used to sign out other sessions after a security action.
- `scope: 'local'` is used after successful account deletion so the current client clears its session.

### 2.6 Password and account security APIs

The current client has these operations:

```ts
supabase.auth.signInWithPassword({ email, password: currentPassword });
supabase.auth.updateUser({ password: newPassword });
supabase.auth.signOut({ scope: 'others' });
supabase.rpc('deactivate_my_account');
```

The current client does **not** implement a password-recovery email flow in the inspected source. Add an explicit recovery endpoint and UI when rebuilding if account recovery is required.

### 2.7 Auth error mapping

The client maps common server messages into user-facing messages:

- Already registered/existing account.
- Invalid login credentials.
- Password too short.
- Network/fetch failure.
- Generic authentication failure.

The replacement API should return stable error codes and keep detailed authentication failure reasons out of unauthenticated responses.

## 3. Database schema

All monetary amounts are stored as integer cents. Do not use floating-point values for money.

All ids are UUIDs unless noted otherwise. Timestamps are timezone-aware timestamps. The current database has 14 public tables, all protected by RLS.

### 3.1 `profiles`

One profile per authenticated account. `profiles.id` is also the foreign key to `auth.users.id`.

| Column | Type | Nullable/default | Meaning |
|---|---|---|---|
| `id` | uuid | not null, primary key | Same id as the Auth account. Cascades on account deletion. |
| `email` | text | not null | Signup email copied from Auth. Immutable through client access. |
| `full_name` | text | nullable | Display name. |
| `created_at` | timestamptz | default `now()` | Creation time. |
| `updated_at` | timestamptz | default `now()` | Last profile update time. |
| `referral_code` | text | generated, unique | Code owned by this user. |
| `referred_by` | uuid | nullable | Referring profile id. Self-referential relationship. |
| `account_type` | text | default `shopper` | `shopper` or `retailer`. |
| `business_name` | text | nullable | Required for retailers; 2–80 characters when supplied. |
| `admin_level` | text | nullable | `admin` or `super_admin`. Operator-controlled only. |
| `phone_number` | text | nullable | Optional phone value matching the database format rule. |
| `date_of_birth` | date | nullable | Locked after first set; minimum age is 13. |
| `address` | text | nullable | Optional address, maximum 200 characters. |
| `notify_offers` | boolean | default `true` | Offer notification preference. |
| `notify_receipts` | boolean | default `true` | Receipt notification preference. |
| `marketing_opt_in` | boolean | default `false` | Marketing preference. |
| `personalised_offers` | boolean | default `true` | Personalisation preference. |
| `deactivated_at` | timestamptz | nullable | Set when the account is deactivated. |
| `avatar_path` | text | nullable | Private storage path in the `avatars` bucket. |

Client permissions:

- `SELECT`: own row only.
- `UPDATE`: own row only, with column-restricted writes.
- No client `INSERT` or `DELETE`.
- The signup trigger creates the row.

Client-updatable fields are limited to profile details and preferences. Email, id, referral fields, account type, admin level, and deactivation state are not client-controlled.

### 3.2 `offers`

A retailer-created cashback offer. Active offers are readable by signed-in shoppers. Retailers can read and update their own offers.

| Column | Type | Nullable/default | Meaning |
|---|---|---|---|
| `id` | uuid | primary key, generated | Offer id. |
| `merchant_name` | text | not null | Store or merchant name. |
| `merchant_address` | text | nullable | Address used in the offer and store map. 5–140 characters when supplied. |
| `title` | text | not null | Offer title. |
| `description` | text | not null | Offer explanation. |
| `category` | text | not null | Grocery, dining, retail, outdoors, health, fuel, electronics, or other UI category. |
| `cashback_cents` | integer | not null | Cashback per approved claim. Current database bound is 1–5,000 cents. |
| `budget_cents` | integer | not null | Maximum offer budget. |
| `reserved_cents` | integer | default `0` | Reserved budget field retained by the model. |
| `spent_cents` | integer | default `0` | Cashback committed by approved claims. |
| `min_purchase_cents` | integer | default `0` | Minimum receipt total. Bound is 0–10,000,000 cents. |
| `per_user_limit` | integer | default `1` | Maximum qualifying claims per user. Bound is 1–100. |
| `starts_at` | timestamptz | not null | Offer start. |
| `ends_at` | timestamptz | not null | Offer end; must be after start. |
| `active` | boolean | default `true` | Whether the offer can be selected. |
| `owner_id` | uuid | nullable | Retailer profile that owns the offer. |
| `created_at` | timestamptz | default `now()` | Creation time. |

Important constraints:

- `reserved_cents + spent_cents <= budget_cents`.
- Cashback is positive and capped at 5,000 cents in the live database.
- Minimum purchase is non-negative and capped at 10,000,000 cents.
- Per-user limit is positive and capped at 100.
- End date must be after start date.

Client permissions:

- `SELECT`: active offers or offers owned by the current user.
- `INSERT`: authenticated retailer only, with `owner_id = auth.uid()`.
- `UPDATE`: own offer only, and only title, description, budget, end date, active flag, and merchant address.
- No client `DELETE`.
- Cashback amount and merchant name are not editable after creation through the client grant.

### 3.3 `receipts`

One submitted receipt claim. Claims are created only through `submit_receipt(...)`.

| Column | Type | Nullable/default | Meaning |
|---|---|---|---|
| `id` | uuid | generated primary key | Claim id. |
| `user_id` | uuid | default `auth.uid()` | Shopper who submitted the claim. |
| `offer_id` | uuid | not null | Related offer. |
| `merchant_name` | text | not null | Merchant name as submitted. |
| `purchase_date` | date | not null | Date printed on the receipt. |
| `total_cents` | integer | not null | Receipt total. Must be positive; function caps it at 10,000,000 cents. |
| `receipt_number` | text | not null | Receipt identifier. Function accepts 3–40 characters. |
| `card_last4` | text | nullable | Optional four-digit card suffix. |
| `fingerprint` | text | not null | MD5 fingerprint of normalized merchant/date/total/receipt number/card suffix. Used only for duplicate detection. |
| `status` | text | default `SUBMITTED` | `SUBMITTED`, `REVIEWING`, `APPROVED`, `PAID`, `REJECTED`, or `REVERSED`. |
| `cashback_cents` | integer | default `0` | Cashback awarded for this claim. |
| `rejection_reason` | text | nullable | Required when status is `REJECTED`. |
| `submitted_at` | timestamptz | default `now()` | Submission time. |
| `decided_at` | timestamptz | nullable | Decision time. |

Client permissions:

- `SELECT`: own receipts only.
- No direct client insert, update, or delete.
- Submission is only through the protected RPC.

A partial unique index prevents duplicate non-rejected fingerprints. Rejected attempts remain visible in the submitter's history but do not permanently reserve the fingerprint.

### 3.4 `saved_offers`

A user's saved-offer list.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Owner. Defaults to current authenticated user. |
| `offer_id` | uuid | Related offer. |
| `created_at` | timestamptz | Save time. |

Unique key: `(user_id, offer_id)`.

Client permissions: own-row select, insert, and delete only.

### 3.5 `referral_bonuses`

Immutable referral rewards created by the referral RPC.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | User receiving the bonus. |
| `amount_cents` | integer | Positive bonus amount. Current referral bonus is 500 cents. |
| `reason` | text | `INVITE_ACCEPTED` or `INVITE_SENT`. |
| `counterpart_id` | uuid | Other profile in the referral relationship. |
| `created_at` | timestamptz | Creation time. |

Client permissions: select own rows only. Inserts are performed by `redeem_referral_code(...)`.

### 3.6 `wallet_ledger`

Append-only financial ledger. This is the source of truth for wallet credits and reversals.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Wallet owner. |
| `entry_type` | text | `RECEIPT_CASHBACK`, `REFERRAL_BONUS`, or `REVERSAL`. |
| `amount_cents` | integer | Positive for credits; negative for reversals. |
| `source_id` | uuid | Receipt or referral source, or original ledger row for a reversal. |
| `reference_key` | text | Unique idempotency key such as `receipt:<id>` or `referral_bonus:<id>`. |
| `description` | text | Merchant name or bonus/reversal explanation. |
| `transaction_id` | uuid | Transaction identifier where present in the current schema. |
| `reversal_of` | uuid | Original ledger id for reversal rows. |
| `created_at` | timestamptz | Creation time. |

Current invariants:

- Non-reversal rows must have positive amounts and no `reversal_of`.
- Reversal rows must have negative amounts and a `reversal_of` value.
- Every `reference_key` is unique.
- A trigger rejects all updates and deletes.
- No client insert, update, or delete grant exists.
- Clients can select only their own rows.

Replacement implementation must use an append-only ledger and create correction rows rather than editing financial history.

### 3.7 `payouts`

Cash-out request created by the shopper and settled by an administrator.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Shopper requesting payment. |
| `method` | text | `UPI` or `CASH`. |
| `upi_id` | text | Required for UPI; null for cash. |
| `amount_cents` | integer | Amount linked to this payout. |
| `status` | text | `REQUESTED`, `PAID`, or `CANCELLED`. |
| `payment_reference` | text | Required for paid payouts. |
| `note` | text | Required for cancelled payouts. |
| `requested_at` | timestamptz | Request time. |
| `settled_at` | timestamptz | Settlement or cancellation time. |

Constraints and indexes:

- Amount must be positive.
- UPI id must match the selected method.
- Requested payouts have no settlement time.
- Paid payouts require a payment reference.
- Cancelled payouts require a note.
- At most one `REQUESTED` payout per user.
- Paid payment references are unique.
- Current minimum payout is 500 cents.

Client permissions: select own payouts only. All writes go through RPC functions.

### 3.8 `payout_entries`

Links wallet ledger entries to a payout without modifying the ledger.

| Column | Type | Meaning |
|---|---|---|
| `ledger_id` | uuid | Primary key and foreign key to `wallet_ledger`. One ledger row can be linked once. |
| `payout_id` | uuid | Foreign key to `payouts`, cascades when a payout is removed by trusted server logic. |

Client permissions: select rows only when the related payout belongs to the current user.

When a payout is requested, all currently unlinked ledger rows for that user are linked. The wallet balance therefore decreases without changing ledger history. When an administrator cancels a request, its links are removed and the balance becomes available again.

### 3.9 `notifications`

In-app notifications created from receipt status changes.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Notification owner. |
| `kind` | text | `RECEIPT_APPROVED` or `RECEIPT_REJECTED`. |
| `receipt_id` | uuid | Related receipt. |
| `merchant_name` | text | Merchant name shown in the alert. |
| `cashback_cents` | integer | Stored for the in-app record; push text does not expose the amount. |
| `read_at` | timestamptz | Null until marked read. |
| `created_at` | timestamptz | Creation time. |
| `pushed_at` | timestamptz | Set after push delivery is attempted. |

Unique key: `(receipt_id, kind)`.

Client permissions:

- Select own notifications.
- Update only `read_at` on own notifications.
- No client insert or delete.

### 3.10 `push_subscriptions`

One browser/device push subscription per endpoint.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Owner. |
| `endpoint` | text | Unique HTTPS browser push endpoint. |
| `p256dh` | text | Web Push encryption key. |
| `auth_key` | text | Web Push authentication key. |
| `created_at` | timestamptz | Registration time. |

Client permissions:

- Select own subscriptions.
- Delete own subscriptions.
- No direct insert/update; registration uses `register_push_subscription(...)`.

### 3.11 `support_requests`

Customer support messages.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Request owner. |
| `topic` | text | `ACCOUNT`, `CASHBACK`, `OFFERS`, or `OTHER`. |
| `message` | text | 10–2,000 characters. |
| `status` | text | `OPEN`, `ANSWERED`, or `CLOSED`; default `OPEN`. |
| `created_at` | timestamptz | Creation time. |

Client permissions: select own requests and insert only `topic` and `message`. Ownership and status are server-controlled.

### 3.12 `todos`

Private planner items.

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | Primary key. |
| `user_id` | uuid | Owner. |
| `title` | text | Trimmed length 1–200. |
| `due_on` | date | Planned date. |
| `completed` | boolean | Completion flag. |
| `created_at` | timestamptz | Creation time. |

Client permissions: full CRUD for own rows only. Inserts default ownership from the authenticated session.

### 3.13 `submit_log`

Server-only receipt submission rate-limit records.

| Column | Type | Meaning |
|---|---|---|
| `user_id` | uuid | Rate-limit subject. |
| `submitted_at` | timestamptz | Submission attempt time. |

The table has no client grants and is only accessed inside `submit_receipt(...)`.

Current rule: after old entries are removed, a user can make at most 12 receipt submissions in a rolling one-hour window. The row is written only after the user passes the limit check.

### 3.14 Storage bucket: `avatars`

Private Supabase Storage bucket for profile images.

Current behavior:

- Allowed formats: JPEG, PNG, WebP.
- Maximum upload size: 2 MB.
- Object path: `<user_id>/avatar-<timestamp>.<extension>`.
- Users can upload into their own path, read through signed URLs, and remove their own previous image.
- Signed URLs currently last one hour.

## 4. Relationships

```text
auth.users 1 ─── 1 profiles
profiles  1 ─── * offers              (retailer ownership)
profiles  1 ─── * receipts
profiles  1 ─── * saved_offers
profiles  1 ─── * referral_bonuses
profiles  1 ─── * wallet_ledger
profiles  1 ─── * payouts
profiles  1 ─── * notifications
profiles  1 ─── * push_subscriptions
profiles  1 ─── * support_requests
profiles  1 ─── * todos

offers    1 ─── * receipts
receipts  1 ─── * notifications
wallet_ledger 1 ─── 0..1 payout_entries
payouts   1 ─── * payout_entries
wallet_ledger 1 ─── * wallet_ledger reversals
profiles  1 ─── * profiles.referred_by
```

## 5. Direct table API contracts

The current frontend uses the Supabase SDK. A replacement REST or GraphQL API should preserve the following logical operations.

### Public authenticated offer reads

```text
GET offers
  filter active = true
  filter ends_at > current time
  order by ends_at ascending

GET offers/:id
  return one active or owned offer
```

Returned offer fields:

```text
id, merchant_name, merchant_address, title, description, category,
cashback_cents, budget_cents, reserved_cents, spent_cents,
min_purchase_cents, per_user_limit, starts_at, ends_at
```

### Shopper profile

```text
GET profiles/:current_user_id
PATCH profiles/:current_user_id
```

The server must ignore or reject attempts to update protected fields. Allowed profile updates are the fields explicitly listed in the profile permissions section.

### Shopper receipts

```text
GET receipts
  current user's rows only
  newest submitted_at first

GET receipts/:id
  current user's row only
  include related offer title
```

There is no direct receipt create endpoint. Use the submit receipt RPC contract below.

### Saved offers

```text
GET saved_offers with related offer
GET saved_offers -> offer_id list
POST saved_offers { offer_id }
DELETE saved_offers where offer_id = :offer_id
```

The duplicate save case is idempotent in the client: unique violation `23505` is treated as already saved.

### Wallet and payouts

```text
GET wallet_ledger
  current user's rows only
  newest first

GET payouts
  current user's rows only
  newest requested_at first

GET payout_entries/:payout_id
  only when the payout belongs to current user
```

The wallet balance itself is returned by `my_wallet_balance_cents()` rather than calculated in the client.

### Notifications

```text
GET notifications
  current user's rows only
  newest first
  maximum 50 in the current client

PATCH notifications
  where id in requested ids and read_at is null
  set read_at = current timestamp
```

Only `read_at` can be changed by the client.

### Todos

```text
GET todos
  filter due_on between selected month bounds
  order by created_at ascending

POST todos { title, due_on }
PATCH todos/:id { completed }
DELETE todos/:id
```

All operations are owner-scoped.

### Retailer offers

```text
GET offers owned by current retailer
GET my_offer_claim_stats()
POST offers
PATCH offers/:id
```

Create payload:

```json
{
  "merchant_name": "string",
  "merchant_address": "string",
  "title": "string",
  "description": "string",
  "category": "string",
  "cashback_cents": 0,
  "budget_cents": 0,
  "min_purchase_cents": 0,
  "per_user_limit": 1,
  "ends_at": "ISO-8601 timestamp"
}
```

Update payload:

```json
{
  "title": "string",
  "description": "string",
  "merchant_address": "string",
  "budget_cents": 0,
  "ends_at": "ISO-8601 timestamp",
  "active": true
}
```

The current client validates a narrower UI range than the database for some fields. The replacement server should be authoritative and retain the database bounds.

### Support

```text
GET support_requests
POST support_requests { topic, message }
```

The server sets `user_id`, `status`, and timestamps. The client cannot set status.

## 6. RPC API contracts

All RPC calls below are logically POST operations. In a replacement stack, expose them as authenticated service methods or endpoints rather than allowing clients to write financial tables directly.

### 6.1 `submit_receipt`

Signature:

```text
submit_receipt(
  p_offer_id uuid,
  p_merchant_name text,
  p_purchase_date date,
  p_total_cents integer,
  p_receipt_number text,
  p_card_last4 text
) -> receipts row
```

Caller: authenticated shopper.

Validation:

- Requires a signed-in user.
- Merchant name: trimmed, 2–80 characters.
- Receipt number: trimmed, 3–40 characters.
- Total: positive, maximum 10,000,000 cents.
- Purchase date cannot be null or in the future.
- Card suffix is empty/null or exactly four digits.
- Offer must exist and be active.

Business checks, in order:

1. Offer must be within its time window.
2. Purchase date must be within the offer date range.
3. Case-insensitive merchant name must match the offer merchant name.
4. Receipt total must meet the offer minimum.
5. Fingerprint must not already exist on a non-rejected claim.
6. User claim count for the offer must be below `per_user_limit`.
7. Offer budget remaining must cover the cashback amount.
8. The user's rolling one-hour submission count must be below 12.

Fingerprint input:

```text
lower(trim(merchant_name)) + '|' +
purchase_date + '|' +
total_cents + '|' +
lower(trim(receipt_number)) + '|' +
coalesce(trim(card_last4), '')
```

The current implementation stores the MD5 of that normalized string.

Success behavior:

- Increments `offers.spent_cents` by the offer cashback.
- Inserts an `APPROVED` receipt with the cashback amount.
- A receipt trigger writes the corresponding wallet ledger credit.
- A notification trigger creates an in-app approval notification.
- A push trigger may dispatch the notification asynchronously.

Business-rule rejection behavior:

- Inserts a `REJECTED` receipt with `cashback_cents = 0` and a user-readable `rejection_reason`.
- Returns the rejected receipt rather than treating a normal eligibility failure as a server failure.

Malformed input and authentication failures raise errors and do not create a receipt.

Concurrency requirements:

- Lock the offer row while checking and consuming budget.
- Use a unique non-rejected fingerprint index or equivalent database constraint.
- Rate-limit and insert atomically.
- Treat a unique race as a friendly rejected duplicate, not as a successful claim.

### 6.2 `my_wallet_balance_cents`

Signature:

```text
my_wallet_balance_cents() -> integer
```

Caller: authenticated user.

Returns the current available wallet total. The calculation must include the user's positive ledger credits and exclude ledger entries already linked to a payout. Reversal rows are negative and remain part of the append-only balance history.

### 6.3 `redeem_referral_code`

Signature:

```text
redeem_referral_code(p_code text) -> integer
```

Caller: authenticated user.

Current business rules:

- Referral bonus is 500 cents per side according to the current referral design.
- Prevents self-referral.
- Prevents prohibited mutual/cyclic referral patterns.
- Limits invite activity to 20 according to the current function logic.
- Creates referral bonus rows and wallet ledger rows through the referral trigger.
- Returns the resulting bonus amount.

### 6.4 `request_payout`

Signature:

```text
request_payout(p_method text, p_upi_id text default null) -> payouts row
```

Caller: authenticated shopper.

Accepted methods:

- `UPI`: requires a valid UPI id matching the current database pattern.
- `CASH`: clears/ignores the UPI id.

Current rules:

- Requires authentication.
- Locks the caller's profile row to serialize payout requests.
- Rejects a second `REQUESTED` payout.
- Links all currently unlinked wallet ledger rows for the caller.
- Requires at least 500 cents available.
- Inserts the payout using the linked total.
- Does not allow direct client insertion into `payouts`.

The UPI validator was corrected in the latest migration to use a maximum local-part repetition count of 255 because Postgres rejects repetition counts above 255.

### 6.5 `admin_list_payouts`

Signature:

```text
admin_list_payouts() -> rows
```

Returns:

```text
id, user_id, full_name, email, method, upi_id, amount_cents,
status, payment_reference, note, requested_at, settled_at,
transaction_count
```

Requires `profiles.admin_level` to be non-null for the caller.

### 6.6 `admin_payout_transactions`

Signature:

```text
admin_payout_transactions(p_payout_id uuid) -> rows
```

Returns linked wallet entries:

```text
ledger_id, entry_type, amount_cents, description, created_at
```

Requires an administrator caller.

### 6.7 `admin_complete_payout`

Signature:

```text
admin_complete_payout(p_payout_id uuid, p_reference text) -> payouts row
```

Rules:

- Administrator only.
- Reference is trimmed and must be 4–64 characters.
- Payout must exist and be `REQUESTED`.
- Reference cannot already belong to a `PAID` payout.
- Sets `status = PAID`, stores the reference, and sets `settled_at`.

### 6.8 `admin_cancel_payout`

Signature:

```text
admin_cancel_payout(p_payout_id uuid, p_reason text) -> payouts row
```

Rules:

- Administrator only.
- Reason is trimmed and must be 3–200 characters.
- Payout must exist and be `REQUESTED`.
- Deletes only the payout links, not ledger rows.
- Sets `status = CANCELLED`, stores the note, and sets `settled_at`.
- The linked wallet amount becomes available again.

### 6.9 `admin_spending_overview`

Signature:

```text
admin_spending_overview() -> rows
```

Returns aggregate rows:

```text
merchant_name, category, claim_count,
spend_cents, cashback_cents
```

Administrator-only. It does not return individual user details.

### 6.10 `admin_customer_summary`

Signature:

```text
admin_customer_summary() -> rows
```

Returns:

```text
user_id, full_name, email, claim_count,
spend_cents, cashback_cents, last_purchase_date
```

The current implementation restricts this customer-level aggregate to `super_admin`.

### 6.11 `admin_customer_merchant_breakdown`

Signature:

```text
admin_customer_merchant_breakdown(p_user_id uuid) -> rows
```

Returns:

```text
merchant_name, category, claim_count,
spend_cents, cashback_cents, last_purchase_date
```

Administrator-only, with the current function's role restrictions.

### 6.12 `admin_customer_transactions`

Signature:

```text
admin_customer_transactions(p_user_id uuid) -> rows
```

Returns at most 200 customer receipt records:

```text
receipt_id, merchant_name, offer_title, category,
purchase_date, total_cents, cashback_cents, status
```

The current function restricts this detailed customer view to `super_admin`.

### 6.13 `my_offer_claim_stats`

Signature:

```text
my_offer_claim_stats() -> rows
```

Returns retailer-owned offer aggregates:

```text
offer_id, claims, approved, rejected, approved_total_cents
```

No customer personal information is returned.

### 6.14 `deactivate_my_account`

Signature:

```text
deactivate_my_account() -> void
```

Authenticated caller only. Sets `profiles.deactivated_at` and updates the profile timestamp. It does not delete financial history or the Auth account.

### 6.15 `reactivate_my_account`

Signature:

```text
reactivate_my_account() -> void
```

Authenticated caller only. Clears `profiles.deactivated_at`. The client calls it after a successful password login.

### 6.16 `register_push_subscription`

Signature:

```text
register_push_subscription(
  p_endpoint text,
  p_p256dh text,
  p_auth_key text
) -> void
```

Authenticated caller only.

Validation:

- Endpoint must be HTTPS and no more than 2,048 characters.
- Encryption keys must be non-empty and no more than 256 characters.
- User id is always taken from `auth.uid()`.
- Endpoint uniqueness is handled with upsert, updating the subscription owner and keys.

### 6.17 `reverse_receipt_credit`

Signature:

```text
reverse_receipt_credit(p_receipt_id uuid, p_reason text) -> wallet_ledger row
```

Service-role/database administration only. It is not a client API.

Rules:

- Reason is trimmed and must be 3–200 characters.
- Receipt must exist and be `APPROVED` or `PAID`.
- Finds the original receipt cashback ledger entry.
- Adds one negative `REVERSAL` ledger row linked to the original entry.
- Reduces offer `spent_cents`, never below zero.
- Changes receipt status to `REVERSED`.
- Does not edit or delete the original ledger row.

## 7. Edge Function APIs

### 7.1 `delete-account`

Route in the current deployment:

```text
POST /functions/v1/delete-account
```

JWT verification is enabled at the platform level. The function also validates the bearer token by calling Auth with the service-role client.

Request:

- No request body required.
- `Authorization: Bearer <user access token>` required.

Responses:

```json
{ "ok": true }
```

or:

```json
{ "ok": false, "reason": "wallet_history" }
```

Possible blocking reasons:

- `wallet_history`: user has any ledger history.
- `open_payouts`: user has a `REQUESTED` payout.
- `open_claims`: user has a `SUBMITTED` or `REVIEWING` receipt.
- `has_offers`: user owns retailer offers.

On success, the function deletes the user's receipts, saved offers, and todos, then deletes the Auth account. Profile deletion follows through the profile foreign key cascade.

The function returns generic `unauthorized` or `delete_failed` errors rather than exposing internal database details.

Replacement requirements:

- Verify the access token server-side.
- Re-check blockers in the same deletion workflow.
- Make deletion idempotent or safely retryable.
- Revoke sessions and refresh tokens.
- Decide separately how to retain legally required financial/audit records.

### 7.2 `send-push`

Route in the current deployment:

```text
POST /functions/v1/send-push
```

Platform JWT verification is disabled because this is invoked by the database trigger. The function performs its own authentication by requiring the bearer token to equal the server-only service key.

Request:

```json
{ "notification_id": "uuid" }
```

Headers:

```text
Authorization: Bearer <server-only service key>
Content-Type: application/json
```

Behavior:

1. Validate the service key.
2. Validate the notification id format.
3. Load the notification and return `404` if it does not exist.
4. Return a skipped success if `pushed_at` is already set.
5. Load all push subscriptions for the notification's user.
6. Send Web Push notifications with a 24-hour TTL.
7. Remove subscriptions returning 404 or 410.
8. Count sent, removed, and failed deliveries.
9. Set `notifications.pushed_at` after the attempt.

Push payload text includes the merchant name but intentionally does not expose cashback amounts or receipt details:

```json
{
  "title": "Receipt approved",
  "body": "Your receipt from <merchant> was approved.",
  "url": "/notifications"
}
```

The rejection message similarly names the merchant and directs the user to open the app for details.

### 7.3 CORS behavior

Both edge functions respond to `OPTIONS` preflight and include these headers on success and errors:

```text
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-Client-Info, Apikey
```

If the replacement stack serves only same-origin requests, restrict CORS rather than copying the wildcard blindly.

## 8. Database triggers and asynchronous behavior

### Auth/profile triggers

- `on_auth_user_created` on `auth.users` → `handle_new_user()`.
- `profiles_guard_changes` before profile insert/update → protects email and date of birth and checks minimum age.

### Receipt triggers

- `receipts_wallet_ledger` after receipt insert or status/cashback update → creates idempotent cashback ledger credit when status is `APPROVED` or `PAID` and cashback is positive.
- `receipts_notifications` after receipt insert/update → creates the appropriate approval/rejection notification once per receipt and kind.

### Referral trigger

- `referral_bonuses_wallet_ledger` after referral bonus insert → creates an idempotent referral ledger credit.

### Wallet protection

- `wallet_ledger_immutable` before update/delete → rejects changes to financial history.

### Push trigger

- `notifications_push_dispatch` after notification insert → reads the push dispatch URL and service key from the database vault and submits a request through `pg_net` to `send-push`.

This push delivery is asynchronous. The transaction creating the notification does not wait for the browser push to finish.

## 9. Row-level security and grants

The live security model is deny-by-default for client roles.

| Table | Authenticated client access |
|---|---|
| `profiles` | Select/update own profile with restricted columns |
| `offers` | Select active or own offers; retailer-only insert; own-offer restricted update |
| `receipts` | Select own rows only |
| `saved_offers` | Select/insert/delete own rows |
| `referral_bonuses` | Select own rows |
| `wallet_ledger` | Select own rows |
| `payouts` | Select own rows |
| `payout_entries` | Select rows tied to own payouts |
| `notifications` | Select own rows; update only `read_at` |
| `push_subscriptions` | Select/delete own rows; insert through RPC only |
| `support_requests` | Select own rows; insert only topic/message |
| `todos` | Full CRUD on own rows |
| `submit_log` | No client access |

Rules to preserve in a replacement API:

- Derive ownership from the verified session, never from a request body user id.
- Keep admin fields, wallet amounts, payout statuses, and moderation fields server-controlled.
- Separate read permissions from write permissions.
- Do not give a browser client a generic update permission on financial tables.
- Use database transactions and row locks for balance, budget, referral, and payout operations.
- Keep service-role credentials server-side only.

### Administrator authorization

Administrator RPCs check `profiles.admin_level` in the database:

- `admin`: general administrator operations and payout management.
- `super_admin`: more sensitive customer-level reporting functions.

The current design does not use a client-editable metadata field for authorization. In a replacement stack, use a server-controlled role table or immutable server-side claims.

## 10. Main business workflows

### Shopper receipt-to-wallet flow

```text
1. User signs in.
2. Client calls submit_receipt(...).
3. Server validates identity, input, offer status, date, merchant,
   minimum purchase, duplicates, claim limit, budget, and rate limit.
4. Offer budget is updated while its row is locked.
5. Receipt is inserted as APPROVED or REJECTED.
6. Approved receipt trigger creates a RECEIPT_CASHBACK ledger entry.
7. Notification trigger creates an in-app notification.
8. Push trigger asynchronously calls send-push.
9. Client reloads receipt history and wallet balance.
```

### Wallet-to-payout flow

```text
1. User requests UPI or cash payout.
2. request_payout locks the profile row.
3. It rejects a second open payout.
4. It links all unlinked positive/negative ledger entries for the user.
5. It computes the linked amount.
6. It rejects totals below 500 cents.
7. It creates a REQUESTED payout.
8. Available wallet balance becomes zero for those linked rows.
9. Admin either completes or cancels the payout.
10. PAID keeps links and records a payment reference.
11. CANCELLED removes links and restores availability without editing history.
```

### Reversal flow

```text
1. Trusted server/admin identifies an approved or paid receipt.
2. reverse_receipt_credit validates the reason and receipt state.
3. A negative REVERSAL ledger row is appended.
4. The offer's spent amount is reduced safely.
5. Receipt becomes REVERSED.
6. Original ledger data remains unchanged.
```

### Account deactivation flow

```text
1. Signed-in user calls deactivate_my_account.
2. Profile gets deactivated_at = current time.
3. Auth account remains present.
4. On later successful login, client calls reactivate_my_account.
5. Profile deactivated_at is cleared.
```

### Account deletion flow

```text
1. User submits deletion request with a valid session.
2. Server checks wallet history, open payouts, open claims, and owned offers.
3. If any blocker exists, return a stable blocker code.
4. If clear, delete personal app records and the Auth user.
5. Revoke the user's sessions.
```

## 11. Rate limiting and abuse controls

Current protection:

- Receipt submissions: 12 per user per rolling hour.
- Rate limit is stored in `submit_log` rather than memory.
- Old records are removed during submission.
- The rate-limit table has no browser grants.
- Duplicate receipt fingerprints prevent repeated non-rejected claims.
- One-open-payout unique index prevents duplicate cash-outs.
- Payout reference uniqueness prevents reusing a paid reference.

Important limitation:

- The current receipt limiter is per user, not per IP.
- Authentication attempts are currently delegated to Supabase Auth and no separate application IP limiter is present in this project.
- A replacement public API should add IP/device controls at the edge for login, signup, password recovery, receipt submission, referral redemption, support requests, and push registration. Keep per-user controls as a second layer.

## 12. Migration history

The live database reports these applied migrations:

1. `20261108043742_create_profiles_with_signup_trigger.sql`
2. `20261108044548_create_offers_receipts_and_submit_claim.sql`
3. `20261108050613_add_referral_codes_and_bonuses.sql`
4. `20261108051748_add_retailer_accounts_and_offer_management.sql`
5. `20261108052856_add_offer_address_saved_deals_and_tighten_grants.sql`
6. `20261110043420_add_admin_spending_insights.sql`
7. `20261110044822_add_wallet_ledger.sql`
8. `20261110045826_add_wallet_reversals.sql`
9. `20261110050837_add_payouts_linked_to_ledger.sql`
10. `20261110051322_add_wallet_available_balance.sql`
11. `20261112020657_add_planner_todos.sql.sql`
12. `20261112022638_add_profile_details_and_account_controls.sql`
13. `20261112034216_add_profile_avatar_private_storage.sql`
14. `20261112042034_add_receipt_notifications.sql`
15. `20261112043223_harden_notifications_access_and_insert_trigger.sql`
16. `20261112045054_add_push_subscriptions_and_dispatch.sql`
17. `20261117034819_20261117_revoke_drifted_table_grants.sql.sql`
18. `20261117034831_20261117_submit_receipt_friendly_duplicate_race.sql.sql`
19. `20261117035502_20261117_revoke_residual_table_privileges.sql.sql`
20. `20261117035517_20261117_add_offer_sanity_bounds.sql.sql`
21. `20261117041924_20261117_add_submit_rate_limit.sql.sql`
22. `20261117041938_20261117_wire_submit_rate_limit.sql.sql`
23. `20261117042130_fix_request_payout_upi_regex_repetition_limit.sql.sql`

The migration files in `supabase/migrations/` are the source history. The live database security posture is authoritative if a migration file and the database ever disagree.

## 13. Replacement stack mapping

### Recommended service boundaries

Build these as separate server modules:

1. **Auth service**
   - Registration, login, refresh, logout, password change, password recovery, session revocation.
   - User id and account status derived from verified tokens.

2. **Profile service**
   - Profile read/update.
   - Preferences.
   - Deactivation/reactivation.

3. **Offer service**
   - Public authenticated offer reads.
   - Retailer offer create/update.
   - Offer budget and availability checks.

4. **Claim service**
   - Receipt submission.
   - Fingerprint duplicate protection.
   - Rate limits.
   - Claim status and notifications.

5. **Wallet service**
   - Append-only ledger.
   - Balance calculation.
   - Referral credits.
   - Reversals.

6. **Payout service**
   - Request payout.
   - Link ledger entries.
   - Admin completion/cancellation.
   - Payment reference idempotency.

7. **Notification service**
   - In-app notification creation.
   - Push subscription registration.
   - Push delivery and endpoint cleanup.

8. **Account deletion service**
   - Blocker checks.
   - Personal data deletion.
   - Financial/audit retention policy.
   - Session revocation.

### Suggested HTTP endpoint equivalents

```text
POST   /auth/signup
POST   /auth/login
POST   /auth/refresh
POST   /auth/logout
POST   /auth/logout-other-sessions
POST   /auth/password/change
POST   /auth/password/recovery

GET    /me
PATCH  /me
POST   /me/deactivate
POST   /me/reactivate
POST   /me/delete

GET    /offers
GET    /offers/:offerId
POST   /retailer/offers
PATCH  /retailer/offers/:offerId
GET    /retailer/offers/stats

POST   /claims/receipts
GET    /claims/receipts
GET    /claims/receipts/:receiptId

GET    /wallet/balance
GET    /wallet/ledger
POST   /wallet/payouts
GET    /wallet/payouts
GET    /wallet/payouts/:payoutId/entries

GET    /referrals/bonuses
POST   /referrals/redeem

GET    /saved-offers
POST   /saved-offers
DELETE /saved-offers/:offerId

GET    /notifications
PATCH  /notifications/read
POST   /push/subscriptions
DELETE /push/subscriptions/:endpoint

GET    /todos
POST   /todos
PATCH  /todos/:todoId
DELETE /todos/:todoId

GET    /support-requests
POST   /support-requests

GET    /admin/analytics/overview
GET    /admin/customers
GET    /admin/customers/:userId/merchant-breakdown
GET    /admin/customers/:userId/transactions
GET    /admin/payouts
GET    /admin/payouts/:payoutId/transactions
POST   /admin/payouts/:payoutId/complete
POST   /admin/payouts/:payoutId/cancel

POST   /internal/push/send
```

These paths are a suggested translation, not routes that currently exist in the project. The current frontend uses Supabase table queries and RPC calls instead.

## 14. Recommended rebuild order

1. Create Auth accounts and the user/profile model.
2. Create offers and retailer ownership rules.
3. Create receipts and the server-side submission transaction.
4. Create the append-only wallet ledger and idempotent credit triggers/jobs.
5. Create referral bonuses and redemption rules.
6. Create payouts and payout-entry linking.
7. Add reversals and immutable financial audit behavior.
8. Add notifications and push subscriptions.
9. Add account deactivation and deletion blockers.
10. Add admin reporting and payout settlement.
11. Add IP/device rate limiting at the edge.
12. Import data only after schema and invariants are tested.

## 15. Data migration notes

- Preserve UUIDs where possible so foreign keys remain valid.
- Import Auth users before profiles.
- Import profiles before offers, receipts, referrals, and wallet records.
- Import wallet ledger rows before payout entries.
- Import payouts before payout entries.
- Keep original timestamps and statuses.
- Validate that every `wallet_ledger.reference_key` is unique before import.
- Validate that every non-rejected receipt fingerprint is unique.
- Validate that each payout amount equals the sum of its linked ledger rows.
- Validate that no user has more than one open payout.
- Do not import `submit_log` history unless you intentionally want to preserve the current rate-limit window.
- Do not copy service keys, VAPID private keys, database URLs, access tokens, or Vault values into migration files.

## 16. Current implementation gaps to account for

These are existing behaviors or limitations, not hidden assumptions:

- No separate application API server exists in this project.
- Current signup expects an immediate session; email-confirmation mode would require client changes.
- Password recovery is not implemented in the current client code.
- Receipt rate limiting is per user, not per IP.
- Receipt approval is automatic after database validation; there is no separate human review queue in the current client flow.
- Account deletion is blocked when financial history exists, so financial records are retained rather than deleted.
- Push delivery is web-push based and depends on configured VAPID credentials and database dispatch settings.
- Admin permissions are stored in `profiles.admin_level`; this field must remain operator-controlled.
- The current database uses Supabase-specific `auth.uid()`, RLS, `pg_net`, Vault, and Auth trigger behavior. These must be replaced with equivalent server-side mechanisms on the new stack.

## 17. Verification checklist for the replacement

Before switching the client to the new backend, verify:

- A user cannot read another user's profile, receipts, wallet, payouts, notifications, todos, saved offers, or support requests.
- A shopper cannot create or edit an offer.
- A retailer cannot edit cashback or merchant identity after creation.
- A client cannot insert or update wallet ledger rows.
- A duplicate receipt cannot create two non-rejected claims, including under concurrent requests.
- A claim cannot spend more than the offer budget.
- A user cannot create two open payouts concurrently.
- A payout cannot link another user's ledger entries.
- Cancelling a payout restores the available balance without changing ledger history.
- Completing a payout requires a unique payment reference.
- Reversing a receipt appends a negative ledger row and is idempotent or safely rejected on repeat.
- Rate limits work across multiple API instances.
- Login, signup, password recovery, and push registration have IP/device abuse controls.
- Account deletion revokes sessions and obeys financial retention requirements.
- Admin functions enforce server-side roles, not client metadata.
- All money tests use integer cents and database transactions.
- All background jobs are durable and retryable; no important state is held only in process memory.

## 18. Source locations in this project

- Supabase client setup: `lib/supabase.ts`
- Auth/session context: `contexts/AuthContext.tsx`
- Account operations: `lib/accountService.ts`
- Receipt queries and submission: `hooks/useReceipts.ts`
- Offer queries and retailer operations: `hooks/useOffers.ts`, `hooks/useBusinessOffers.ts`
- Wallet and payout queries: `hooks/useWalletBalance.ts`, `hooks/usePayouts.ts`, `hooks/useAdminPayouts.ts`
- Admin analytics: `hooks/useAdminInsights.ts`
- Referral API calls: `hooks/useReferrals.ts`
- Notification API calls: `hooks/useNotifications.ts`
- Push registration: `lib/pushAlerts.ts`
- Avatar storage: `lib/avatarService.ts`
- Account deletion edge function: `supabase/functions/delete-account/index.ts`
- Push delivery edge function: `supabase/functions/send-push/index.ts`
- Database migration source: `supabase/migrations/`

This document describes the backend contract as implemented at the snapshot date above. Re-check the live database security posture before performing a production data export or cutover if additional changes are made afterward.
