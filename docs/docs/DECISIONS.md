# Architecture decisions

Each record states the context, the decision, and its consequences.

## ADR-001: Supabase as the single backend
**Context.** The app needs persistent data, sign-in, and access rules shared by shoppers and retailers.
**Decision.** Use Supabase for Postgres, authentication, and row-level security. The browser talks to it directly with the public anon key.
**Consequences.** No custom server to run. Security depends on RLS and grants being correct, so every table has an explicit policy set and every function has a revoked-by-default EXECUTE grant. Business rules that must not be bypassed live in Postgres functions.

## ADR-002: Money as integer cents
**Context.** Floating-point values cannot represent money exactly.
**Decision.** Store every amount in cents as an integer, in the database and in app code.
**Consequences.** Arithmetic is exact. Formatting to dollars happens only at display time.

## ADR-003: Validate receipts in the database
**Context.** Client validation can be bypassed, and budgets must never be over-committed when two shoppers claim at once.
**Decision.** `submit_receipt` performs all checks and budget reservation in one transaction, locking the offer row. Failed business rules are saved as rejected claims with a reason.
**Consequences.** The client only shows the outcome. Rejected claims are visible in history, and the logic is in one place.

## ADR-004: Receipt scanning runs in the browser; native OCR is deferred
**Context.** Receipt scanning uses tesseract.js, which runs in the browser. A native phone build would need a different recognition path, and the server-side option requires an edge function plus a provider choice.
**Decision.** Ship scanning on the web only, loaded on demand. Defer native and server-side recognition.
**Consequences.** Scanning works in the browser preview. On phones, shoppers type receipt details. Server-side recognition is deferred and not yet built.

## ADR-005: Lazy-load heavy browser-only code
**Context.** The OCR engine is large and is only needed on the scanner screen.
**Decision.** Import tesseract.js with a dynamic import inside the reader, so it is split into its own chunk and downloaded when a scan starts.
**Consequences.** The first page load does not include the OCR engine. Unused packages are not removed from `package.json` because project rules keep template dependencies; they do not add to the bundle when nothing imports them.

## ADR-006: Generic user-facing errors, detail in the console
**Context.** Raw database and auth messages expose schema details and internal wording.
**Decision.** Map known errors to friendly text. Show a generic message for anything else and log the detail to the console.
**Consequences.** Users see clear next steps; attackers learn little from error text. Support can still see detail in the browser console during debugging.

## ADR-007: Retailer role set only at sign-up
**Context.** If clients could change their account type, any shopper could start managing offers.
**Decision.** The account type is read from sign-up metadata by the trigger that creates the profile. The column is not writable by clients.
**Consequences.** Switching a shopper account to a retailer account needs an administrator action in the database.

## ADR-008: Reversals as compensating ledger rows
**Context.** Receipts can be reversed after cashback was credited, and cashback may already have been paid out.
**Decision.** The ledger is append-only. A reversal is a new negative row linked to the original through `reversal_of`, and related rows share a `transaction_id`. Reversing a credit that was already paid out is allowed and leaves a negative unlinked balance, which is netted against the shopper's next cash-out.
**Consequences.** Balances can be negative until the shopper earns more. Reversals are service-role only, so no UI exists for them yet.

## ADR-009: Cash-outs as links to ledger rows
**Context.** Each cash-out needs an audit trail, and a balance snapshot would hide which credits were paid.
**Decision.** A cash-out links every unlinked ledger row to a payout row. Available balance is the sum of unlinked rows. Cancelling a payout deletes its links, returning the amount to the balance without editing ledger rows.
**Consequences.** Each payout shows its exact transactions. A ledger row can belong to only one payout at a time.
