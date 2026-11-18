# VasoolKaro — Independent Backend Documentation

Design package for rebuilding the VasoolKaro receipt-cashback backend on **FastAPI + self-hosted PostgreSQL**, fully independent of Supabase. The existing production Supabase database was used **only as a behavioral reference** (via the handoff document); it is not a runtime dependency and was not modified.

## Start here

| If you want to… | Read |
|---|---|
| Understand the product and current backend contract | [BACKEND_HANDOFF.md](BACKEND_HANDOFF.md) — auth model, all 14 tables, RPC contracts, RLS, triggers, workflows, migration history |
| See the new database design and why | [DATABASE_DESIGN.md](DATABASE_DESIGN.md) |
| Look up any column, type, or constraint | [DATABASE_DICTIONARY.md](DATABASE_DICTIONARY.md) |
| See the entity-relationship diagram | [DATABASE_ER_DIAGRAM.md](DATABASE_ER_DIAGRAM.md) |
| Migrate data off Supabase | [SUPABASE_TO_POSTGRES_MAPPING.md](SUPABASE_TO_POSTGRES_MAPPING.md) |
| Build or call an endpoint | [API_REFERENCE.md](API_REFERENCE.md) — 44 endpoints across 10 modules |
| Understand a multi-table flow | [API_WORKFLOWS.md](API_WORKFLOWS.md) — receipt→wallet→payout, reversals, referrals, deletion |
| Understand the code layout and layering | [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) |
| Review the security model | [AUTHENTICATION_AND_SECURITY.md](AUTHENTICATION_AND_SECURITY.md) |
| Set up a dev environment | [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) |

## The design in one page

- **Identity:** one `users` table (merging `auth.users` + `profiles`), argon2id passwords, 15-minute JWTs + rotating hashed refresh tokens in `sessions`. Roles live in a server-controlled `user_roles` table — the client-editable-metadata weakness is designed out.
- **Money:** `bigint` cents everywhere; an append-only `wallet_ledger` (immutability trigger retained) with unique idempotency keys; budget and payout operations commit in single transactions with explicit row/advisory locks; partial unique indexes block duplicate receipts, double payouts, and reused payment references.
- **Supabase replacements:** RLS → owner-scoped repository queries + field-allow-list schemas; `SECURITY DEFINER` RPCs → transactional service functions; the `pg_net` push trigger → a durable worker; the avatars bucket → app-managed storage; `submit_log` → a generalized `rate_limit_events` limiter that also adds the recommended per-IP controls.
- **New, clearly separated from existing behavior:** password recovery, sessions, `audit_log`, admin support-status endpoint, soft-delete retention path for accounts with financial history. Everything else preserves the current product's rules exactly (12 receipts/hour limit, 500-cent payout minimum and referral bonus, frozen offer economics, deletion blockers, friendly receipt rejections).

## Build order

1. Schema via Alembic (`DATABASE_DESIGN.md`) → 2. auth + users → 3. offers → 4. receipt submission transaction → 5. wallet ledger + referrals → 6. payouts → 7. reversals → 8. notifications + push worker → 9. deactivation/deletion → 10. admin → 11. IP rate limits → 12. data migration per the mapping document.
