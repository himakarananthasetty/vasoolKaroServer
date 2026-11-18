# Security model

This document describes how Vassolkaro protects shopper and retailer data, what was checked in the latest review, and what is still open.

## Trust boundaries

- **The browser is untrusted.** Anyone can call the Supabase API directly with the public anon key. Every access rule therefore lives in the database, not in the screens.
- **The anon key is public by design.** It identifies the project; it does not grant access. Row-level security and column grants decide what it can reach.
- **Service role key and database URL are server-only.** They are never referenced by app code and never prefixed with `EXPO_PUBLIC_`, so they are not bundled.

## Database controls

### Row-level security
- RLS is enabled on every application table: `profiles`, `offers`, `receipts`, `referral_bonuses`, `saved_offers`, `todos`, `notifications`, `payouts`, and `push_subscriptions`.
- Shopper data is owner-scoped: `auth.uid() = user_id`.
- Shoppers can read only active offers. Retailers can read and write only offers where `owner_id = auth.uid()`.
- Policies are written per operation (select, insert, update, delete) and scoped to `authenticated`.

### Column-level grants
- Table-wide write grants were removed. Clients can write only the columns they need:
  - `offers` insert: the listed retailer fields only. Update: title, description, budget, end date, active flag, and store address.
  - `profiles` update: full name, phone number, date of birth (only while empty), address, preference flags, and updated timestamp. Email, referral fields, account type, admin level, and deactivation time are not writable.
  - `support_requests`: insert `topic` and `message` only. Owner comes from the session.
  - Account deactivation and reactivation go through `deactivate_my_account` and `reactivate_my_account`, which take the caller from `auth.uid()`.
  - `receipts` and `referral_bonuses`: read only. Claims are created through `submit_receipt`.
  - `saved_offers`: insert and delete for the owner.
  - `todos`: insert and update limited to title, due date, and completed; `user_id` is set from the session and cannot be supplied by the client.
- Anonymous users have no grants on application tables.

### Profile guard trigger
- `guard_profile_changes` runs before every insert and update on `profiles`, including writes from the service role. It rejects any change to `email`, any change to a date of birth that is already set, and any date of birth that makes the person younger than 13.
- The trigger function has no EXECUTE grant for `PUBLIC`, `anon`, or `authenticated`.

### Privileged functions
- `submit_receipt`, `redeem_referral_code`, `my_offer_claim_stats`, `request_payout`, and the `admin_*` payout functions are `SECURITY DEFINER` with `SET search_path = public`. The admin functions also check `profiles.admin_level` in their body.
- `reverse_receipt_credit` is granted to `service_role` only. Shoppers and admins cannot reverse a credit from the client.
- Wallet money movements are never edited. Reversals are new negative ledger rows, and payouts are links to ledger rows, so every cent has an audit trail.
- Payout requests and balance reads run inside the database. The client cannot choose which ledger rows to pay out.
- Each function derives the caller from `auth.uid()` and checks ownership in its body. Parameters are never trusted as identity.
- EXECUTE is revoked from `PUBLIC` and `anon`, then granted to `authenticated`. This applies to `deactivate_my_account` and `reactivate_my_account` too.
- `delete-account` is an edge function with JWT verification on. It identifies the caller from the token, uses the service role only inside the function, and returns a fixed reason code for blocked deletions.
- `submit_receipt` validates every input (lengths, date not in the future, card digits, total bounds), locks the offer row, and reserves budget atomically. Business-rule failures are stored as rejected claims with a readable reason.
- Clients never receive raw database error text. Screens show fixed messages, and the function returns `delete_failed` on unexpected errors. Details go to the server log.
- Retailer sign-up role is set only in the sign-up trigger from account metadata. A client cannot promote itself later because `profiles.account_type` is not writable.

### Retailer protections
- Retailers cannot delete offers. Pausing sets `active = false`.
- Economic terms of an offer that already has claims (cashback, merchant name, per-user limit) cannot be changed.
- Budget cannot be lowered below the amount already reserved or spent (enforced by a table constraint, shown to the user as a friendly message).
- Claim statistics expose counts and totals only, never shopper identities.

## Client controls

- No secrets are in source. The only configuration is the two `EXPO_PUBLIC_` values.
- Auth errors are mapped to fixed messages. Unknown errors show a generic message; the raw detail is logged to the console only.
- Sign-up does not reveal whether an email is registered in the screen flow beyond a neutral "sign in instead" hint (see open items).
- Offer save errors show a generic message; the raw database error is not rendered.
- Maps links are built with `encodeURIComponent` and open only fixed Google Maps or Apple Maps URLs.
- Receipt images are read locally in the browser and are never uploaded, so there is no file storage surface.
- Text from retailers (merchant names, addresses, titles) is rendered as plain text, not as HTML.

## Review results

Checked in this review:

| Area | Result |
| --- | --- |
| Database advisor (security) | Fourteen WARN findings for signed-in `SECURITY DEFINER` functions. Intentional: every one checks `auth.uid()` in its body, and the admin functions also check `profiles.admin_level`. Clients cannot change `admin_level`. |
| Notifications access | Anon has no access. Shoppers can only select their own rows and set `read_at`. Alerts are created only by the receipt trigger. |
| Table and column grants | Over-broad grants removed in the latest migration. |
| Client secrets | None found. Only public values are read from `EXPO_PUBLIC_` variables. |
| Raw error text in the UI | One path found in the offer save hook and fixed. Auth fallback fixed. |
| Sign-in and sign-up errors | Fallback changed from raw text to a generic message. |
| Console logging | Only error details go to the console, never passwords or tokens. |
| Git ignore | `.env*`, `node_modules/`, and `dist/` are ignored. |
| Open redirects and HTML injection | None found in the app's own code. |

## Fixed in this pass

- The offer save hook no longer shows raw database error text. It maps the budget rule to a friendly message and falls back to a generic one.
- Auth errors show a generic message for anything unexpected instead of raw server text.
- Minimum password length raised from 6 to 8 characters in the sign-up form.
- The duplicate-account message no longer tells the user the email is registered; it says the account could not be created and suggests signing in if they already have one.
- Tesseract is loaded only when a shopper scans a receipt.
- Notifications: removed anon access, insert and delete rights, and full-row update rights. Only `read_at` is writable.
- Receipt notification trigger also fires when a receipt is inserted already approved or rejected.

## Open items

These are known and deliberately not changed in this pass.

1. **Supabase dashboard settings.** Minimum password length on the server and leaked-password protection are project settings. Confirm they match the app.
2. **Account existence on sign-up.** The sign-up response still reveals whether an email is taken through Supabase's error. The screen message is neutral, but the platform response is not fully hidden. Fully hiding it needs a server-side flow with email confirmation, which is out of scope.
3. **Receipt duplicate hint.** The "already submitted" message is shared across shoppers, so it could confirm that a specific receipt was submitted by someone else if the number, date, total and store are already known. Low impact; a per-user duplicate message would remove it.
4. **Production dependency advisories.** `npm audit --omit=dev` reports 22 advisories (1 critical, 10 high) in transitive packages such as `ws`, `yaml`, and `zod`. Most come from the Expo toolchain. Run `npm audit fix` in a branch and test the build before merging; `--force` can introduce breaking upgrades.
5. **Anon key and project URL.** Confirm the anon key and the project URL in `.env` belong to the same Supabase project.
6. **Advisor warnings (accepted).** The fourteen `SECURITY DEFINER` WARN findings are accepted. Each function is callable by signed-in users by design, checks `auth.uid()` in its body, and the admin functions also require `profiles.admin_level`. Clients cannot write `admin_level`, and only the operator sets it. Revoking EXECUTE from `authenticated` would break the app's own screens.
7. **Admin tiers (verified).** `admin_customer_summary` and the per-customer admin functions are `super_admin` only, as stated in the admin migration. `admin` level can view spending overview and payouts. `tests/database/notifications_isolation.sql` confirms both tiers.
8. **Migration files (resolved).** Every applied migration, including the notifications hardening and push migrations, is saved in `supabase/migrations/`. The file list matches the database migration history.
9. **Push delivery (pending owner configuration).** The code path is complete, but alerts are not sent until the owner sets the VAPID keys and the dispatch secrets described in `docs/DEPLOYMENT.md`. Until then the database trigger does nothing.

## Push delivery

- `push_subscriptions` has RLS on. Signed-in users can select and delete only their own rows. Direct insert and update are revoked from every client role; rows are created only by `register_push_subscription`, which requires a signed-in caller, an HTTPS endpoint of at most 2048 characters, and keys of at most 256 characters each. It always stores the caller's own id.
- `anon` has no access to `push_subscriptions` and no EXECUTE on `register_push_subscription` or `dispatch_notification_push`.
- `send-push` is deployed with JWT verification off so the database can call it without a user session. It rejects every request unless the bearer token equals the service role key, so it is not an open relay. It returns 503 when the VAPID settings are missing and never echoes provider responses.
- The service role key is stored only in the database vault (`push_dispatch_service_key`), never in client code or the repo. The VAPID private key lives only in the function's secrets.
- Expired or unsubscribed endpoints (HTTP 404 or 410 from the push service) are deleted automatically.
- Payloads contain the alert title, a one-line body that names the merchant (for example "Your receipt from X was approved"), and a relative link. The cashback amount and other receipt details are not included in the push body.
- The database HTTP extension (`pg_net`) is the only outbound path from the database. The dispatch URL is read from the vault and is not user-editable.
- Accepted risk: a stolen service role key would allow sending push messages to any subscriber. Rotate the key in the project settings and update the vault entry if that happens.

## Reporting a vulnerability

Email the project owner with steps to reproduce. Do not open a public issue for security problems.
