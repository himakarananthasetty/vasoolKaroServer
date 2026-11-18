# Data model

All money is stored as integer cents. Timestamps are `timestamptz`. Every table has row-level security enabled.

## Tables

### `profiles`
One row per user, created by the sign-up trigger.
- `id` (references the auth user), `full_name`, `account_type` (`shopper` or `retailer`), `business_name`, `referral_code` (unique), timestamps.
- Shoppers read only their own row. Writable by the client: `full_name`, `phone_number`, `date_of_birth` (only while empty), `address`, `notify_offers`, `notify_receipts`, `marketing_opt_in`, `personalised_offers`, and `updated_at`.
- Read-only to the client: `email`, `id`, referral fields, `account_type`, `admin_level`, and `deactivated_at`.
- `phone_number` must match `^\+?[0-9 ()-]{7,20}$`.
- `address` is at most 200 characters.
- `date_of_birth` is set once and then locked by the `guard_profile_changes` trigger. The trigger also rejects anyone younger than 13.
- `deactivated_at` is set by `deactivate_my_account` and cleared by `reactivate_my_account`. Sign-in calls reactivation.

### `offers`
Cashback offers, created by retailers or seeded.
- `owner_id` (retailer), `merchant_name`, `merchant_address` (5 to 140 characters), `title`, `description`, `category`.
- `cashback_cents`, `budget_cents`, `reserved_cents`, `spent_cents`, `min_purchase_cents`, `per_user_limit`.
- `starts_at`, `ends_at`, `active`, `created_at`.
- Constraints: cashback and limits positive, reserved plus spent not above budget, end after start.
- Shoppers see only rows where `active = true`. An offer is shown as available when it is active, its end date is in the future, and budget remains (`budget - reserved - spent > 0`).

### `receipts`
One row per claim.
- `user_id` (defaults to the signed-in user), `offer_id`, `merchant_name`, `purchase_date`, `total_cents`, `receipt_number`, `card_last4`.
- `fingerprint` (used to block duplicate receipts that are not rejected), `status`, `cashback_cents`, `rejection_reason`, timestamps.
- Statuses: `SUBMITTED`, `REVIEWING`, `APPROVED`, `PAID`, `REJECTED`, `REVERSED`. Rejected rows must carry a reason.
- `REVERSED` means the cashback was taken back by `reverse_receipt_credit`.
- Shoppers read their own rows. Writes happen only through `submit_receipt` and `reverse_receipt_credit`.

### `wallet_ledger`
Append-only record of every wallet movement. Rows are never updated or deleted (`wallet_ledger_immutable` trigger).
- `user_id`, `entry_type` (`RECEIPT_CASHBACK`, `REFERRAL_BONUS`, `REVERSAL`), `amount_cents` (positive for credits, negative for reversals), `description`, `reference_key` (unique), `source_id`.
- `transaction_id` groups the rows that belong to one business event. `reversal_of` points from a `REVERSAL` row to the original row.
- A reversal row must be negative and carry `reversal_of`. Other rows must be positive with no `reversal_of`.
- Shoppers read their own rows.

### `payouts`
A shopper's request to be paid out of their wallet.
- `user_id`, `method` (`UPI` or `CASH`), `upi_id` (required for UPI), `amount_cents` (positive), `status` (`REQUESTED`, `PAID`, `CANCELLED`), `payment_reference` (required when PAID, unique), `note` (required when CANCELLED), `requested_at`, `settled_at`.
- One `REQUESTED` payout per user at a time.
- Shoppers read their own rows. Writes happen only through `request_payout` and the admin functions.

### `payout_entries`
Links a ledger row to the payout that settles it. `ledger_id` is the primary key, so each ledger row belongs to at most one payout.
- Wallet available balance is the sum of ledger rows with no link here. Cancelling a payout deletes its links, which returns the amount to the balance without editing any ledger row.
- Shoppers read the links for their own payouts.

### `referral_bonuses`
Bonuses earned from referrals, written only by `redeem_referral_code`. Shoppers read their own rows.

### `saved_offers`
Offers a shopper has bookmarked.
- `user_id` (defaults to the signed-in user), `offer_id` (cascade delete), unique per user and offer.
- Shoppers can select, insert, and delete their own rows.

### `support_requests`
A message a shopper sends to support.
- `id`, `user_id` (defaults to the signed-in user, cascade delete), `topic` (`ACCOUNT`, `CASHBACK`, `OFFERS`, `OTHER`), `message` (10 to 2000 characters), `status` (`OPEN`, `ANSWERED`, `CLOSED`), `created_at`.
- Shoppers read and create only their own rows. Clients can set only `topic` and `message`.

### `todos`
Personal planner to-dos, shown on the calendar in the Wallet tab.
- `id`, `user_id` (defaults to the signed-in user, cascade delete), `title` (1 to 200 characters after trimming), `due_on` (date), `completed` (boolean, default false), `created_at`.
- Index on `(user_id, due_on)` for month lookups.
- Shoppers can select, insert, update, and delete only their own rows. Insert and update are column-restricted to `title`, `due_on`, and `completed`.

### `notifications`
In-app alerts about receipt outcomes, created by a database trigger on `receipts`.
- `id`, `user_id` (defaults to the signed-in user, cascade delete), `kind` (`RECEIPT_APPROVED` or `RECEIPT_REJECTED`), `receipt_id` (cascade delete), `merchant_name`, `cashback_cents`, `read_at` (null until read), `created_at`.
- Unique on `(receipt_id, kind)` so each outcome alerts once.
- Index on `(user_id, created_at)`.
- `pushed_at` (null until a push has been delivered or attempted) so an alert is never pushed twice.
- Shoppers read only their own rows and can set `read_at`. Clients cannot insert or delete rows.

### `push_subscriptions`
One row per browser or device that opted into push alerts.
- `user_id` (defaults to the signed-in user, cascade delete), `endpoint` (unique HTTPS URL, at most 2048 characters), `p256dh`, `auth_key` (encryption keys, at most 256 characters each), `created_at`.
- Shoppers read and delete only their own rows. Direct insert and update are revoked from every client role; rows are created only by `register_push_subscription`.

## Functions

| Function | Caller | Purpose |
| --- | --- | --- |
| `handle_new_user` | Auth trigger | Creates the profile, reads `account_type` and `business_name` from sign-up metadata |
| `submit_receipt` | Shopper | Validates a receipt, checks offer window, store name, minimum, duplicates and limit, reserves budget, stores approved or rejected claim |
| `redeem_referral_code` | Shopper | Applies a referral code once and records the bonus |
| `my_offer_claim_stats` | Retailer | Returns claim counts and totals for the retailer's own offers, no shopper identities |
| `my_wallet_balance_cents` | Shopper | Returns the sum of the shopper's ledger rows not yet linked to a payout |
| `request_payout` | Shopper | Links all unlinked ledger rows to a new payout and rejects amounts under the 500 cent minimum |
| `admin_list_payouts` | Admin | Lists all payouts with the shopper's name and email |
| `admin_payout_transactions` | Admin | Lists the ledger rows linked to one payout |
| `admin_complete_payout` | Admin | Marks a requested payout as paid with a unique reference |
| `admin_cancel_payout` | Admin | Cancels a requested payout and releases its linked rows back to the balance |
| `notifications_from_receipt` | Trigger on `receipts` | Creates an approval or rejection alert when a receipt is inserted or its status changes to APPROVED or REJECTED, if the shopper has receipt notifications on. Not callable by clients |
| `register_push_subscription` | Shopper | Saves or refreshes the caller's push subscription after checking the endpoint and keys; always stores the caller's own id |
| `dispatch_notification_push` | Trigger on `notifications` | Calls the `send-push` edge function through the database HTTP extension when an alert is created; does nothing until the dispatch secrets are stored in the vault. Not callable by clients |
| `guard_profile_changes` | Trigger on `profiles` | Blocks email changes, changes to a set date of birth, and dates of birth under 13. Not callable by clients |
| `deactivate_my_account` | Shopper | Sets `deactivated_at` on the caller's profile |
| `reactivate_my_account` | Shopper | Clears `deactivated_at` on the caller's profile after sign-in |
| `reverse_receipt_credit` | Service role | Writes a compensating `REVERSAL` row for an approved or paid receipt and marks the receipt `REVERSED` |

All functions are `SECURITY DEFINER` with a fixed `search_path`. EXECUTE is granted to `authenticated` only.

## Grants summary

| Table | `authenticated` |
| --- | --- |
| `profiles` | select; update (full_name, phone_number, date_of_birth, address, preference flags) |
| `support_requests` | select; insert (topic, message) |
| `offers` | select; insert (retailer columns); update (listed columns) |
| `receipts` | select |
| `wallet_ledger` | select |
| `payouts` | select |
| `payout_entries` | select |
| `referral_bonuses` | select |
| `saved_offers` | select, insert, delete |
| `notifications` | select; update (read_at) |
| `push_subscriptions` | select; delete (own rows); inserts only via `register_push_subscription` |
| `todos` | select; insert and update (title, due_on, completed); delete |
| `anon` | none |

## Account deletion

The `delete-account` edge function (JWT verification on) deletes the caller's account only when none of these exist:
- `wallet_history`: any `wallet_ledger` row. Ledger rows are immutable, so an account with money history cannot be removed.
- `open_payouts`: any `REQUESTED` payout.
- `open_claims`: any receipt in `SUBMITTED` or `REVIEWING`.
- `has_offers`: any offer owned by the account.

If a blocker exists, the function returns `{ ok: false, reason }` and the app shows the matching message. Otherwise it removes the caller's receipts, saved offers, and todos, then deletes the auth user, which cascades to the profile.
