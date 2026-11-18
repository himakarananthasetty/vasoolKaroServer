# VasoolKaro — ER Diagram

Mermaid diagram of the new PostgreSQL schema. Cardinality notation: `||—o{` one-to-zero-or-more, `||—o|` one-to-zero-or-one.

```mermaid
erDiagram
    USERS ||--o{ SESSIONS : "owns"
    USERS ||--o{ PASSWORD_RESET_TOKENS : "requests"
    USERS ||--o{ USER_ROLES : "holds"
    USERS |o--o| USERS : "referred_by"
    USERS ||--o{ OFFERS : "owns (retailer)"
    USERS ||--o{ RECEIPTS : "submits"
    USERS ||--o{ SAVED_OFFERS : "bookmarks"
    USERS ||--o{ REFERRAL_BONUSES : "receives"
    USERS ||--o{ WALLET_LEDGER : "owns"
    USERS ||--o{ PAYOUTS : "requests"
    USERS ||--o{ NOTIFICATIONS : "receives"
    USERS ||--o{ PUSH_SUBSCRIPTIONS : "registers"
    USERS ||--o{ SUPPORT_REQUESTS : "opens"
    USERS ||--o{ TODOS : "plans"
    USERS ||--o{ AUDIT_LOG : "acts in"

    OFFERS ||--o{ RECEIPTS : "claimed by"
    OFFERS ||--o{ SAVED_OFFERS : "saved as"
    RECEIPTS ||--o{ NOTIFICATIONS : "triggers"
    RECEIPTS ||--o{ WALLET_LEDGER : "credits (source_id)"
    REFERRAL_BONUSES ||--o{ WALLET_LEDGER : "credits (source_id)"
    WALLET_LEDGER |o--o| PAYOUT_ENTRIES : "settled by"
    PAYOUTS ||--o{ PAYOUT_ENTRIES : "contains"
    WALLET_LEDGER |o--o| WALLET_LEDGER : "reversal_of"

    USERS {
        uuid id PK
        citext email UK
        text password_hash
        varchar full_name
        enum account_type "shopper|retailer"
        varchar business_name
        varchar referral_code UK "immutable"
        uuid referred_by FK
        boolean notify_offers
        boolean notify_receipts
        boolean marketing_opt_in
        boolean personalised_offers
        timestamptz deactivated_at
        timestamptz deleted_at
    }
    USER_ROLES {
        uuid user_id PK FK
        enum role PK "admin|super_admin"
        timestamptz granted_at
    }
    SESSIONS {
        uuid id PK
        uuid user_id FK
        bytea token_hash UK "sha256"
        inet ip_address
        timestamptz expires_at
        timestamptz revoked_at
    }
    PASSWORD_RESET_TOKENS {
        uuid id PK
        uuid user_id FK
        bytea token_hash UK
        timestamptz expires_at
        timestamptz used_at
    }
    OFFERS {
        uuid id PK
        uuid owner_id FK "retailer"
        varchar merchant_name "immutable"
        varchar merchant_address
        varchar title
        text description
        varchar category
        bigint cashback_cents "1-5000 immutable"
        bigint budget_cents
        bigint reserved_cents
        bigint spent_cents
        bigint min_purchase_cents
        smallint per_user_limit "1-100"
        timestamptz starts_at
        timestamptz ends_at
        boolean active
    }
    RECEIPTS {
        uuid id PK
        uuid user_id FK
        uuid offer_id FK
        varchar merchant_name
        date purchase_date
        bigint total_cents
        varchar receipt_number
        varchar card_last4
        bytea fingerprint "UK where not REJECTED"
        enum status "SUBMITTED..REVERSED"
        bigint cashback_cents
        text rejection_reason
        timestamptz submitted_at
        timestamptz decided_at
    }
    WALLET_LEDGER {
        uuid id PK
        uuid user_id FK
        enum entry_type "CASHBACK|REFERRAL|REVERSAL"
        bigint amount_cents "signed"
        uuid source_id
        varchar reference_key UK "idempotency"
        varchar description
        uuid transaction_id
        uuid reversal_of FK "self"
        timestamptz created_at "append-only"
    }
    PAYOUTS {
        uuid id PK
        uuid user_id FK
        enum method "UPI|CASH"
        varchar upi_id
        bigint amount_cents
        enum status "REQUESTED|PAID|CANCELLED"
        varchar payment_reference "UK where PAID"
        varchar note "required when CANCELLED"
        timestamptz requested_at
        timestamptz settled_at
    }
    PAYOUT_ENTRIES {
        uuid ledger_id PK FK
        uuid payout_id FK
    }
    REFERRAL_BONUSES {
        uuid id PK
        uuid user_id FK
        bigint amount_cents
        enum reason "INVITE_ACCEPTED|INVITE_SENT"
        uuid counterpart_id FK
    }
    SAVED_OFFERS {
        uuid id PK
        uuid user_id FK
        uuid offer_id FK
    }
    NOTIFICATIONS {
        uuid id PK
        uuid user_id FK
        enum kind "APPROVED|REJECTED"
        uuid receipt_id FK
        varchar merchant_name
        bigint cashback_cents
        timestamptz read_at
        timestamptz pushed_at
    }
    PUSH_SUBSCRIPTIONS {
        uuid id PK
        uuid user_id FK
        text endpoint UK
        varchar p256dh
        varchar auth_key
    }
    SUPPORT_REQUESTS {
        uuid id PK
        uuid user_id FK
        enum topic
        varchar message
        enum status "OPEN|ANSWERED|CLOSED"
    }
    TODOS {
        uuid id PK
        uuid user_id FK
        varchar title
        date due_on
        boolean completed
    }
    RATE_LIMIT_EVENTS {
        bigint id PK
        varchar subject_kind "user|ip"
        text subject_id
        varchar action
        timestamptz occurred_at
    }
    AUDIT_LOG {
        bigint id PK
        uuid actor_user_id FK
        varchar actor_kind
        varchar action
        varchar entity_type
        text entity_id
        jsonb detail
    }
    RATE_LIMIT_EVENTS ||--o{ RATE_LIMIT_EVENTS : "no FK (limiter only)"
    AUDIT_LOG }o--o| USERS : "actor"
```

## Key integrity flows the diagram encodes

1. **Money path:** `receipts`/`referral_bonuses` → `wallet_ledger` (append-only, `reference_key` idempotent) → `payout_entries` → `payouts`. Ledger rows are never edited; reversals are new negative rows.
2. **Budget path:** `offers.spent_cents` moves only inside the receipt-approval transaction, guarded by `reserved + spent <= budget` and a row lock on the offer.
3. **Identity path:** everything user-owned hangs off `users`; financial tables (`wallet_ledger`, `payouts`) use `ON DELETE RESTRICT` so account deletion can never erase financial history, while convenience tables cascade.
4. **States:** one open payout per user (partial unique), one notification per receipt outcome (unique `(receipt_id, kind)`), duplicate receipts blocked (partial unique fingerprint).
