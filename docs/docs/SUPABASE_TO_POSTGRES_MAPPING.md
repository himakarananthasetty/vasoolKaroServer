# VasoolKaro — Supabase → Independent PostgreSQL Migration Mapping

How each object in the existing Supabase project maps to the new self-hosted schema. Existing functionality is preserved; deviations are listed with reasons. This document pairs with `DATABASE_DESIGN.md` (full column detail) and `BACKEND_HANDOFF.md` (current behavior contract).

## 1. Table mapping

| Existing Supabase Table | New PostgreSQL Table | Changes | Reason |
|---|---|---|---|
| `auth.users` (Supabase-managed) | `users` (merged with `profiles`) | Consolidated into a single app-owned table; adds `password_hash`, `deleted_at`; drops the profile/auth split | Auth becomes app-owned (argon2id + JWT); one row per account removes the permanent 1:1 join and the signup trigger |
| `profiles` | `users` (merged with `auth.users`) | Same columns as before, minus `admin_level`; `email` becomes `citext`; `updated_at` becomes trigger-maintained | Consolidation above; `admin_level` replaced by the `user_roles` table so roles are server-controlled rows, not a client-visible column |
| `offers` | `offers` | Conceptually unchanged; money columns `integer → bigint`; adds `updated_at`; fingerprint-grade CHECK bounds kept | Money-safety headroom; update auditing; the bounds (cashback 1–5000, min-purchase 0–10M, per-user 1–100, `reserved+spent ≤ budget`, end > start) are existing business rules |
| `receipts` | `receipts` | Conceptually unchanged; `fingerprint` md5-hex → sha-256 `bytea`; money `bigint`; FK to offer now RESTRICT; same partial unique fingerprint index | Stronger hash (md5 kept only for duplicate detection before, not security — still upgraded); claims are financial evidence and must not vanish if an offer were ever deletable |
| `saved_offers` | `saved_offers` | Unchanged (same unique `(user_id, offer_id)`) | Already correct |
| `referral_bonuses` | `referral_bonuses` | Unchanged plus a unique partial `(user_id, counterpart_id, reason)` | Makes "no double awarding the same referral pair" a database guarantee instead of function logic only |
| `wallet_ledger` | `wallet_ledger` | Unchanged semantics; money `bigint`; immutability trigger kept; FK to users is RESTRICT | The append-only design was already right; RESTRICT ensures financial history survives account deletion |
| `payouts` | `payouts` | Unchanged semantics; money `bigint`; all partial uniques and state CHECKs kept | Existing rules were sound (one open payout, unique paid reference, method/UPI pairing, note/reference/settled_at state pairing) |
| `payout_entries` | `payout_entries` | Unchanged | The ledger-linking design is preserved exactly |
| `notifications` | `notifications` | Unchanged (same unique `(receipt_id, kind)`, `pushed_at` guard) | Already correct |
| `push_subscriptions` | `push_subscriptions` | Unchanged (endpoint upsert via service layer) | Already correct |
| `support_requests` | `support_requests` | Adds `updated_at`; otherwise unchanged | Admin status changes become an actual endpoint, so changes need tracking |
| `todos` | `todos` | Unchanged (same `(user_id, due_on)` index) | Already correct |
| `submit_log` | `rate_limit_events` (redesigned) | Generalized: `user_id` → `subject_kind` + `subject_id`, plus `action`; identity PK | Same rolling-window behavior (12 receipts/hour) but reusable for other actions and for IP subjects, which the handoff §11 recommends adding |
| — (storage bucket `avatars`) | `users.avatar_path` + backend upload endpoint | Bucket replaced by app-managed object storage | No Supabase Storage dependency |
| — (none) | `sessions`, `password_reset_tokens`, `user_roles`, `audit_log` | New tables | Replace Supabase Auth sessions; add the recommended password-recovery flow; server-controlled admin roles; privileged-action audit trail |

## 2. Consolidation / split decisions

- **Consolidated:** `auth.users` + `profiles` → `users`. They were 1:1 with an identity link only; merging removes the signup trigger, the sync risk, and a join on every request.
- **Consolidated:** `submit_log` → `rate_limit_events` (generic limiter, covers more endpoints without new tables).
- **Split:** none. No Supabase table mixed unrelated concerns; splitting would add complexity without benefit.
- **Dropped:** nothing that carries business functionality. `profiles.admin_level` is dropped *as a column* but its meaning is preserved in `user_roles`.

## 3. Supabase-specific functionality that must be (and is) replaced

| Supabase mechanism | Existing behavior | New implementation |
|---|---|---|
| Supabase Auth (signup/login/refresh/sign-out scopes) | SDK-managed sessions | `POST /api/v1/auth/*` endpoints; argon2id hashes; 15-min JWT access tokens; hashed refresh tokens in `sessions`; logout / logout-others / revoke-on-password-change |
| `auth.uid()` | Caller identity inside RPCs and RLS | `current_user.id` from the verified access token, injected as a FastAPI dependency; never taken from request bodies |
| RLS policies (13 protected tables) | Row ownership enforcement in the DB | Repository layer: every query filtered by the caller's id (or admin role); Pydantic write schemas reject protected fields; least-privilege DB grants as defense-in-depth |
| Column-level grants | e.g. client could update only `read_at` on notifications | Pydantic request models accept only allowed fields; repositories update only those columns |
| `SECURITY DEFINER` RPCs (`submit_receipt`, `request_payout`, admin functions, etc.) | Atomic business logic | Service-layer functions running in explicit transactions with `SELECT ... FOR UPDATE` locks and advisory locks; same validation order as the old functions |
| `handle_new_user()` auth trigger | Profile creation on signup | Profile row created in the registration transaction |
| `receipts_wallet_ledger` trigger | Auto wallet credit on APPROVED | Wallet service credits the ledger in the same transaction as receipt approval |
| `receipts_notifications` trigger | Auto in-app notification | Notification service writes the row in the same transaction |
| `referral_bonuses_wallet_ledger` trigger | Auto referral credit | Referral service writes both rows in one transaction |
| `wallet_ledger_immutable` trigger | Rejects UPDATE/DELETE | **Kept as a DB trigger** (data-integrity backstop) plus revoked UPDATE/DELETE grants |
| `guard_profile_changes` trigger | Email immutability, DOB set-once, age ≥ 13 | Service-layer validation + DB CHECK on DOB age |
| `notifications_push_dispatch` trigger + `pg_net` + Vault | Async push dispatch | Durable background job (`pushed_at` guard kept) via Taskiq/database-backed queue; Web Push sent by the worker; failed endpoints (404/410) pruned |
| `send-push` edge function | Push delivery with service-key auth | Internal worker routine authenticated by a server-only token; never exposed publicly |
| `delete-account` edge function | Blocker checks + deletion | `POST /me/delete` with the same blockers (`wallet_history`, `open_payouts`, `open_claims`, `has_offers`); revokes sessions; soft-delete/anonymization path when financial retention applies |
| Storage `avatars` bucket + signed URLs | Avatar upload/read | Backend upload endpoint (format/size limits preserved: JPEG/PNG/WebP, 2 MB) storing to app-managed storage; short-lived signed URLs issued by the backend |
| Database vault | Secret storage | Environment variables / server secret manager |
| Supabase roles (`anon`, `authenticated`, `service_role`) | Access tiers | App-level roles: `shopper`, `retailer`, `admin`, `super_admin` (from `user_roles`); DB user has plain table grants |

## 4. Business rules preserved verbatim

- Money as integer cents; no floats.
- Receipt submission validation order: offer window → purchase date in window → case-insensitive merchant match → minimum purchase → duplicate fingerprint → per-user limit → budget coverage → rate limit (12/hour).
- Business-rule failures insert a `REJECTED` receipt with a user-readable reason (not a server error); malformed input is a 4xx error with no row.
- Concurrent submission safety: offer row locked during budget consumption; duplicate-fingerprint race surfaces as a friendly rejection.
- Payout: profile/advisory lock serializes requests; one open payout; links all unlinked ledger rows; 500-cent minimum; cancel releases links (balance restored without touching history); complete requires a unique 4–64 char reference.
- Reversal: append-only negative row, offer `spent_cents` reduced not below zero, receipt → `REVERSED`, original ledger untouched; idempotent on repeat.
- Referral: 500 cents per side, no self-referral, no mutual/cyclic referrals, invite cap 20.
- Admin analytics: spending overview (admin), customer summary/merchant breakdown/transactions (super_admin), retailer claim stats without shopper identities.
- Deletion blockers: `wallet_history`, `open_payouts`, `open_claims`, `has_offers`.
- Rate limits: 12 receipt submissions per user per rolling hour, stored in the database (works across instances).

## 5. Data migration ordering (when the cutover happens)

1. `users` (from `auth.users` ⊕ `profiles`; preserve UUIDs; set `password_hash` to an invalid placeholder — users recover via the new password-recovery flow, or import bcrypt/argon2 hashes if exportable).
2. `user_roles` (from `profiles.admin_level`).
3. `offers` (preserve UUIDs and budget counters).
4. `receipts` (recompute fingerprints into the new sha-256 form from raw columns — raw columns are present, so this is deterministic).
5. `referral_bonuses` → `wallet_ledger` (credits) — preserve `reference_key` uniqueness.
6. `payouts` → `payout_entries`.
7. `notifications`, `push_subscriptions`, `saved_offers`, `support_requests`, `todos`.
8. Do **not** import `submit_log` history (start rate-limit windows clean).

Post-import validation: every payout amount equals the sum of its linked ledger rows; no user has more than one open payout; every non-rejected fingerprint is unique; `reserved + spent ≤ budget` on all offers; no ledger row links to more than one payout.
