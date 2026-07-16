# FutureRoots — Local Development

Local-first: everything runs on your machine. No AWS account or Stripe keys needed (production config paths like the Secrets Manager fetch only activate when their env vars are set — no ARN, no fetch).

## Prerequisites

- **Node.js** 20+ (`winget install OpenJS.NodeJS.LTS`)
- **uv** (Python manager) (`winget install astral-sh.uv`)
- **PostgreSQL 16** (`winget install PostgreSQL.PostgreSQL.16`) — running as a Windows service

## One-time database setup

Create the dev role and database (run in psql as the postgres superuser):

```sql
CREATE ROLE futureroots LOGIN PASSWORD 'futureroots';
CREATE DATABASE futureroots OWNER futureroots;
```

## API (`apps/api`)

```powershell
cd apps/api
uv sync                                   # install deps into .venv
uv run alembic upgrade head               # apply migrations
uv run uvicorn app.main:app --reload      # http://localhost:8000 (docs at /docs)
```

Tests:

```powershell
uv run pytest                             # whole suite
uv run pytest tests/test_invites.py -k single_use   # one test
```

Dev email goes to `apps/api/var/outbox/` as text files (invite links are in there).

Configuration comes from `.env` (see `.env.example`); everything defaults to sane local values, so no `.env` is needed to start.

## Web (`apps/web`)

```powershell
cd apps/web
npm install
npm run dev                               # http://localhost:3000
```

The web app expects the API at `http://localhost:8000` (`NEXT_PUBLIC_API_URL` to override).

## What works locally with no keys

- **Payments & Premium:** the local `PaymentProvider` settles synchronously in the same request — contribution confirm, Premium subscription checkout, and gift checkout all complete end to end (entitlements, feed events, emails) with no Stripe account.
- **Media:** the web client mints a short-lived media token (`POST /auth/media-token`) automatically and appends it to media URLs, so photos/video render locally with nothing to configure.

## Writing PowerShell scripts

`.ps1` scripts in this repo must stay **pure ASCII** — PowerShell 5.1 parses BOM-less UTF-8 as ANSI, so curly quotes/dashes from mojibake silently corrupt parsing.

## Migrations

After changing `app/models.py`:

```powershell
cd apps/api
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```
