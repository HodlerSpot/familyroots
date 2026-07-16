# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**FutureRoots** — a Family Wealth Network ("Building Generational Wealth & Memories"): families preserve memories, transfer wisdom, teach financial literacy, and build generational wealth around child-centered vaults. It is a **family platform, not a crypto product** — blockchain (Base) is invisible infrastructure only.

**Current status: Phase 5 complete — live at https://futureroots.app.** All product phases (Family Graph, Vault/Feed/Memories, Achievement Economy, Time Capsules, Legacy Archive) are deployed: web on Amplify Hosting (futureroots.app + www), API on Lambda + RDS at `https://api.futureroots.app` (us-east-1, CDK stack in `infra/`, runbook in `docs/deploy.md`). DNS lives in Cloudflare (domain registered there). SES is in sandbox mode. **FutureRoots Premium** went live 2026-07-15 (family membership via Stripe Checkout subscriptions + gift year, entitlement-gated video — `docs/specs/premium.md`), and the hardening backlog round completed 2026-07-16 (runtime secrets in the `futureroots/api` Secrets Manager secret, media-scoped token auth, leave/remove-member with owner-departure billing, daily EventBridge maintenance command); the remaining backlog is the slimmed "Open" list in `docs/deploy.md`. Next: Phase 6 (AI & growth).

## Source-of-truth documents (read before designing or building anything)

- `docs/vision.md` — product vision, personas, modules, MVP scope, positioning. **Authoritative; do not redesign the product.**
- `docs/architecture.md` — system design, stack, local-first dev approach, key flows
- `docs/data-model.md` — PostgreSQL schema design and access rules
- `docs/roadmap.md` — phased build plan and what's explicitly deferred
- `docs/agents.md` — the role-based agent team in `.claude/agents/` and the feature workflow

## Non-negotiable principles

1. **North star:** a grandparent goes from milestone notification → congratulations → contribution → memory in **under 60 seconds**, never seeing blockchain.
2. **Zero crypto surface:** no wallets, seed phrases, gas, tokens, or Web3/crypto terminology in any user-facing string, ever.
3. **Children are profiles, not accounts** (COPPA/GDPR/PIPEDA): no child credentials; parental consent is recorded data; access is scoped by explicit family relationships.
4. **Money discipline:** integer cents + currency; the future-fund ledger is append-only; ledger entries only from verified Stripe webhooks; balances always derived.
5. **Private by design:** family-only experience, no public social features, no cross-family data access.
6. **Local-first dev, Lambda-shaped code:** everything runs locally (native Postgres service, uvicorn, next dev — no keys needed; local providers settle payments synchronously); cloud services (SES/S3/Stripe/Secrets Manager/Base) sit behind thin abstractions with local implementations. Deployed on AWS since Phase 5. Infra cost ceiling ~$50/month.

## Stack (decided — do not relitigate)

Web: Next.js + TypeScript + Tailwind + ShadCN (`apps/web`) · API: FastAPI + Pydantic + SQLAlchemy/Alembic (`apps/api`) · PostgreSQL · Stripe · S3 presigned uploads · AI via APIs only (no self-hosted models) · Mobile (Expo) deferred.

## Out of MVP scope (do not build)

Trading, crypto wallets, DeFi, NFTs, complex investments, enterprise white-labeling, custom AI models.

## Commands

Full setup details in `docs/dev.md`. Prereqs: Node 20+, uv, PostgreSQL 16 running as a Windows service (db/role `futureroots`/`futureroots` — see dev.md for the one-time SQL).

```powershell
# API (apps/api) — http://localhost:8000, OpenAPI docs at /docs
uv sync                                  # install deps
uv run alembic upgrade head              # apply migrations
uv run uvicorn app.main:app --reload     # run server
uv run pytest                            # all tests
uv run pytest tests/test_invites.py -k single_use   # single test
uv run alembic revision --autogenerate -m "msg"     # new migration after model changes

# Web (apps/web) — http://localhost:3000
npm install
npm run dev
npm run build                            # type-checks + production build
```

Dev email (invites) is written to `apps/api/var/outbox/` as text files — invite links are in there. On this machine `uv` lives at `$env:LOCALAPPDATA\Microsoft\WinGet\Packages\astral-sh.uv_*\uv.exe` and node at `C:\Program Files\nodejs` (add to PATH in fresh shells if not picked up).

`.ps1` scripts in this repo must stay **pure ASCII** — PowerShell 5.1 parses BOM-less UTF-8 as ANSI, so curly quotes/dashes from mojibake silently corrupt parsing.

Note: `apps/web` is **Next.js 15** (pinned — Amplify Hosting SSR doesn't support 16 yet; see `apps/web/AGENTS.md`). Dynamic-route `params` are Promises in server components (use `useParams()` in client components); `useSearchParams` needs a Suspense boundary.

## Brand voice

Warm, optimistic, family-centered, trustworthy. All user-facing copy goes through the `brand-guardian` agent's rules (`.claude/agents/brand-guardian.md`).
