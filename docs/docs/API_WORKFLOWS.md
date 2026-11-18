# VasoolKaro — API Workflows

End-to-end flows across the new backend, with the tables and transaction boundaries involved in each step. Business behavior matches the current product (see `BACKEND_HANDOFF.md`); improvements are marked **[new]**.

## 1. Signup and login

```text
Client                          Backend
  │  POST /auth/signup             │
  │──────────────────────────────▶ │  TX①: insert users (argon2id hash,
  │                                │       referral_code generated)
  │  ◀── 201 tokens + profile ──── │       insert sessions (refresh hash)
  │                                │
  │  POST /auth/login              │
  │──────────────────────────────▶ │  verify argon2id; TX②: clear
  │  ◀── 200 tokens ────────────── │  deactivated_at (reactivation);
  │                                │  insert sessions
```

- Retailer signup requires `business_name`; DOB enforces age ≥ 13 and is set-once.
- **[new]** Refresh rotation on `/auth/refresh`; failed logins are IP-rate-limited.

## 2. Receipt submission → wallet → notification (the core flow)

Single API call: `POST /claims/receipts`. Everything below happens in **one database transaction** — a failure anywhere rolls back all of it.

```text
                         ┌──────────────── POST /claims/receipts ─────────────────┐
 1. Validate input       │ merchant 2–80, receipt# 3–40, total 1–10M cents,       │
    (4xx if malformed,   │ date not future, card_last4 = 4 digits                 │
     no row written)     └────────────────────────────────────────────────────────┘
 2. BEGIN TX
 3. SELECT offer FOR UPDATE            (offers row locked → budget races serialized)
 4. Eligibility checks, in order:      offer active → within window → purchase date in
    window → merchant name match (case-insensitive) → total ≥ min_purchase →
    fingerprint unused (non-rejected) → user claims < per_user_limit →
    budget remaining ≥ cashback → rate limit < 12/hour (rate_limit_events)
 5a. All pass  → insert receipt APPROVED, cashback_cents = offer cashback
                → offers.spent_cents += cashback            (budget invariant CHECK)
                → insert wallet_ledger credit                (reference_key = receipt:<id>,
                                                              unique ⇒ idempotent)
                → insert notification RECEIPT_APPROVED       (unique receipt+kind)
                → insert rate_limit_events row
 5b. Rule fail → insert receipt REJECTED, cashback 0, user-readable reason
                → insert notification RECEIPT_REJECTED
                (still HTTP 201 — a business rejection is not a server error)
 6. COMMIT
 7. After commit: enqueue push job; worker sends Web Push (24h TTL),
    prunes dead endpoints (404/410), sets notifications.pushed_at
 8. Client reloads GET /claims/receipts + GET /wallet/balance
```

- Duplicate-fingerprint race (two simultaneous identical claims): the second commit hits the partial unique index and is converted to a friendly `duplicate_receipt` rejection — never a 500.
- Approval auto-credits the wallet exactly as the old `receipts_wallet_ledger` trigger did, but as explicit transactional code.

## 3. Wallet → payout → admin settlement

```text
Shopper                             Backend                              Admin
  │ POST /wallet/payouts               │                                    │
  │───────────────────────────────────▶│ BEGIN TX                           │
  │                                    │  advisory lock (user)              │
  │                                    │  reject 2nd open payout            │
  │                                    │  select unlinked ledger rows       │
  │                                    │  FOR UPDATE                        │
  │                                    │  insert payout_entries links       │
  │                                    │  amount = Σ linked rows            │
  │                                    │  reject < 500 cents                │
  │                                    │  insert payout REQUESTED           │
  │ ◀── 201 ────────────────────────── │ COMMIT                             │
  │                                    │                                    │
  │                          (wallet available balance is now 0;             │
  │                           ledger history unchanged)                      │
  │                                                                         │
  │                                    │   GET /admin/payouts ─────────────▶│
  │                                    │   POST /admin/payouts/:id/complete │
  │                                    │    BEGIN TX:                       │
  │                                    │     payout REQUESTED? else 409     │
  │                                    │     reference unique? else 409     │
  │                                    │     → PAID + settled_at            │
  │                                    │     → audit_log entry              │
  │                                    │    COMMIT                          │
  │ ◀── GET /wallet/payouts shows PAID ────────────────────────────────────  │
```

**Cancellation path** (`/admin/payouts/{id}/cancel`): same state check; delete that payout's `payout_entries` rows → the linked ledger rows become available again; set `CANCELLED` + note + `settled_at`; audit-logged. Ledger history is never edited — the existing release-by-unlinking design is preserved.

## 4. Reversal (clawback) — admin/internal only

```text
POST /internal/receipts/{receiptId}/reverse   { reason: "3–200 chars" }
  BEGIN TX
    receipt is APPROVED or PAID? else 409
    find original RECEIPT_CASHBACK ledger row
    insert REVERSAL row: amount negative, reversal_of = original.id,
                         reference_key = reversal:<receipt>:<seq>   (idempotent)
    offers.spent_cents = greatest(0, spent - cashback)
    receipt.status = REVERSED
  COMMIT
```

The original ledger row is untouched — corrections are appended, matching the append-only financial model.

## 5. Referral redemption

```text
POST /referrals/redeem { code }
  BEGIN TX
    resolve code → inviter (404 if unknown)
    reject self-referral (409)
    reject mutual/cyclic referral (409)
    reject if pair already rewarded (409, unique partial index backstop)
    reject if inviter exceeds 20-invite cap (422)
    insert referral_bonuses ×2 (invitee INVITE_ACCEPTED, inviter INVITE_SENT)
    insert wallet_ledger credits ×2 (reference_key = referral_bonus:<id>)
  COMMIT
  → both wallets grow by 500 cents each; push/notification unaffected (existing design)
```

## 6. Notifications and push delivery

```text
(receipt approval TX inserts notification row)
        │ after commit: enqueue job
        ▼
Push worker: load notification → skip if pushed_at set (idempotent)
  → load user's push_subscriptions (respects notify_receipts preference)
  → send Web Push, TTL 24h, payload: title + merchant name only,
    never cashback amounts (existing privacy rule)
  → prune subscriptions answered 404/410
  → set notifications.pushed_at
Client: GET /notifications → PATCH /notifications/read { ids }
```

## 7. Account deactivation vs deletion

```text
Deactivate: POST /me/deactivate → users.deactivated_at = now()
  Login still works; login auto-reactivates (clears deactivated_at).
  Existing design preserved.

Delete: POST /me/delete
  BEGIN TX — blockers re-checked:
    wallet_history   (any ledger row)        → 409 reason=wallet_history
    open_payouts     (REQUESTED payout)      → 409 reason=open_payouts
    open_claims      (SUBMITTED/REVIEWING)   → 409 reason=open_claims
    has_offers       (retailer w/ offers)    → 409 reason=has_offers
  no blockers:
    delete receipts, saved_offers, todos, notifications, sessions…
    financial rows are RESTRICT-protected → account is anonymized
    (name/email cleared, deleted_at set) **[new: explicit retention path]**
    → audit_log entry
  revoke all sessions
```

## 8. Retailer offer lifecycle

```text
POST /retailer/offers         → offer active with full budget
PATCH /retailer/offers/:id    → title/description/address/budget/ends_at/active only;
                                cashback + merchant name frozen (existing rule)
                                budget ≥ reserved + spent enforced
POST /claims/receipts         → shoppers claim; spent_cents grows
GET /retailer/offers/stats    → claims/approved/rejected/approved_total_cents
                                per own offer, no shopper identities
active=false                  → offer disappears from the catalog; history intact
```

## 9. Offer availability display rule (unchanged)

An offer is shown to shoppers when: `active = true` AND `ends_at > now()` AND `budget − reserved − spent > 0`. `GET /offers` applies exactly these predicates.

## 10. Money-safety invariants recap (enforced across all workflows)

| Invariant | Enforced by |
|---|---|
| No double credit | unique `wallet_ledger.reference_key` |
| No overspent offer | offer row lock + `reserved + spent ≤ budget` CHECK |
| No duplicate claim | partial unique fingerprint (non-rejected) |
| No double payout | partial unique open payout + advisory lock |
| No balance fabrication | payout amount = Σ linked ledger rows, in one TX |
| Immutable history | ledger UPDATE/DELETE trigger + grants |
| Unique settlement | partial unique `payment_reference` WHERE PAID |
| Traceable money actions | `audit_log` rows written in the same TX **[new]** |
