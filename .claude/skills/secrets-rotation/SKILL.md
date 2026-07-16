---
name: secrets-rotation
description: Coaching runbook for rotating every FutureRoots secret — Stripe keys, webhook signing secrets, JWT, Agora certificate, the RDS-managed DB password, and testnet/X secrets. Use when the user wants to rotate one or all secrets (scheduled hygiene, suspected exposure, offboarding), or asks "how do I rotate X". Walks the operator through dashboard steps they must do themselves, runs the push/cold-start/verify steps that can be automated, and enforces the ordering and grace-window rules that make rotation zero-downtime.
---

# FutureRoots — Secrets Rotation

You are coaching the operator through a rotation. Some steps happen in third-party dashboards **only they can access** (Stripe, Agora) — for those, tell them exactly what to click and wait for their confirmation. Steps involving `infra/.env`, `push_secrets.ps1`, AWS CLI, and verification you can run yourself (with their permission).

## The secret inventory

| Secret | Lives in | Rotated at | User impact of rotation |
|---|---|---|---|
| `STRIPE_SECRET_KEY` | `futureroots/api` SM secret | Stripe Dashboard (roll key) | None (grace window) |
| `STRIPE_WEBHOOK_SECRET` | `futureroots/api` | Stripe Dashboard (roll endpoint secret) | None if done inside window |
| `STRIPE_CONNECT_WEBHOOK_SECRET` | `futureroots/api` | Stripe Dashboard (Connect endpoint) | None if done inside window |
| `JWT_SECRET` | `futureroots/api` | generated locally | **Everyone logged out** (hard cut) |
| `AGORA_SECRET` (app certificate) | `futureroots/api` | Agora Console | Brief video-call join impact |
| DB master password | **RDS-managed secret** (`rds!db-...`) | Secrets Manager RotateSecret | **None** (app self-heals) |
| `TESTNET_ADMIN_TOKEN`, `X_CLIENT_SECRET` | `futureroots/api` | generated locally / X dev portal | Testnet only |
| `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` | Amplify env (public, not a secret) | rolls together with the secret key pair | Web rebuild needed |

Not secrets (no rotation): Stripe price IDs, Agora App ID, SES from-address, `X_CLIENT_ID`, `WEB_BASE_URL`.

## The universal flow (all `futureroots/api` keys)

Every app-level secret rotates with the same three moves, **in this order**:

```powershell
# 1. Operator edits the value in infra\.env (gitignored)

# 2. Push to Secrets Manager (from infra/)
powershell -ExecutionPolicy Bypass -File scripts\push_secrets.ps1

# 3. Force cold starts on BOTH Lambdas (values load once per cold start)
$stamp = Get-Date -Format o
aws lambda update-function-configuration --function-name FutureRoots-ApiFnE0725F78-CVhDBf56iARR --description "rotate $stamp" --region us-east-1
aws lambda wait function-updated --function-name FutureRoots-ApiFnE0725F78-CVhDBf56iARR --region us-east-1
aws lambda update-function-configuration --function-name FutureRoots-TestnetApiFn046590C9-3ZhunkrcO4fl --description "rotate $stamp" --region us-east-1
aws lambda wait function-updated --function-name FutureRoots-TestnetApiFn046590C9-3ZhunkrcO4fl --region us-east-1
```

Rules you must enforce:
- **Push before cold starts**, never the other way around.
- `push_secrets.ps1` pushes ALL keys from `.env` at once (idempotent) — safe even when rotating a single value.
- **Never edit `push_secrets.ps1` with non-ASCII characters** (PowerShell 5.1 parses BOM-less UTF-8 as ANSI; mojibake curly-quotes silently corrupt parsing — this has caused a real outage-adjacent bug).
- An explicitly set Lambda env var overrides the secret (that's the emergency rollback lever, not a normal path).

## Per-secret coaching

### 1. Stripe secret key (do first when rotating everything — highest value, zero impact)
1. Ask the operator to open **Stripe Dashboard (live mode) → Developers → API keys → Roll key** on the secret key, choosing a **12-hour expiry** for the old key. Both keys work during the window.
2. They paste the new `sk_live_...` into `infra/.env` as `STRIPE_SECRET_KEY`.
3. Run the universal flow.
4. Verify inside the window: exercise any Stripe-touching path (a family's Plan section triggers status reads) and check CloudWatch for `AuthenticationError`. Also confirm livemode consistency — the gift webhook cross-checks `event.livemode` against the key prefix, so a `sk_test_` pasted by mistake breaks gift settlement.
5. Remind them: the **publishable key** (`pk_live_...`) only changes if they roll the *pair*; if it changed, update `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` in the Amplify console and trigger a web rebuild.

### 2. Stripe webhook signing secrets (one endpoint at a time)
1. Dashboard → Developers → Webhooks → the `https://api.futureroots.app/webhooks/stripe` endpoint → **Roll secret** with a delay window (up to 24 h; old + new both verify during it).
2. New `whsec_...` into `.env` as `STRIPE_WEBHOOK_SECRET` → universal flow **within the window**.
3. Verify: Dashboard → the endpoint → **Send test event** → expect 200. Watch the next real `payment_intent.succeeded`/`checkout.session.completed` settle correctly.
4. Repeat separately for the Connect endpoint (`/webhooks/stripe-connect` → `STRIPE_CONNECT_WEBHOOK_SECRET`). Remember Connect events arrive **only** on that second endpoint.

### 3. JWT secret (⚠️ schedule a quiet hour — hard cut)
Warn the operator first: rotating this **logs out every user immediately**, invalidates all media tokens and in-flight password-reset links. There is no dual-key grace. Get explicit confirmation of timing before proceeding.
1. Generate 64 chars of randomness locally:
   `-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 64 | ForEach-Object {[char]$_})`
2. Replace `JWT_SECRET` in `.env` → universal flow.
3. Verify: log in fresh on futureroots.app (old sessions must 401 → login; new login works; images render, which proves media tokens re-mint).

### 4. Agora app certificate (brief call impact — pair the console swap with the push)
1. Agora Console → the FutureRoots project → enable the **secondary certificate**, then promote it per Agora's swap flow. In-progress calls survive until token refresh; **new joins fail** while console and app disagree — so do steps 1–2 back-to-back.
2. New certificate into `.env` as `AGORA_SECRET` → universal flow immediately.
3. Verify: a Premium family can start/join a call (or confirm `POST /families/{id}/call/join` returns a token rather than 503/500 for an entitled member).

### 5. DB master password (the easy one — fully managed)
No `.env`, no push script, no cold starts. The password lives in the RDS-managed secret (`rds!db-...`) and the app self-heals: every new pooled connection pulls credentials from a 5-minute-TTL cached accessor, and a connect-time auth failure forces a refresh and retries once.
1. Rotate on demand:
   ```powershell
   $arn = aws secretsmanager list-secrets --region us-east-1 --query "SecretList[?starts_with(Name,'rds!db-')].ARN | [0]" --output text
   aws secretsmanager rotate-secret --secret-id $arn --region us-east-1
   ```
   (Or Secrets Manager console → the `rds!db-...` secret → Rotate immediately. An automatic schedule can also be enabled there.)
2. Verify (~1 minute later): `aws lambda invoke` with `{"futureroots_command":"migrate"}` returns `{"status": "migrated"}` — that's a full connect-with-fresh-credentials round trip. Also hit any DB-backed endpoint.
3. Expect nothing to break: established connections survive; warm Lambdas heal on their next new connection.

### 6. Testnet admin token / X client secret (low urgency)
- `TESTNET_ADMIN_TOKEN`: generate like the JWT secret → `.env` → universal flow. Update wherever the operator stores the operational copy.
- `X_CLIENT_SECRET`: regenerate in the X developer portal → `.env` → universal flow. Testnet X-linking breaks until both sides match.

## Full-rotation order (when rotating everything, e.g. suspected exposure)

1. Stripe secret key (grace window — start it first so the clock runs)
2. Both webhook signing secrets
3. Agora certificate
4. Testnet/X secrets
5. JWT secret **last** (it's the disruptive one — batch the user-visible cut into one moment)
6. DB password (independent — any time, zero impact)

One push + one cold-start cycle can cover steps 1–5 if the operator collects all new values into `.env` first; otherwise run the flow per secret. For suspected exposure, prefer immediate expiry over grace windows and accept the disruption.

## Verification checklist (after any rotation batch)

```powershell
# API + DB alive
Invoke-WebRequest https://api.futureroots.app/health -UseBasicParsing            # 200
aws lambda invoke --function-name FutureRoots-ApiFnE0725F78-CVhDBf56iARR `
  --payload '{\"futureroots_command\":\"migrate\"}' `
  --cli-binary-format raw-in-base64-out "$env:TEMP\rot-check.json" --region us-east-1
Get-Content "$env:TEMP\rot-check.json"                                           # {"status":"migrated"}
```
Plus, as applicable: fresh login (JWT), Stripe test event (webhooks), a Plan-section load (Stripe key), a call join (Agora), CloudWatch error scan for both Lambdas over the following hour.

## Emergency rollback

Explicit Lambda env vars override the secret overlay. If a rotation bricks something and the old value is still valid (grace window), set the old value directly:
`aws lambda update-function-configuration --function-name <fn> --environment "Variables={...existing...,FUTUREROOTS_STRIPE_SECRET_KEY=<old>}"` — then fix forward and REMOVE the override (it permanently shadows the secret until deleted). For the DB secret there is no override path — use Secrets Manager's version stages (`AWSPREVIOUS`) via `update-secret-version-stage` if a rotation must be undone.
