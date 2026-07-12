# FutureRoots Testnet — Gamified Testing Harness (Design of Record)

**Owner:** Testnet Gamification Engineer
**Surface:** testnet.futureroots.app only. The family product (futureroots.app) never shows any of this.

## Purpose

Get as many testers as possible exercising every corner of the platform by making
testing feel like a game. Testers sign in with a Base Sepolia wallet, earn points
for real platform actions, and compete on a real-time leaderboard. Points trace the
product's real user journeys, so leaderboard chasing doubles as coverage of the
flows that matter — with the north-star grandparent journey scoring highest.

## The flag wall (why none of this exists outside testnet)

The family product has a zero-crypto-surface rule: no wallets, points, quests, or
crypto vocabulary, ever. Everything here sits behind two explicit flags:

| Layer | Flag | Effect when off |
|---|---|---|
| Backend | `FUTUREROOTS_TESTNET_MODE` (`settings.testnet_mode`, default `False`) | `/testnet/*` routes are **not mounted** in `app/main.py`, and every testnet route also carries a request-time `require_testnet` dependency that returns **404** — a double wall. The `award()` hook is a no-op, so product actions write no point data. |
| Frontend | `NEXT_PUBLIC_TESTNET=1` (build-time) | The testnet shell, wagmi providers, wallet gate, quests panel, and banner are behind a compile-time check plus a dynamic import: they are neither mounted nor fetched. `/leaderboard` renders the standard 404. Zero UI difference. |

Why 404 and not 403: outside testnet mode these endpoints should be
indistinguishable from routes that were never built. Nothing in the production
API surface should even hint that a points system exists.

The touch on the product codebase is deliberately tiny: one import plus one
`award(...)` line in four routers, and a seven-entry event-to-action map inside
`services/feed.py::emit()`. Everything else lives in `app/testnet/` and
`apps/web/src/components/testnet/`.

## Tester identity and auth flow (signature-only, no transactions)

Sign-In-With-Ethereum style on Base Sepolia (chainId 84532). No gas, no
transactions, no funds — a signature is only a proof of key ownership used as a
login. One tester per wallet.

1. `POST /testnet/auth/nonce {address}` — validates the address shape, stores or
   refreshes a single-use nonce for that wallet (`wallet_nonces` row), and returns
   `{nonce, message}` where the message is exactly:

   ```
   Sign in to FutureRoots Testnet (Base Sepolia)

   Wallet: {address}
   Nonce: {nonce}
   ```

   Addresses are normalized to lowercase everywhere (storage, message, comparison).

2. The browser signs the message with `personal_sign` (wagmi `signMessage`).

3. `POST /testnet/auth/verify {address, signature}` — recovers the signer with
   `eth_account.Account.recover_message(encode_defunct(text=message))` and requires
   it to equal the address (case-insensitive). The nonce is **single-use** (deleted
   on success) and expires after 10 minutes. On first login the server creates:
   - a `Tester` row (wallet is the identity), and
   - a linked platform `User`: email `{address}@wallet.testnet.futureroots.app`,
     display name `Tester 0xab12cd...89ef` (ASCII only), and a random
     complexity-compliant password hash nobody knows.

   It awards `connect_wallet` exactly once per wallet, then returns
   `{access_token}` from the product's own `create_access_token(user.id)`.

Because the token is a normal platform JWT, the **entire existing product API
works unchanged** — testers create families, invite grandparents, contribute, and
seal capsules through the very same endpoints real families use. That is the
point: testing traffic exercises production code paths, not a parallel API.

The synthetic email doubles as the tester's invite address: another tester can
invite `0x...@wallet.testnet.futureroots.app` to their family, which is how the
invite-acceptance and grandparent-contribution quests are completed across
testers. The quests panel shows each tester their own address for this.

## Quest catalog

Points weight the north-star journey heaviest: invite a grandparent (150), accept
an invitation (125), and complete a contribution (200) are the three richest
quests, and running the full chain — milestone, invitation, acceptance,
contribution — is worth 525 points in one sitting. Repeatable low-effort actions
(memories) score low. Caps are per UTC day.

| Action key | Quest (warm label) | How it's earned | Points | Daily cap |
|---|---|---|---|---|
| `connect_wallet` | Join the testing crew | First wallet sign-in | 25 | once ever |
| `set_display_name` | Pick your tester name | Set a display name in the quests panel | 10 | once ever |
| `create_family` | Plant your family tree | Create a family space | 75 | 2 |
| `add_child` | Start a child's vault | Add a child profile (with consent) | 60 | 3 |
| `invite_grandparent` | Invite a grandparent | Send an invitation with the grandparent role | 150 | 5 |
| `invite_family` | Welcome more family | Send an invitation with any other role | 60 | 5 |
| `invite_accepted` | Join a family | Accept another tester's invitation | 125 | 3 |
| `milestone` | Share a milestone | Post a milestone to a child's vault | 50 | 5 |
| `contribution` | Grow a future fund | Complete a contribution end to end | 200 | 5 |
| `memory_added` | Tuck away a memory | Add a photo, message, or memory to a vault | 30 | 10 |
| `create_goal` | Set a goal | Create a goal for a child | 40 | 5 |
| `achievement` | Celebrate an achievement | A parent marks a goal complete | 50 | 5 |
| `capsule_created` | Seal a time capsule | Seal a letter or recording for the future | 60 | 3 |
| `capsule_released` | Open a time capsule | A capsule you sealed is released | 75 | 3 |
| `bug_verified` | Squash a real bug | Report a bug our team confirms is real | 250 | 5 |

`bug_verified` is the single richest action (250) because a confirmed bug is the
most valuable testing outcome we can buy. It is deliberately **not** self-claimable:
a tester submits a report freely (no points), and the award fires only when a human
reviewer confirms the bug is real. Submission is never a scoring path — see
"Bug reports (human-verified)" below.

Maximum score on day one (full caps, both once-ever quests, five full north-star
chains): a determined tester touches every module to get there — which is the
coverage we want.

## Award mechanics (server-verified only)

`app/testnet/service.py::award(db, user_id, action)` is the single scoring path:

- **No-op unless** `settings.testnet_mode` is on.
- **No-op for non-testers** — a user without a linked `Tester` row scores nothing.
- **Caps enforced by derivation**: a `COUNT(*)` of today's events for that
  tester and action, compared to the catalog cap (once-ever quests count
  all-time). No stored counters.
- **Append-only**: inserts a `PointEvent(tester_id, action, points)` and never
  updates or deletes. Totals are always `SUM(points)` — mirroring the
  future-fund ledger discipline.
- **Rides the caller's transaction**: `award()` never commits. Points land only
  if the underlying product action commits, so a rolled-back action can never
  score. Clients can never claim points; every award comes from a server-side
  code path that just performed the real action.

Wiring:

- `services/feed.py::emit()` maps feed events to actions — milestone,
  memory_added, achievement, contribution, capsule_created, capsule_released
  (emitted with the capsule's creator as actor, so the sealer earns the release),
  and member_joined → `invite_accepted`.
- Explicit one-line awards for actions that have no feed event: `create_family`,
  `add_child`, `create_goal`, and `create_invite` (grandparent role scores as
  `invite_grandparent`, everything else as `invite_family`).
- `connect_wallet` and `set_display_name` are awarded inside the testnet router.
- `bug_verified` is awarded **only** by the admin bug-verification endpoint, never
  by the tester who submitted the report — the one action a human, not the server,
  gatekeeps.

## Bug reports (human-verified)

Confirmed bugs are worth more than any other action, so the incentive to file them
is strong — which is exactly why the points can never be self-awarded. The flow
splits submission from scoring:

1. `POST /testnet/bugs {title, body}` — a tester files a report. It is created
   with `status="pending"` and **awards nothing**. A tester may hold up to 20
   pending (unreviewed) reports; the 21st is rejected with `429` so the endpoint
   can't be used to spam the review queue.
2. `GET /testnet/bugs` — the tester's own reports, newest first, each with its
   status (`pending` | `verified` | `rejected`).
3. `POST /testnet/bugs/{id}/verify {decision}` — the **only** path that awards
   `bug_verified`. Admin-only, gated by an `X-Admin-Token` header compared
   constant-time against `settings.testnet_admin_token`
   (`FUTUREROOTS_TESTNET_ADMIN_TOKEN`). If no token is configured, verification is
   impossible by design. On `verified`: status becomes `verified` and, if the
   report has not already scored, `award(bug_verified)` fires for the reporting
   tester and the report's `points_awarded` flag is set. On `rejected`: status
   becomes `rejected`, no points. The `points_awarded` flag makes re-verifying
   idempotent (a report can never award twice), while `award()`'s own daily cap of
   5 still bounds how many verified bugs score per tester per day.

Anti-gaming summary for this quest: submission ≠ points; only a human reviewer's
verify awards; the award is idempotent per report; the pending queue is capped per
tester; and the admin token is required for the one privileged action.

## Leaderboard mechanics

- `GET /testnet/leaderboard` — top 50 by derived total, one
  `SUM ... GROUP BY tester` query (outer join so brand-new testers appear with 0).
  Ties break by who joined first. Each entry: `{rank, display_name, points,
  is_me}`; display name falls back to the shortened wallet (`0xab12cd...89ef`).
- If the caller is authenticated and is a tester, the response also carries
  `my_rank` and `my_points` (rank = 1 + count of testers with a strictly higher
  total), so a tester outside the top 50 still sees where they stand.
- The web leaderboard polls every 5 seconds for the real-time feel. At tester
  scale this is a cheap aggregate; if it ever hurts, add a 5-second cache or a
  materialized total — but only then.

## Anti-gaming rules

1. **One tester per wallet** — `testers.wallet_address` is unique; a wallet maps
   to exactly one platform user. Sybil cost is real (new wallet, new full journey).
2. **Daily caps on every action**, enforced server-side by counting today's
   events. Once-ever quests (connect, name) can never repeat.
3. **Server-verified actions only** — there is no "claim points" endpoint at all.
   Awards fire inside the product code path that performed the action, in the
   same transaction.
4. **Single-use, short-lived nonces** — a login signature can't be replayed:
   the nonce dies on successful verify and expires after 10 minutes.
5. **Repeatable spam actions score low** — memories are 30 points with the
   loosest cap; the expensive-to-fake multi-actor flows (invite, accept,
   contribute) carry the weight.
6. **Append-only, derived totals** — no balance to tamper with; disputes are
   auditable event by event.
7. **Cross-tester quests need a counterparty** — `invite_accepted` requires a
   second wallet to actually accept, which is exactly the multi-user family
   behavior we need tested.

Known accepted gap: one person can run several wallets. Mitigation is cost (each
wallet must replay whole journeys under caps), not prevention — fine for a
points-for-glory testnet with no monetary rewards.

## API summary (all under `require_testnet`, 404 when the flag is off)

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /testnet/auth/nonce` | none | Issue/refresh single-use sign-in nonce and message |
| `POST /testnet/auth/verify` | none | Verify signature, create tester+user on first login, return platform JWT |
| `GET /testnet/quests` | bearer | Catalog plus the caller's per-quest counts, today's counts, and total |
| `GET /testnet/leaderboard` | optional | Top 50 plus caller's own rank when authed |
| `POST /testnet/profile` | bearer | Set tester display name (max 40 chars) |
| `POST /testnet/bugs` | bearer | File a bug report (pending, awards nothing; capped at 20 open) |
| `GET /testnet/bugs` | bearer | The caller's own bug reports with status, newest first |
| `POST /testnet/bugs/{id}/verify` | `X-Admin-Token` | Human review; `verified` awards `bug_verified`, `rejected` does not |

Data model (`app/models.py`): `Tester` (wallet 1:1 user), `WalletNonce`
(single-use login nonces), `PointEvent` (append-only, indexed by tester), and
`BugReport` (tester-submitted bugs with review status and an idempotent
`points_awarded` flag). Migration is autogenerated by the main session, not by
hand.

## Frontend harness (`NEXT_PUBLIC_TESTNET=1` builds only)

- **Testnet banner** — a slim strip on every page: "FutureRoots Testnet · points
  mode", so testers always know they're on the harness. Brand colors, product
  pages otherwise untouched.
- **Wallet gate** — with the flag on and no session, every route shows a warm
  connect screen ("Connect your wallet to start testing") instead of the email
  login/signup flow: connect (injected connector, Base Sepolia) → fetch nonce →
  sign → verify → token stored via the product's own `setToken` → straight into
  the normal app.
- **Quests panel** — a floating "🎮 Quests" button (bottom right, every page)
  opens the catalog with checkmarks, per-quest points and daily progress, the
  tester's display name editor, their invite address, and a link to the
  leaderboard.
- **`/leaderboard`** — top 50, the tester's own row highlighted, own rank shown
  even outside the top 50, polling every 5 seconds.
- Providers (wagmi + react-query) mount only inside the dynamically imported
  testnet shell, so flag-off builds neither mount nor download any of it.

## Rollout notes

1. **Migration**: main session runs `alembic revision --autogenerate` (tables
   `testers`, `wallet_nonces`, `point_events`) and `upgrade head` on the testnet
   database only. Production can safely carry the empty tables, but nothing
   requires them while the flag is off.
2. **Deploy**: testnet.futureroots.app gets `FUTUREROOTS_TESTNET_MODE=1` on the
   API and a web build with `NEXT_PUBLIC_TESTNET=1`; production gets neither.
   Keep testnet on its **own database** — tester data is synthetic and should
   never mingle with family data. Also set `FUTUREROOTS_TESTNET_ADMIN_TOKEN` to a
   strong random secret on the testnet API: it is the shared secret a reviewer
   passes as `X-Admin-Token` to verify a bug and release its 250 points. Leave it
   unset (the default) and no bug can ever be verified.
3. **Tester onboarding copy** lives on the wallet gate; testers need only an
   injected wallet (MetaMask, Coinbase Wallet) — no funds, Base Sepolia is
   signature-only here.
4. **Resets/seasons**: to start a fresh season, truncate `point_events` (testers
   and their vaults survive). Point values can be tuned in
   `app/testnet/service.py` — the catalog is data, not schema.
5. **Watch for**: leaderboard query cost at scale (add cache then), invite spam
   between testers (caps hold it to 5/day), and any testnet vocabulary leaking
   into shared components (there is none today; keep it that way in review).
