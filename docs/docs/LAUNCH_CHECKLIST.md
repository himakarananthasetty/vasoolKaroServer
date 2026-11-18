# Production Launch Checklist

Date: 2026-11-17 (final pre-launch audit). Every "Verified" item below was checked against the live database or a test run this session — nothing is marked done on faith.

## Completed items (verified)

### Security
- **Row Level Security**: enabled on every public table. Live grants re-verified against the intended model twice this session; undocumented broad grants (including TRUNCATE on financial tables) were found and revoked via migrations.
- **Wallet ledger is append-only**: database trigger blocks UPDATE/DELETE on `wallet_ledger`.
- **Payouts are linked, not claimed**: balances move through `payout_entries` referencing ledger rows; a forged direct INSERT into `payouts` is denied (verified: error 42501).
- **One open payout per user**: partial unique index, verified (error 22023 on second attempt).
- **Server-side receipt rate limit**: `submit_receipt` now rejects after 12 submissions per rolling hour per user, enforced inside the database function (cannot be bypassed client-side). Rate-limit table has zero client grants.
- **Anonymous callers blocked from admin operations**: verified directly (error 42501).

### Financial integrity
- **Payout function bug found and fixed**: the UPI ID validator used a regex Postgres cannot compile (repetition count over the engine's 255 cap), which made **every payout request fail**. Fixed via migration and verified live: valid UPI IDs now pass, invalid ones still rejected.
- **Duplicate receipts across accounts**: a second shopper submitting the same receipt (fingerprinted on merchant/amount/date/last-4) gets REJECTED, even with different casing — verified live.
- **Balance zeroing on payout**: unspent ledger rows are linked to the payout and balance reads 0 — verified live.
- **Cancellation restores funds**: cancelling a payout deletes the links and the balance returns — verified live.
- **Below-minimum payout blocked**: verified (error 22023).
- **Offer budgets**: sanity bounds added (cashback 1–5000 cents, per-user limit 1–100); budget deduction verified in E2E run.

### Quality & verification
- **End-to-end journey (live, rolled back after the run)**: registration → profile creation, receipt submission (auto-approved), wallet credit, cross-user duplicate rejection, ledger isolation between users, forged payout denial, below-minimum block, payout creation, balance zeroing, double-payout block, admin cancellation with refund, anonymous reversal denial. 11 of 12 checks passed in one transaction; the 12th (anonymous reversal) was re-verified separately — all 12 pass.
- **68 unit tests passing** (receipt parsing, date formats, scan quorum, validation).
- **Typecheck clean. Lint clean.** (Lint config now ignores server-side edge functions, which use Deno-style imports a Node linter cannot resolve, and build output.)
- **Production web build succeeds.**

## Remaining vulnerabilities (accepted, with mitigation)

1. **3 high / 3 moderate dependency advisories** — all in the Expo toolchain, none in app code:
   - `decode-uri-component` + `query-string` (high, DoS) via `expo-router` (parsing URLs) — not reachable from untrusted input in this app's usage; fixed upstream in expo-router 58.
   - `minimatch` (moderate) via `expo`/`@expo/fingerprint` — build-time only.
   - Recommendation: upgrade Expo SDK 57 → 58 in a separate branch and verify (see Manual actions). Not attempted here because the workspace has no git history to roll back a major-version jump.

## Manual dashboard configurations (cannot be set from code — required before launch)

1. **Password policy**: Auth → Policies → set minimum password length to 8 (the app enforces 8; the server default may be 6) and **enable leaked-password protection**.
2. **Email confirmation**: decide ON (recommended for production) or OFF to match current app behavior; if ON, confirm the app's signup flow handles the "check your email" state.
3. **Session handling**: review access-token expiry and refresh-token rotation/reuse-interval settings; consider requiring re-login after long inactivity.
4. **Account recovery**: verify the recovery email template and redirect domains (Site URL + redirect allowlist).
5. **Backups / PITR**: confirm the plan includes daily backups; enable Point-in-Time Recovery if available. Test a restore before launch.
6. **Monitoring & alerting**: enable email/webhook alerts (high error rates, DB CPU, auth failures); consider a third-party uptime check on the deployed URL.
7. **Expo SDK 58 upgrade**: branch, upgrade, run the full E2E flow, then merge (clears the two high advisories).

## Known limitations

- Receipt approval is currently automatic (no human review step); fraud protection relies on fingerprint deduplication, per-offer budgets, and the per-user rate limit.
- Rate limiting is per-user only; IP-based limiting is not possible in a pure database-function design (would need an edge function in front).
- The payout regex fix and rate limit are database-level; changes to those functions should keep the E2E test as a regression gate.

## Test results summary

- E2E journey: **12/12 pass** (J12 verified in a separate probe after the main block).
- Unit tests: **68/68 pass**. Typecheck: clean. Lint: clean. Production build: succeeds.

## Go / No-Go recommendation

**GO**, conditional on completing the 7 manual dashboard items above — most critically the password policy and leaked-password protection, email confirmation decision, and a verified backup restore. The critical financial paths (payouts, reversals, balances, duplicates) and access controls have all been verified working against the live database. The dependency advisories are toolchain-level and acceptable for launch, with the SDK 58 upgrade as the first post-launch follow-up.
