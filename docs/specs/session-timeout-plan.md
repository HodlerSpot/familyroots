# Session timeout + "Stay logged in" — plan

## Context

Today every FutureRoots session is a **fixed 7-day JWT** in `localStorage` — no idle timeout, no way to opt into a longer or shorter session, and it persists across browser restarts on any computer. This adds a **30-minute sliding (inactivity) session timeout** as the default, plus a **"Stay logged in" checkbox** at login (unticked by default) that instead issues a **30-day** session. The result: on a shared computer a walk-away logs you out after 30 minutes of inactivity, while your own device can remember you for a month — the standard, expected behavior.

## Locked decisions (founder)

- **Sliding / inactivity** 30-minute timeout — active users are never logged out mid-task; logout happens after 30 minutes of inactivity.
- **"Stay logged in" = 30 days**, and a remembered session is not subject to the 30-minute idle timeout.
- **Checkbox unticked by default** (safe on shared/public computers).

## Design

**Token TTLs (backend).** `create_access_token(user_id, *, remember: bool = False)` (`security.py`) mints with `settings.session_ttl_minutes` (30) when not remembered, `settings.remember_me_ttl_days` (30) when remembered, and embeds a small `rmb: bool` claim so refresh knows which window to renew without re-authenticating. New settings in `config.py` (env-overridable): `session_ttl_minutes=30`, `remember_me_ttl_days=30` (replacing the fixed `jwt_ttl_hours` for session issuance; the impersonation token stays its own 30-min path). The existing impersonation-token `minutes=` idiom (`security.py:43`) is the pattern to copy.

**Sliding refresh — active users never expire (mirror the media-token flow).** New `POST /auth/refresh` (gated by `get_current_user`, so only a *still-valid* token can refresh) re-mints a fresh token preserving the `rmb` window, returning `TokenResponse` + `expires_in_seconds`. The web mirrors `ensureMediaToken` (`api.ts:433-462`): store `futureroots_token_exp`; on every `request()`, if the session token is within its final refresh window (~10 min for a 30-min token; ~1 day for a remembered token), background-refresh via a single in-flight promise. Any API activity slides the 30-minute window; an idle tab's token simply ages out. This is the core mechanism — no server-side session store needed (JWT stays stateless).

**Expired-vs-invalid signal + centralized timeout redirect.** Split `jwt.ExpiredSignatureError` in `security.decode_access_token` (today it collapses expired and invalid both to `None`) so `deps.get_current_user` can return a distinguishable 401 (e.g. `detail={"code":"session_expired"}`). Centralize the response in the web `request()` wrapper: on a 401, `setToken(null)` and redirect to `/login?next={path}&reason=timeout`; the login page shows a warm "Your session timed out — please sign in again" note when `reason=timeout`. This replaces the ~15 scattered per-page `if 401 → /login` checks (they can be simplified to just the on-mount `if (!getToken())` guard).

**Storage semantics = the real shared-computer protection.** `setToken(token, { remember })`: remembered → `localStorage` (persists across restarts, up to 30 days); not-remembered → `sessionStorage` (cleared when the browser/tab closes). So on a shared computer, closing the browser logs you out even before the 30-minute idle expiry. `getToken()` reads `sessionStorage` first, then `localStorage`; `setToken(null)` and `signOut()` clear both (plus the media token, as today).

**Idle timeout UX (light).** Refresh-on-API-traffic already enforces "30 min of no activity → next action 401 → login." Add a small optional idle timer (module-level, reset on debounced user activity + API traffic) that, for non-remembered sessions, proactively redirects to `/login?reason=timeout` at 30 minutes idle even if the user hasn't clicked — so an abandoned open tab bounces on its own. The token `exp` remains the hard server boundary; the timer is UX polish.

**Login checkbox.** Add `remember_me: bool = False` to `LoginRequest` (`schemas.py`) → thread through `login` (`auth.py`) → `create_access_token(user.id, remember=...)`. Add a quiet "Stay logged in" checkbox (unticked) to `apps/web/src/app/login/page.tsx`, pass it to `api.login`, and `setToken(token, { remember })`. Signup issues a default (non-remembered, 30-min) session.

## Workstreams

**WS1 — Backend.** `config.py` (two TTL settings), `security.py` (`create_access_token(remember=)` + `rmb` claim + `ExpiredSignatureError` split), `schemas.py` (`LoginRequest.remember_me`, optional `TokenResponse.expires_in_seconds`), `auth.py` (`login` threads remember; new `POST /auth/refresh`), `deps.py` (distinct `session_expired` 401). Keep testnet wallet-auth and signup on the default session TTL.

**WS2 — Web.** `api.ts`: session-token exp tracking + `ensureSessionFresh()` background refresh piggybacked on `request()` (mirroring `ensureMediaToken`); `setToken(token, {remember})` store selection; `getToken()` dual-store read; a centralized 401→`/login?reason=timeout` redirect; `api.login(email, password, remember)` + `api.refreshSession()`. `login/page.tsx`: the checkbox + the `reason=timeout` note. Optional idle-timer module. `site-header.tsx` `signOut()` already clears via `setToken(null)` — ensure it clears both stores.

**WS3 — Tests + review.** `apps/api/tests/test_auth.py` (+ maybe a new `test_security.py`): default token `exp` ≈ 30 min and remembered ≈ 30 days (patch `datetime.now`); `login(remember_me=true)` returns the long token; `/auth/refresh` re-mints preserving the window and **rejects an expired token** (401); expired-token request returns the `session_expired` 401 distinct from a garbage-token 401 (extend `test_me_requires_auth`). Web has no JS test runner (build-only) — verify `npm run build` + `tsc`. A short **security review** pass on the refresh endpoint (can only a valid token refresh? does refresh preserve, not escalate, the remember window? no way to turn a 30-min token into a 30-day one without re-login).

## Key files
- Backend: `apps/api/app/security.py`, `apps/api/app/config.py`, `apps/api/app/schemas.py`, `apps/api/app/routers/auth.py`, `apps/api/app/deps.py`, `apps/api/tests/test_auth.py`.
- Web: `apps/web/src/lib/api.ts`, `apps/web/src/app/login/page.tsx`, `apps/web/src/app/signup/page.tsx` (setToken signature), `apps/web/src/components/site-header.tsx` (signOut clears both stores), optional new `apps/web/src/lib/idle.ts`.
- Reuse: the media-token silent-refresh model (`api.ts` `ensureMediaToken`, security.py `create_media_token`); the impersonation-token `minutes=` TTL idiom (`security.py:43`); `MediaTokenResponse.expires_in_seconds` as the `expires_in_seconds` shape.

## Verification
1. `uv run pytest` green (+ new auth tests); `npm run build` + `tsc --noEmit` clean.
2. Local: log in WITHOUT "stay logged in" → token stored in `sessionStorage`, `exp` ~30 min; keep using the app (API calls) → it silently refreshes and never logs out; leave it idle >30 min → next action redirects to `/login?reason=timeout` with the warm note; close the browser and reopen → logged out (sessionStorage cleared). Log in WITH "stay logged in" → token in `localStorage`, `exp` ~30 days, survives restart, no idle logout. Sign out → both stores cleared, cannot navigate back into protected pages.
3. Deploy note: this changes the token *lifetime*, not the secret, so existing 7-day tokens stay valid until they expire (no forced logout on deploy). After `cdk deploy`, force a Lambda cold start before verifying (warm containers serve stale code).

## Security notes / accepted limitations
- **Stateless JWT = no server-side revocation.** A remembered 30-day token remains valid until `exp`; "Sign out" clears it client-side but a captured token can't be killed server-side short of rotating `FUTUREROOTS_JWT_SECRET` (which logs everyone out). Accepted for this app; documented. A future denylist / refresh-token rotation is the upgrade path if per-session revocation is ever needed.
- Tokens live in web storage (as today); the 30-min default + sessionStorage materially reduces shared-computer exposure vs. the current 7-day localStorage token.

## Out of scope
Server-side session store / token denylist / refresh-token rotation; "log out all other devices"; a visible countdown / "you'll be logged out in 2 min" warning modal (the idle timer just redirects); 2FA; changing where tokens are stored (stays web storage, not httpOnly cookies — a larger architectural change).
