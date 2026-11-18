# VasoolKaro — Authentication and Security

How the independent backend replaces Supabase Auth and RLS with equivalent (and stronger) controls.

## 1. Identity model

| Concern | Implementation |
|---|---|
| Password storage | argon2id (memory-hard); rehash-on-login when parameters are upgraded |
| Access token | JWT (HS256/EdDSA), 15-minute TTL, claims: `sub` (user id), `role` (shopper/retailer), `typ=access` |
| Refresh token | 32-byte random opaque string; **only its SHA-256 hash** is stored in `sessions`; 30-day TTL; rotated on every refresh (presented token revoked, replacement issued) |
| Session registry | `sessions` row per device (user agent, IP, expiry, revocation) |
| Password reset | single-use random token, hashed at rest, 1-hour expiry; all sessions revoked on success |
| Login rate limit | IP-based sliding window (DB-backed) + per-account lockout after repeated failures |

**Iron rule:** the user id is derived from the verified token on every request. No endpoint trusts a client-supplied user id — this replaces every `auth.uid()` call in the old RPCs.

## 2. Authorization model

Three layers, deny-by-default:

1. **Role dependency** — `require_role("admin")` / `super_admin` checks `user_roles` (server-controlled table; roles granted only by operator scripts, never via API or user-editable metadata — the documented weakness of `profiles.admin_level` is designed out).
2. **Ownership scoping** — repository queries always filter by `current_user.id`; foreign ids yield `404` (no existence oracle).
3. **Write-shape control** — Pydantic request models accept only client-ownable fields. This is the direct replacement for the old column-level grants:

| Old column grant | New control |
|---|---|
| profiles: update only name/phone/DOB/address/preferences | `ProfileUpdateIn` allows exactly those fields |
| notifications: update only `read_at` | `NotificationReadIn { ids }` — nothing else writable |
| offers: no cashback/merchant edit after creation | `OfferUpdateIn` field allow-list + service check |
| support: insert only topic/message | `SupportCreateIn { topic, message }` |
| wallet/payouts/receipts: no client writes at all | no write endpoints exist; services only |

**Defense-in-depth:** the app's database user has plain table grants (no owner rights); the ledger's immutability trigger fires even if application code regresses.

## 3. Financial integrity controls

- Every money-touching request runs in one transaction with explicit row locks (offer budget) or advisory locks (payout serialization).
- Idempotency keys at the database level: `reference_key` (ledger), fingerprint (receipts), payment reference (payouts).
- `wallet_ledger` is append-only: immutability trigger + no application code path updates or deletes rows; corrections are appended reversals.
- Reversal, payout completion/cancellation, and role changes write `audit_log` rows in the same transaction (who, what, when, why).
- Reversal and payout-complete are idempotent or safely state-rejected on repeat.

## 4. Abuse and fraud prevention

| Control | Scope |
|---|---|
| Receipt submissions: 12/user/rolling hour | `rate_limit_events`, DB-backed, works across instances (existing rule) |
| **[new]** IP-level limits on signup, login, refresh, recovery, referral redeem, support, push registration | closes the per-user-only gap documented in the handoff |
| Duplicate receipt fingerprint | partial unique index; race yields friendly rejection |
| One open payout per user | partial unique index |
| Unique payment references | partial unique index |
| Frozen offer economics | cashback/merchant name immutable after creation |
| Referral graph checks | self/mutual/cyclic rejection, 20-invite cap |
| Delete blockers | wallet history, open payouts, open claims, owned offers |
| Push text | never exposes cashback amounts |

## 5. Transport and platform security

- TLS everywhere (nginx/Caddy termination); HSTS.
- CORS: explicit origin allowlist — the wildcard `*` used by the old edge functions is deliberately not copied.
- Security headers: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, minimal CSP for any browser surface.
- Request size limits; strict JSON parsing; Pagination bounds (`page_size ≤ 100`) to prevent export-by-pagination.
- Secrets only via environment/secret manager; never in code, logs, or migrations. `JWT_SECRET` rotation supported via dual-key verification.
- Avatar uploads: format sniffing (JPEG/PNG/WebP), 2 MB cap, randomized object names, served through short-lived signed URLs.
- Dependencies pinned; CI runs ruff + mypy + pytest (see `DEVELOPMENT_GUIDE.md`).

## 6. Threat notes for the money paths

| Threat | Mitigation |
|---|---|
| Forged identity (stolen user id in body) | ids only from verified JWT; signature + `typ` claim checked |
| Replay of refresh token | rotation + hash comparison; reuse of a rotated token revokes the session family |
| Concurrent double-spend | row/advisory locks + CHECK invariants; unique idempotency keys |
| Budget race on hot offers | `SELECT … FOR UPDATE` on the offer row |
| Privilege escalation | roles in a separate table, not editable through any API surface |
| Insider/ops mistakes on money tables | immutability trigger + audit log + least-privilege grants |
| Enumeration (emails, receipts, payouts) | uniform 401/404s; ambiguous auth errors; ownership-scoped queries |

## 7. Verification checklist (carried over from the handoff, adapted)

- A user cannot read another user's profile, receipts, wallet, payouts, notifications, todos, saved offers, or support requests.
- A shopper cannot create or edit offers; a retailer cannot edit cashback or merchant identity after creation.
- No client path inserts or updates ledger rows.
- Duplicate receipts cannot both succeed, including under concurrency.
- Budget cannot be overspent; two open payouts cannot coexist; payout cancellation restores availability without editing history.
- Reversal appends a negative row and is idempotent.
- Rate limits hold across multiple API instances.
- Deletion revokes sessions and obeys financial retention.
- Admin functions enforce `user_roles`, not client metadata.
- All money in integer cents; all money tests use real transactions.
