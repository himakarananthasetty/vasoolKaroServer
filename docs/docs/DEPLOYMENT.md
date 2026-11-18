# Deployment and configuration

This guide covers what the project owner must configure outside the code. The code, migrations, and edge functions are already in the repository and deployed.

## 1. Database

All schema changes live in `supabase/migrations/`, applied in filename order. A fresh database built by replaying those files matches the live project.

Migrations applied to the live database:
- `20261112043223_harden_notifications_access_and_insert_trigger.sql`: notification access rules and the receipt trigger.
- `20261112045054_add_push_subscriptions_and_dispatch.sql`: push subscriptions, `notifications.pushed_at`, `register_push_subscription`, and the dispatch trigger. Enables the `pg_net` HTTP extension.

## 2. Edge functions

- `delete-account`: JWT verification on.
- `send-push`: JWT verification off. It accepts only requests whose bearer token equals the service role key, so the database can call it.

## 3. Push keys (owner action)

Generate a VAPID key pair once, on any machine with Node installed:

```
npx web-push generate-vapid-keys
```

Then configure these values:

| Where | Name | Value |
| --- | --- | --- |
| Web build environment | `EXPO_PUBLIC_VAPID_PUBLIC_KEY` | The public key |
| Edge function secrets (`send-push`) | `VAPID_PUBLIC_KEY` | The same public key |
| Edge function secrets (`send-push`) | `VAPID_PRIVATE_KEY` | The private key |
| Edge function secrets (`send-push`) | `VAPID_SUBJECT` | A contact address, for example `mailto:you@example.com` |

Keep the private key secret. Do not commit it or place it in client code.

Until these are set, `send-push` returns a configuration error and no alerts are sent. The app still works; the "Alerts on this device" card simply does not appear because the browser has no public key to subscribe with.

## 4. Dispatch secrets in the database vault (owner action)

The database calls `send-push` using two vault entries. Run these in the SQL editor, replacing the placeholders with your project values:

```sql
SELECT vault.create_secret('https://<project-ref>.supabase.co/functions/v1/send-push', 'push_dispatch_url');
SELECT vault.create_secret('<service-role-key>', 'push_dispatch_service_key');
```

Until both entries exist, the dispatch trigger does nothing. Existing alerts are never pushed retroactively.

## 5. Verification after configuration

1. Open the notifications screen in a browser and turn on alerts. The browser asks for permission, and the card changes to "Alerts are on for this browser."
2. Confirm a row appears in `push_subscriptions` for your user.
3. Trigger a receipt approval or rejection for that user. A notification row is created and `pushed_at` is set on it within a few seconds.
4. Confirm the browser shows the alert, including when the app tab is closed.

If step 3 does not set `pushed_at`, check that both vault entries exist and that the function secrets from section 3 are set.

## 6. Web build

Set `EXPO_PUBLIC_VAPID_PUBLIC_KEY` in the environment used for the production web build, then rebuild. Push requires HTTPS hosting; browsers do not offer push on plain HTTP except on localhost.

## 7. Rotating keys

- Service role key rotation: update the `push_dispatch_service_key` vault entry and the project's secret for `send-push` if it uses that key.
- VAPID key rotation: existing browser subscriptions become invalid. Users must turn alerts off and on again.
