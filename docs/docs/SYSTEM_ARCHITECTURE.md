# VasoolKaro — System Architecture

Self-hosted FastAPI + PostgreSQL backend. No Supabase at runtime: the app owns identity, authorization, file storage concerns, and background jobs.

## 1. High-level topology

```text
                    ┌──────────────────────────────────────────────────┐
                    │                   your server                    │
                    │                                                  │
  Mobile/Web ──────▶│  nginx (TLS, IP rate-limit edge)                 │
  app clients       │      │                                           │
                    │      ▼                                           │
                    │  FastAPI app (uvicorn workers)                   │
                    │      │                                           │
                    │      ├── routers/      HTTP layer only           │
                    │      ├── services/     business logic, TX logic  │
                    │      ├── repositories/ all SQL via SQLAlchemy    │
                    │      ├── auth/         JWT verify, roles         │
                    │      └── core/         settings, logging, errors │
                    │      │                                           │
                    │      ▼                                           │
                    │  PostgreSQL 16 ◀── Alembic migrations            │
                    │      ▲                                           │
                    │      └── worker process (same image)             │
                    │           push dispatch, email, retries          │
                    └──────────────────────────────────────────────────┘
```

One Postgres instance, one API deployment, one worker process to start; every piece scales horizontally (stateless API, DB-backed rate limits and job queue).

## 2. Project structure

```text
backend/
├── alembic/                      # migration scripts (alembic upgrade head)
│   └── versions/
├── src/
│   ├── main.py                   # app factory, router mounting
│   ├── core/
│   │   ├── config.py             # pydantic-settings, env-only config
│   │   ├── security.py           # argon2id, JWT encode/verify, token hashes
│   │   ├── db.py                 # engine, sessionmaker, session dependency
│   │   ├── logging.py            # JSON logs, correlation ids
│   │   ├── errors.py             # exception → stable error-code mapping
│   │   └── deps.py               # current_user, require_role dependencies
│   ├── modules/
│   │   ├── auth/
│   │   │   ├── router.py         # /auth/* endpoints
│   │   │   ├── schemas.py        # SignupIn, LoginIn, TokenOut …
│   │   │   └── service.py        # registration/login/session transactions
│   │   ├── users/                # /me, profile, avatar, deletion
│   │   ├── offers/               # public catalog + retailer management
│   │   ├── claims/               # receipt submission + history
│   │   ├── wallet/               # balance, ledger, payouts
│   │   ├── referrals/
│   │   ├── notifications/        # inbox, read, push subscriptions
│   │   ├── support/
│   │   ├── todos/
│   │   └── admin/                # analytics, payout settlement, support status
│   ├── workers/
│   │   ├── runner.py             # worker entry point (DB-backed job queue)
│   │   ├── push.py               # Web Push dispatch + endpoint pruning
│   │   └── email.py              # recovery emails, notifications
│   └── common/
│       ├── pagination.py         # page/page_size conventions
│       └── ratelimit.py          # rate_limit_events helper
└── tests/
```

Each module contains `router.py` (HTTP), `schemas.py` (Pydantic I/O), `service.py` (business rules + transaction boundaries), `repo.py` (SQLAlchemy queries), `models.py` (ORM). **Routers never touch the database; services never parse requests; repositories never make business decisions.**

## 3. Layers and transaction boundaries

```text
Request → auth dependency (JWT → current_user)
        → router (parse/validate Pydantic)
        → service (opens one transaction, applies business rules,
                   calls repositories, commits)
        → repository (parameterized SQLAlchemy queries, owner-scoped)
        → response model (whitelisted fields only)
```

- **One transaction per money-touching request**, owned by the service: receipt submission, payout request/complete/cancel, reversal, referral redemption, account deletion.
- **Row locks:** `SELECT … FOR UPDATE` on `offers` (budget), on unlinked ledger rows (payout). **Advisory lock** per user for payout serialization.
- **Commit-then-enqueue:** background jobs (push, email) are enqueued only after commit, into a durable database-backed queue so a crash never loses a notification.
- **Ownership scoping:** every user-data query filters by `current_user.id`; admin queries assert the role from `user_roles` inside the same request. There is no endpoint that accepts a user id as an ownership claim.

## 4. Background jobs

| Job | Trigger | Idempotency |
|---|---|---|
| Push dispatch | after-commit enqueue from receipt flow | `notifications.pushed_at` guard |
| Recovery/transactional email | auth events | single-use token / debounce |
| Rate-limit prune | periodic | window scans are idempotent |
| Session/token cleanup | periodic | idempotent deletes |

The worker runs the same image with a different entry point and can run multiple instances safely (job claims use `FOR UPDATE SKIP LOCKED`).

## 5. Configuration (environment only, no secrets in code)

```
DATABASE_URL=postgresql+psycopg://vasoolkaro:***@localhost:5432/vasoolkaro
JWT_SECRET=<openssl rand -hex 32>          # rotate via kid-based dual keys
ACCESS_TOKEN_TTL=900                       # seconds
REFRESH_TOKEN_TTL=2592000
PUSH_VAPID_PUBLIC_KEY / PUSH_VAPID_PRIVATE_KEY / PUSH_VAPID_SUBJECT
EMAIL_SMTP_URL / EMAIL_FROM
INTERNAL_SERVICE_TOKEN=<random>            # /internal/push/dispatch auth
CORS_ORIGINS=https://app.vasoolkaro.com    # explicit allowlist, no wildcard
```

## 6. Error handling

- All exceptions map to the stable envelope `{ "error": { "code", "message" } }` (`core/errors.py`).
- Business rejections are typed exceptions (`DuplicateReceipt`, `PayoutAlreadyRequested`) raised by services and translated by handlers — HTTP 201-with-REJECTED for receipt rules, 409/422 elsewhere.
- Unhandled exceptions log with a correlation id and return a generic 500; internals never leak.
- 404 is returned for foreign/missing resources alike (no existence oracle).

## 7. Observability

- JSON logs with `request_id`, `user_id` (hashed in non-audit logs), route, latency.
- `/healthz` (liveness) and `/readyz` (DB round-trip) for orchestration.
- Metrics (Prometheus format) on request latency, receipt approval rate, payout queue depth.
- `audit_log` table is the security trail for money-touching actions.

## 8. Deployment

- Single Docker image (API + worker entry points), postgres via managed or self-hosted instance, TLS terminated at nginx/Caddy.
- Migrations run as a release step (`alembic upgrade head`) before new workers serve traffic.
- Backups: nightly base backup + WAL archiving (PITR); quarterly restore drills — the wallet ledger makes restore testing non-negotiable.

## 9. Scalability path

1. **Now:** one API box + one worker. Sufficient for the current scale.
2. **Read growth:** add read-replica for catalog/ledger reads; offers list is cache-friendly (60 s TTL).
3. **Write growth:** rate-limit pruner keeps windows small; ledger inserts are append-only (index-friendly); partition `receipts`/`wallet_ledger` by year if they grow past tens of millions of rows.
4. **Multi-instance:** already supported — limits and locks live in Postgres, never in process memory.
