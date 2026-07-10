# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**FutureRoots** — a Family Wealth Network ("Building Generational Wealth & Memories"): families preserve memories, transfer wisdom, teach financial literacy, and build generational wealth around child-centered vaults. It is a **family platform, not a crypto product** — blockchain (Base) is invisible infrastructure only.

**Current status: design phase.** The repo contains documentation and an agent team, no application code yet. Phase 1 (scaffold) has not started — see `docs/roadmap.md`.

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
6. **Local-first dev, Lambda-shaped code:** everything runs locally (docker-compose Postgres, uvicorn, next dev); cloud services (Cognito/SES/S3/Base) sit behind thin abstractions with local implementations. AWS deployment is Phase 5. MVP infra cost ceiling ~$50/month.

## Stack (decided — do not relitigate)

Web: Next.js + TypeScript + Tailwind + ShadCN (`apps/web`, planned) · API: FastAPI + Pydantic + SQLAlchemy/Alembic (`apps/api`, planned) · PostgreSQL · Stripe · S3 presigned uploads · AI via APIs only (no self-hosted models) · Mobile (Expo) deferred.

## Out of MVP scope (do not build)

Trading, crypto wallets, DeFi, NFTs, complex investments, enterprise white-labeling, custom AI models.

## Commands

None yet — no code exists. When Phase 1 lands, record here: how to start the stack (docker compose + API + web), run migrations, and run tests (including a single test).

## Brand voice

Warm, optimistic, family-centered, trustworthy. All user-facing copy goes through the `brand-guardian` agent's rules (`.claude/agents/brand-guardian.md`).
