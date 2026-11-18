# VasoolKaro Backend — Setup and Run Guide

The backend is an independent FastAPI + PostgreSQL service. Supabase is not used
at runtime: the app talks to Postgres directly through SQLAlchemy, and all
authorization lives in the service layer.

## 1. Prerequisites

- Python 3.11+
- PostgreSQL 14+ (any hosted or local instance; Supabase's Postgres works too)

## 2. Install

```bash
cd backend
python3 -m pip install --break-system-packages \
    "fastapi>=0.110" "uvicorn[standard]" "sqlalchemy>=2.0" alembic \
    "pydantic>=2" pydantic-settings "psycopg[binary]" \
    argon2-cffi PyJWT email-validator python-multipart
```

## 3. Configure

```bash
cp .env.example .env
# edit .env: set DATABASE_URL and a strong JWT_SECRET
```

The app reads `DATABASE_URL` (psycopg driver spelling:
`postgresql+psycopg://user:password@host:5432/dbname`).

## 4. Run migrations

```bash
DATABASE_URL="postgresql+psycopg://..." python3 -m alembic upgrade head
```

Migration `0001_initial` creates all 17 tables, the 10 enum types, and every
constraint (partial unique indexes for receipt fingerprints, one-open-payout,
paid-reference uniqueness, ledger sign rules).

## 5. Start the server

```bash
DATABASE_URL="postgresql+psycopg://..." python3 -m uvicorn src.main:app --port 8000
```

- Health: `GET /healthz` (liveness) and `GET /readyz` (checks the DB round-trip)
- OpenAPI: `GET /docs`

## 6. Smoke-test the full business loop

```bash
# Register a retailer
curl -s -X POST localhost:8000/api/v1/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"email":"shop@example.com","password":"Str0ng!pass9","full_name":"Shop Owner",
       "account_type":"retailer","business_name":"Meera Stores","date_of_birth":"1990-01-01"}'
# -> {"access_token": "...", "refresh_token": "...", "user": {...}}

# Create an offer (with the retailer token)
curl -s -X POST localhost:8000/api/v1/retailer/offers -H "Authorization: Bearer $RT" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Deepavali Cashback","description":"5% back","merchant_name":"Meera Stores",
       "category":"GROCERY","cashback_cents":5000,"budget_cents":100000,
       "min_purchase_cents":50000,"per_user_limit":2,
       "starts_at":"2026-11-01T00:00:00Z","ends_at":"2030-12-31T00:00:00Z"}'

# Register a shopper, submit a receipt, then:
#   GET /api/v1/wallet/balance  -> available_cents 5000
#   POST /api/v1/wallet/payouts {"method":"UPI","upi_id":"meera@upi"}
# Admin payout settlement: POST /api/v1/admin/payouts/{id}/complete (super_admin role,
# provisioned by inserting the user_role row out-of-band).
```

## 7. Tests

The test suite runs against a real Postgres. In this sandbox (and anywhere
without a system Postgres) a disposable wire-protocol Postgres is provided:

```bash
cd backend/tests
npm install                      # installs @electric-sql/pglite + pglite-socket
node pglite-server.cjs &         # disposable Postgres on 127.0.0.1:54329

cd ..
DATABASE_URL="postgresql+psycopg://postgres:postgres@127.0.0.1:54329/postgres" \
    python3 -m pytest tests/test_auth.py tests/test_offers.py tests/test_claims.py \
                      tests/test_wallet.py tests/test_admin.py tests/test_misc.py
```

45 tests cover: signup/login/refresh-rotation/session-revocation, role
authorization (403 paths), offer CRUD + budget guards, receipt eligibility
order (window, merchant, minimum, duplicate fingerprint, per-user limit,
budget), wallet credit consistency, payout minimum + one-open-payout rule,
admin payout complete/cancel (balance restoration, payment-reference
uniqueness), referral rewards + self/duplicate rejection, notifications,
todos, support requests, profile updates.

Against a regular Postgres, point `DATABASE_URL` at it and run the same
command. Tests create unique emails/receipt numbers and clean rate-limit
rows between cases, so they are safe to re-run.

## 8. Runtime adapters

| Capability | Default behavior | To enable |
|---|---|---|
| Email (password recovery) | Token logged, not sent | Set `EMAIL_SMTP_URL` |
| Web Push | No-op dispatch | Set `PUSH_VAPID_*` keys + `pywebpush` |
| Admin/super_admin roles | Not self-service | Insert `user_roles` row out-of-band |

## 9. Project layout

```
backend/
  alembic/versions/0001_initial.py   # schema migration (52 DDL statements)
  src/
    main.py            # app factory, CORS, error envelope, router mounting
    core/              # config, db session, errors, security (argon2id + JWT), logging
    db/                # models (17 tables), DDL emitter
    auth/              # signup, login, refresh rotation, sessions, recovery, roles
    users/             # profile, deactivate/reactivate, delete (blockers), avatar
    offers/            # browse, retailer CRUD/stats, saved offers
    claims/            # receipt submission transaction (eligibility + credit)
    wallet/            # balance, ledger, payouts
    referrals/         # code redemption, bonuses
    notifications/     # in-app feed, mark-read, push subscriptions
    support/ todos/    # user CRUD modules
    admin/             # analytics, payout settlement, customer reports
    internal/          # token-authenticated push dispatch for workers
```
