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

- `PaymentProvider` backend switched by `FUTUREROOTS_PAYMENT_BACKEND` (`local` in dev, `stripe` in prod). Keys live in `infra/.env` (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`) → Lambda env; the publishable key is a public Amplify env var (`NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY`).
- Settlement happens **only** via the signature-verified `POST /webhooks/stripe` (webhook endpoint `we_1Ts44zAXijaNn5C5yVSHU2UT` in the Stripe dashboard, events: `payment_intent.succeeded`/`payment_failed`). The local `/confirm` endpoint refuses in stripe mode.
- Key rotation: update `infra/.env`, `cdk deploy`; publishable key via Amplify console + rebuild.
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
   `cdk deploy`. (Connect events do NOT arrive on the existing endpoint.)
4. **Live-mode platform review**: Stripe reviews Connect platforms before live
   Express accounts can onboard — start early, it gates launch.
5. Verify test-mode end to end (test Express account → contribution → net
   ledger entry) before relying on it live.

Legacy note: pre-Connect contributions settled to the platform balance. After
a child's account activates, an operator may move that child's legacy net sum
with a manual `stripe.transfers.create(...)` — record the transfer id in an
admin note; do NOT add a ledger entry (the balance already includes it).

## Secrets

`infra/.env` (gitignored, never committed): `DB_PASSWORD`, `JWT_SECRET`, `SES_FROM_ADDRESS`, `WEB_BASE_URL`. Rotate by editing and redeploying. Hardening TODO (Phase 5+): move to Secrets Manager + rotation.

## Deploy / update

```powershell
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

- Cognito auth swap (needs an egress path for JWKS or a Cognito VPC endpoint)
- Secrets Manager for DB/JWT secrets
- CloudFront in front of API + custom domain + WAF
- RDS deletion protection on once real families are aboard
- GDPR erasure runbook (S3 cascade delete exists in code; document the operational flow)
- Secrets Manager for the Agora App Certificate (`FUTUREROOTS_AGORA_APP_CERTIFICATE`), currently a plaintext Lambda env var like the other secrets
- Media auth hardening (app-wide): the `/media/{id}?token=` route embeds the full access JWT in the URL (proxy/history/Referer leak surface). Move to a short-lived media-scoped token or cookie auth for `<img>/<video>` fetches (security review L2)
- Video-call erasure: the new `family_calls`, `call_participants`, `call_child_presence`, `planned_calls` tables reference children/families/users with no `ON DELETE CASCADE`; the future erasure routine must cascade to all four (esp. `call_child_presence.child_id`)
- Future Fund erasure: `fund_accounts` + `fund_nudges` join the erasure cascade. The routine must also decide the Stripe side (the Express account is the PARENT's; likely deauthorize/leave it) and note that `contributions`/`fund_ledger_entries` are financial records retained under a legal-obligation basis — anonymize the child linkage rather than delete money records (GDPR Art. 17(3)(b)). Counsel items: money-transmission posture (processor exemption as merchant of record), legacy platform-held balances disposition/escheatment, "earmarked for the child" copy vs. no legal custody (any UTMA/529 product is lawyer-first), retention period for money records post-erasure
- Contribution settle: emails are sent inside `settle_contribution` before commit, so two concurrent `payment_intent.succeeded` deliveries can double-send the celebration email (ledger stays single via the unique constraint). Move sends after commit
- Fund nudge throttle is check-then-insert (no unique constraint): a concurrent double-tap can double-send the nudge email. Nuisance-level
- Video-call retention sweep: `call_participants` rows persist after a call ends (adult "who was on, when" history); add a retention/cleanup policy, and an elapsed-time cap so an abandoned (never-polled) call ends without waiting for the next family-page visit
