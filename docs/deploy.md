# FutureRoots — AWS Deployment (Phase 5)

Region: **us-east-1** · Account: the one configured in `aws configure` · IaC: CDK (`infra/`)

## Architecture deployed

- **VPC** — 2 AZs: public (NAT), private-with-egress (Lambda), isolated (RDS). Egress via a **fck-nat t4g.nano instance** (~$3/mo vs $32 managed NAT) so Lambda reaches Stripe/SES/AI APIs; S3 keeps the free gateway endpoint so media bypasses the NAT.
- **RDS PostgreSQL 16** `db.t4g.micro`, 20 GB gp3, single-AZ, 7-day backups. **No public endpoint** — only the API Lambda's security group can reach port 5432.
- **Lambda** (`python3.13`, 512 MB) running FastAPI via Mangum, deployed from `apps/api/build/lambda.zip`, inside the VPC.
- **HTTP API Gateway** fronting the Lambda.
- **S3 media bucket** — private, SSE, presigned PUT/GET (media bytes never transit Lambda).
- **SES** — email in sandbox mode initially (sender and recipients must be verified identities).
- **Web** — AWS Amplify Hosting building `apps/web` from GitHub on push.

Estimated baseline: ~$18–21/month (RDS ~$15, fck-nat ~$3.3, rest pennies at MVP traffic).

## Payments (Stripe, live mode)

- `PaymentProvider` backend switched by `FUTUREROOTS_PAYMENT_BACKEND` (`local` in dev, `stripe` in prod). Secret keys live in the `futureroots/api` Secrets Manager secret (see **Secrets** below; values still sourced from `infra/.env` via `push_secrets.ps1`); the publishable key is a public Amplify env var (`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`).
- Settlement happens **only** via the signature-verified `POST /webhooks/stripe` (webhook endpoint `we_1Ts44zAXijaNn5C5yVSHU2UT` in the Stripe dashboard, events: `payment_intent.succeeded`/`payment_failed`). The local `/confirm` endpoint refuses in stripe mode.
- Key rotation: update `infra/.env`, run `infra\scripts\push_secrets.ps1`, force new cold starts (`cdk deploy`); publishable key via Amplify console + rebuild.
- Refunds: Stripe dashboard → refund the payment; then add a compensating `adjustment` ledger entry (there is no automated refund webhook handling yet — see hardening backlog).

### Future Fund accounts (Stripe Connect) — one-time dashboard setup

Real per-child accounts route contributions as destination charges (application
fee = card-cost pass-through; platform holds no child balances). Before live
onboarding works, the owner must, in the Stripe Dashboard:

1. **Enable Connect** and complete the **platform profile** (accept the
   loss/negative-balance liability terms destination charges require).
2. **Connect branding** (Settings → Connect): name "FutureRoots", icon, brand
   color — this is what themes the hosted Express onboarding.
3. **Create a second webhook endpoint** at
   `https://api.futureroots.app/webhooks/stripe-connect` with **"Listen to
   events on Connected accounts"** enabled, event `account.updated`. Put its
   signing secret in `infra/.env` as `STRIPE_CONNECT_WEBHOOK_SECRET`, then
   run `infra\scripts\push_secrets.ps1` and `cdk deploy`. (Connect events do
   NOT arrive on the existing endpoint.)
4. **Live-mode platform review**: Stripe reviews Connect platforms before live
   Express accounts can onboard — start early, it gates launch.
5. Verify test-mode end to end (test Express account → contribution → net
   ledger entry) before relying on it live.

Legacy note: pre-Connect contributions settled to the platform balance. After
a child's account activates, an operator may move that child's legacy net sum
with a manual `stripe.transfers.create(...)` — record the transfer id in an
admin note; do NOT add a ledger entry (the balance already includes it).

### Premium rollout (one-time dashboard setup, test + live mode)

Backend is deployed dark: with empty price ids, Premium checkout 503s and
every family stays Free. To light it up:

1. **Products/Prices**: product "FutureRoots Premium" → recurring Prices
   $9.99/month and $99/year (USD); product "FutureRoots Premium — one-year
   gift" → one-time Price $99. Put the three price ids in `infra/.env` as
   `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_ANNUAL`, `STRIPE_PRICE_GIFT_YEAR`,
   then `cdk deploy` (they flow to `FUTUREROOTS_STRIPE_PRICE_*`; same names in
   `apps/api/.env` for local stripe-mode testing).
2. **Webhook events**: on the EXISTING `/webhooks/stripe` endpoint (same
   signing secret — no new endpoint), add `checkout.session.completed`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `invoice.paid`, `invoice.payment_failed`, `invoice.upcoming`.
3. **Billing → Revenue recovery**: Smart Retries ON; after the final retry,
   **cancel the subscription**. Turn OFF Stripe's own customer emails (failed
   payment, upcoming renewal) — FutureRoots sends brand-voice equivalents.
4. **Billing Portal configuration**: payment-method update + invoice history
   ON; cancellation and plan switching OFF (both are app-controlled).
5. **⛔ LAUNCH-BLOCKING — renewal reminder lead time (CA Automatic Renewal
   Law).** The annual renewal reminder fires from Stripe's `invoice.upcoming`
   event, and its lead time is a Stripe Billing setting (Settings → Billing →
   Subscriptions and emails → "upcoming renewal" / upcoming-invoice webhook
   lead time), **default ~7 days**. California's ARL requires the pre-renewal
   notice for an annual auto-renewing plan to land **15–45 days** before the
   charge. Set the `invoice.upcoming` lead time to **30 days** (comfortably
   inside the window) BEFORE enabling live-mode annual subscriptions. This is
   a config-only control — the app never hardcodes the timing (it just emails
   whenever the event arrives), so this dashboard setting is the only lever.
   Do not announce Premium until it is set.
6. Verify test mode end to end with the Stripe CLI
   (`stripe listen --forward-to localhost:8000/webhooks/stripe`): subscribe →
   `premium_activated` feed event; gift → grant; cancel/resume; then a real
   $9.99 live checkout + cancel before announcing.

SES production access remains the dependency for Premium lifecycle emails at
scale (sandbox only delivers to verified addresses).

**Premium data lifecycle** — handled by the daily maintenance command (below):
gift-intent prune (>30 days; the admin endpoint
`POST /admin/premium/prune-gift-intents` remains as a manual trigger) and
`premium_email_log` prune (>1 year; safe because no lifecycle email can
re-fire after 30 days).

## Web Push (VAPID)

Backend is deployed dark by default: with no VAPID keys configured,
`POST /me/push-subscriptions` 503s, the dispatcher (`app/services/notify.py`)
sends no push, and the web settings page hides the push-enrollment card —
the bell, the inbox, and the (now pref-gated) absorbed emails all keep
working regardless. To light it up:

1. **Generate the keypair** (from `apps/api`; prints both halves as
   unpadded base64url strings — the raw format `pywebpush` and the browser's
   `PushManager.subscribe({ applicationServerKey })` expect, not PEM):

   ```powershell
   uv run python -c "from py_vapid import Vapid02; from py_vapid.utils import b64urlencode; from cryptography.hazmat.primitives import serialization; v = Vapid02(); v.generate_keys(); priv = v.private_key.private_numbers().private_value.to_bytes(32, 'big'); pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint); print('VAPID_PRIVATE_KEY=' + b64urlencode(priv)); print('VAPID_PUBLIC_KEY=' + b64urlencode(pub))"
   ```

2. **Private half is a secret**: paste the `VAPID_PRIVATE_KEY` value into
   `infra/.env` → `infra\scripts\push_secrets.ps1` reads it into
   `FUTUREROOTS_VAPID_PRIVATE_KEY` inside the `futureroots/api` Secrets
   Manager secret (already wired — no script change needed).
3. **Public half + subject are plain env, not secrets.** Set
   `VAPID_PUBLIC_KEY` (and, if you want something other than the default,
   `VAPID_SUBJECT` — a `mailto:` contact address the push services may use to
   reach the platform) before `cdk deploy`; `infra/lib/futureroots-stack.ts`
   passes them straight through as `FUTUREROOTS_VAPID_PUBLIC_KEY` /
   `FUTUREROOTS_VAPID_SUBJECT` Lambda env vars. The public key is served to
   browsers live via `GET /me/notifications` (`push_public_key`), so it never
   needs an Amplify env var or a web rebuild.
4. **Deploy**:

   ```powershell
   # from infra/
   powershell -File scripts\push_secrets.ps1
   npx cdk deploy --require-approval never

   # run the new migration (adds push_subscriptions, notifications, and
   # 16 new notification_preferences columns) — revision b8f2c1a9d4e7
   aws lambda invoke --function-name <ApiFunctionName> `
     --payload '{\"futureroots_command\":\"migrate\"}' `
     --cli-binary-format raw-in-base64-out out.json
   ```

5. **Verify**: reload `/settings` and confirm the push-enrollment card
   appears, subscribe, then trigger any notify()-worthy event (e.g. seal a
   time capsule) and confirm an OS-level push arrives alongside the bell
   badge and email, each honoring their toggle.

**Lambda bundle size.** `pywebpush` + `cryptography` add roughly 8 MB to the
zip — still well inside Lambda's 250 MB unzipped limit. `http-ece` (a
pywebpush dependency) ships sdist-only, so `apps/api/scripts/package_lambda.ps1`
builds it from source (`--no-binary http-ece`) while every other dependency
stays wheel-only, so nothing else is compiled cross-platform when targeting
manylinux from Windows.

**Security callout — SSRF allowlist.** The push dispatcher POSTs to whatever
`endpoint` URL a subscription stores, from inside the VPC-egress Lambda.
`apps/api/app/push_targets.py` restricts accepted endpoints to the known Web
Push provider origins (`googleapis.com`, `push.services.mozilla.com`,
`notify.windows.com`, `push.apple.com`) and rejects IP-literal hosts
outright, so a maliciously registered endpoint can never turn push fan-out
into an SSRF primitive reaching internal hosts or the instance metadata
service.

## Secrets (AWS Secrets Manager)

Runtime secrets no longer live in Lambda env vars — or in the CFN template.
Two secrets:

1. **`futureroots/api`** (us-east-1, ~$0.40/mo) — app-level secrets as a JSON
   object keyed by env-var name: `FUTUREROOTS_JWT_SECRET`,
   `FUTUREROOTS_STRIPE_SECRET_KEY`, `FUTUREROOTS_STRIPE_WEBHOOK_SECRET`,
   `FUTUREROOTS_STRIPE_CONNECT_WEBHOOK_SECRET`,
   `FUTUREROOTS_AGORA_APP_CERTIFICATE`, `FUTUREROOTS_VAPID_PRIVATE_KEY`,
   `FUTUREROOTS_TESTNET_ADMIN_TOKEN`,
   `FUTUREROOTS_X_CLIENT_SECRET`. (The old `FUTUREROOTS_DATABASE_URL` /
   `FUTUREROOTS_TESTNET_DATABASE_URL` keys are retired — DB credentials moved
   to the RDS-managed secret below; a stale copy left in the blob is ignored.)
2. **The RDS-managed master-user secret** (name pattern **`rds!db-...`**,
   created and owned by RDS itself via `manageMasterUserPassword` in the CDK
   stack) — JSON with `username` + `password` only. The password never exists
   in `infra/.env`, the CFN template, or the app secret.

Note: `.ps1` scripts in this repo must stay pure ASCII (PowerShell 5.1 parses
BOM-less UTF-8 as ANSI; curly quotes from mojibake silently corrupt parsing).

- **Source of values**: app secrets still come from `infra/.env` (gitignored);
  push with `infra\scripts\push_secrets.ps1` (idempotent; never prints
  values; no longer needs `DB_PASSWORD` or the `DbEndpoint` output). The DB
  password is generated by RDS — nobody types it, nothing composes it.
- **How they load**: the CDK stack grants both Lambdas read on both secrets
  and passes `FUTUREROOTS_SECRETS_ARN` (app secret),
  `FUTUREROOTS_DB_SECRET_ARN` (RDS-managed secret) and `FUTUREROOTS_DB_HOST`
  (endpoint hostname — not a secret). At cold start `apps/api/app/config.py`
  composes `FUTUREROOTS_DATABASE_URL` from the DB secret + host (database
  `futureroots_testnet` when `FUTUREROOTS_TESTNET_MODE=1`, else
  `futureroots`; password percent-encoded), then overlays the app-secret JSON
  as env-var *defaults* — both fetched over the fck-nat egress path, no VPC
  endpoint. Explicitly set env vars always win, and local dev (no ARNs) is
  untouched.
- **DB password rotation**: rotate on demand
  (`aws secretsmanager rotate-secret --secret-id 'rds!db-...'`) or enable
  automatic rotation on the RDS console/secret — RDS owns the rotation, no
  Lambda function to manage. The app is rotation-resilient: established
  connections survive, and `app/db.py` injects credentials from a cached
  accessor (5-min TTL) into every NEW pooled connection, force-refreshing the
  secret and retrying once on an auth failure. **No forced cold starts needed
  for DB rotation.**
- **App-secret rotation** (JWT/Stripe/Agora): edit `infra/.env` → run
  `push_secrets.ps1` → force new cold starts (`cdk deploy`, or
  `aws lambda update-function-configuration` with a touched description).
  These values are read once per cold start, so warm containers keep old
  values until recycled.
- **Not in any secret**: Stripe price ids, backends, SES from-address,
  `WEB_BASE_URL`, Agora App ID (all non-secret, still plain env vars), and
  `X_CLIENT_ID` (public). `DB_PASSWORD` in `infra/.env` is obsolete — delete
  the line once the migration deploy has succeeded (it is read by nothing).

## Scheduled maintenance

An EventBridge rule (`cron(0 9 * * ? *)`, daily 09:00 UTC) invokes the API
Lambda with `{"futureroots_command": "maintenance"}` — an idempotent
data-lifecycle sweep (one DB session, one commit, a one-line count summary in
CloudWatch; handler in `apps/api/app/lambda_handler.py` /
`app/services/maintenance.py`). It runs: `premium_gift_intents` prune
(>30 days), `premium_email_log` prune (>1 year), `fund_nudges` sweep
(>30 days), abandoned-video-call end (active call with no heartbeat for
15 min), and `call_participants`/`call_child_presence` retention (rows of
calls ended >90 days ago). It never touches money records. Manual trigger:

```powershell
aws lambda invoke --function-name <ApiFunctionName> `
  --payload '{\"futureroots_command\":\"maintenance\"}' `
  --cli-binary-format raw-in-base64-out out.json
```

## RDS protection

The database has `deletionProtection: true` and removal policy `RETAIN`: it
survives both an accidental delete-instance call and a stack teardown. To
ever decommission it, first flip both in `infra/lib/futureroots-stack.ts`
and deploy.

## Media auth

`GET /media/{id}` never accepts a session JWT in the URL. Browsers load media
through `?token=<media token>` — a signed, stateless JWT
(`aud: futureroots:media`, 60-min TTL, `FUTUREROOTS_MEDIA_TOKEN_TTL_MINUTES`)
minted by `POST /auth/media-token` for any authenticated user. The token is a
narrow read credential: it authenticates the user on the media route only
(every other endpoint rejects it as a bearer token, and the media route
rejects access JWTs in the query string), and the route still runs full
per-media authorization (family membership, supporter sharing, sealed-capsule
creator-only) on every fetch, so it grants nothing its owner couldn't already
view. API clients may use a normal `Authorization: Bearer <access JWT>` header
instead. The web client caches the token in localStorage and refreshes it
opportunistically on API traffic (background refresh under 15 min remaining),
clearing it on any identity change. Query-string credentials remain a
Referer/history/proxy-log leak surface (plain `<img>/<video>` tags can't send
headers); the exposure is now capped at ≤1 h of read-only media access instead
of a week-long full session token.

## Deploy / update

```powershell
# 0. If infra/.env changed: push secrets first (from infra/)
powershell -File scripts\push_secrets.ps1

# 1. Package the API for Lambda (from apps/api)
powershell -ExecutionPolicy Bypass -File scripts\package_lambda.ps1

# 2. Deploy (from infra/)
npx cdk deploy --require-approval never

# 3. Run migrations inside the VPC (function name from stack output ApiFunctionName)
aws lambda invoke --function-name <ApiFunctionName> `
  --payload '{\"futureroots_command\":\"migrate\"}' `
  --cli-binary-format raw-in-base64-out out.json
```

Stack outputs: `ApiUrl`, `MediaBucketName`, `DbEndpoint`, `ApiFunctionName`.

## SES sandbox

While sandboxed, both the FROM address and every recipient must be verified:

```powershell
aws sesv2 create-email-identity --email-identity someone@example.com --region us-east-1
```

Request production access (SES console → Account dashboard) before inviting real families.

## Custom domain (futureroots.app)

- Domain registered at **Cloudflare** (Registrar) — nameservers must stay Cloudflare's, so DNS records live in the Cloudflare dashboard, all **DNS only** (grey cloud — proxying breaks ACM validation and double-proxies Amplify's CDN).
- Web: Amplify domain association for apex + www (`@` and `www` CNAME → the Amplify CloudFront host; ACM cert auto-managed by Amplify).
- API: ACM cert for `api.futureroots.app` + API Gateway custom domain + mapping to the HTTP API; `api` CNAME → the API GW regional target (`d-1oabzuff0d.execute-api.us-east-1.amazonaws.com`).
- URLs: `https://futureroots.app` (web) · `https://api.futureroots.app` (API). `WEB_BASE_URL`/`EXTRA_ORIGINS` in `infra/.env` and `NEXT_PUBLIC_API_URL` in Amplify env vars must stay in sync with these.

## Web (Amplify Hosting)

Amplify app builds `apps/web` from the GitHub repo (monorepo root `apps/web`). After the first deploy, set `WEB_BASE_URL` in `infra/.env` to the Amplify URL and redeploy the stack so API CORS and email links point at it. Set `NEXT_PUBLIC_API_URL` env var in Amplify to the `ApiUrl` output.

## Post-deploy smoke test

`scripts/smoke_test.sh <ApiUrl>` (Git Bash) runs signup → family → child → invite → milestone → contribution against the deployed API.

## Hardening backlog (tracked for post-MVP)

Open:

- Cognito auth swap (needs an egress path for JWKS or a Cognito VPC endpoint) — **deferred by founder decision 2026-07-16** (multi-day effort)
- CloudFront in front of API + custom domain + WAF — **deferred by founder decision 2026-07-16** (adds ~$10–15/mo)
- Account-deletion / erasure endpoints: the manual operational flow is now
  documented in `docs/erasure-runbook.md`; its §7 "automation backlog" is the
  spec for the eventual self-serve endpoints (table walks, tombstone-vs-delete
  for `users`, media walk on `MediaStorage.delete()`, Stripe
  Customer/Connect handling, `consent_records.revoked_at` writes). Counsel
  items (money-transmission posture, legacy balance escheatment, retention
  period for money records) are flagged inline there
- EU/UK withdrawal-right consent line on checkout is live (immediate-performance
  acknowledgment, unchecked by default) — **pending counsel review**

Resolved (2026-07-16):

- ~~Secrets-Manager-managed RDS master credential~~ → the instance now uses
  `manageMasterUserPassword` (RDS generates/rotates the password in its own
  `rds!db-...` secret; `MasterUserPassword` is gone from the CFN template and
  `DB_PASSWORD` from `infra/.env`; the app composes the DB URL from the secret
  and re-fetches on auth failure — see **Secrets** above)
- ~~Secrets Manager for DB/JWT/Stripe/Agora secrets~~ → the `futureroots/api`
  consolidated secret (see **Secrets** above)
- ~~RDS deletion protection~~ → on, with removal policy RETAIN
- ~~GDPR erasure runbook~~ → `docs/erasure-runbook.md` (note: the old claim
  "S3 cascade delete exists in code" was an overstatement — the
  `MediaStorage.delete()` primitive exists; the erasure walk does not yet)
- ~~Contribution settle email double-send race~~ → emails send only after the
  ledger commit; a concurrent duplicate delivery loses the unique constraint,
  acks, and emails nobody
- ~~Fund nudge throttle race~~ → one row per (member, child) under a unique
  constraint (migration `d41f7b6a90c3`); re-nudges refresh in place
- ~~Video-call retention sweep + abandoned-call cap~~ → 90-day
  participant/presence retention in the maintenance command; abandoned calls
  (no heartbeat 15 min) ended at read time and by the daily sweep
- ~~Gift-intent prune scheduling / email-log retention~~ → daily maintenance
  command (see **Scheduled maintenance** above)
- ~~Owner-departure billing gap~~ → leave-family / remove-member endpoints now
  exist and call `handle_owner_departure` (subscription set to
  cancel-at-period-end, remaining parents emailed)
- ~~Media auth hardening (JWT in media URLs)~~ → short-lived media-scoped
  tokens (see **Media auth** above)
