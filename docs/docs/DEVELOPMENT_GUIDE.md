# VasoolKaro — Development Guide

Practical guide for building, migrating, and testing the new backend.

## 1. Local setup

```bash
# 1. Postgres
docker run -d --name vk-db -e POSTGRES_USER=vasoolkaro \
  -e POSTGRES_PASSWORD=vasoolkaro -e POSTGRES_DB=vasoolkaro \
  -p 5432:5432 postgres:16

# 2. Python 3.12+ environment
cd backend
uv sync                 # or: pip install -e ".[dev]"

# 3. Configuration
cp .env.example .env    # then edit DATABASE_URL, JWT_SECRET, etc.

# 4. Schema
alembic upgrade head

# 5. First admin role (operator action, never an API)
psql $DATABASE_URL -c "INSERT INTO user_roles (user_id, role)
  SELECT id, 'super_admin' FROM users WHERE email = 'you@example.com';"

# 6. Run
uvicorn src.main:app --reload          # API
python -m src.workers.runner           # background worker
```

## 2. Workflow rules

- **Migration first:** any schema change starts with `alembic revision --autogenerate -m "…"`, reviewed by hand (autogenerate misses enum changes and partial indexes), then models are updated to match. Never edit an applied migration.
- **Money is `bigint` cents.** Any new money column is `*_cents bigint`, positive-or-signed per the ledger conventions.
- **New tables** get: UUID pk, FK with explicit `ON DELETE` behavior, indexes for their hot queries, an Alembic migration, and dictionary entries in `DATABASE_DICTIONARY.md`.
- **Business rules live in services**, never in routers or repositories. A service method that touches money opens exactly one transaction and states its lock strategy in the docstring line.
- **Ownership scoping is mandatory:** every repository method for user data takes the owner id as a parameter. There is no "get receipt by id" — only "get receipt by id **and owner**".
- **Enums over free text** for statuses; new states require a migration + this doc update.

## 3. Testing

```bash
pytest                    # unit + integration
pytest tests/money        # financial-integrity suite specifically
```

- Tests run against a throwaway Postgres (testcontainers or a local CI database), never SQLite — the ledger triggers, partial indexes, and lock behavior are Postgres-specific.
- **Concurrency tests are required for money paths:** parallel duplicate receipts (expect one APPROVED + one friendly REJECTED), parallel payout requests (expect one success), budget exhaustion race (expect no overspend).
- Integration tests exercise services against the real schema; routers are tested via the FastAPI test client with dependency overrides for auth.
- Every endpoint contract in `API_REFERENCE.md` has a test asserting status code and error-code envelope.

## 4. Adding an endpoint (checklist)

1. Pydantic schemas (request = field allow-list; response = whitelisted fields).
2. Router method with auth/role dependency and status code from `API_REFERENCE.md` conventions.
3. Service method: business rules, transaction, locks, typed exceptions.
4. Repository methods, owner-scoped.
5. Error-code mapping in `core/errors.py`.
6. Tests, including the abuse case (foreign id → 404, bad role → 403).
7. `API_REFERENCE.md` updated.

## 5. Background jobs

- Jobs are DB-queued rows claimed with `FOR UPDATE SKIP LOCKED` — safe with multiple workers, no lost jobs on restart.
- Enqueue only after the triggering transaction commits.
- Every job is idempotent (e.g. `pushed_at` guard) because at-least-once delivery is the contract.

## 6. Operations

```bash
alembic upgrade head        # release step, before new workers serve traffic
alembic downgrade -1        # only for the immediately previous, unreleased migration
```

- Logs are JSON with `request_id`; correlate with nginx request ids.
- `/readyz` failure → the instance is pulled from rotation; investigate DB connectivity first.
- Restore drills: quarterly, from production backups, verified against ledger-sum invariants.
- Seeding demo offers: use the retailer API or a script that inserts `offers` rows with `owner_id = NULL` (admin-managed), never direct SQL against financial tables.

## 7. Documentation map

| Doc | Read when… |
|---|---|
| `BACKEND_HANDOFF.md` | You need the exact current-product behavior contract |
| `DATABASE_DESIGN.md` | You need table rationale or the design principles |
| `DATABASE_DICTIONARY.md` | You need a column definition |
| `DATABASE_ER_DIAGRAM.md` | You need the relationship picture |
| `SUPABASE_TO_POSTGRES_MAPPING.md` | You are migrating data or wondering why something changed |
| `API_REFERENCE.md` | You are building/calling an endpoint |
| `API_WORKFLOWS.md` | You are touching a multi-table flow |
| `SYSTEM_ARCHITECTURE.md` | You are adding a module or changing layering |
| `AUTHENTICATION_AND_SECURITY.md` | You are touching auth, roles, or money invariants |
