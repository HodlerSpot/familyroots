# FutureRoots Memory Request — monthly memory prompt

## Context

Vaults grow only when family members remember to add to them. **Memory Request** is a gentle monthly ritual: once per calendar month each family member is nudged to add a memory for the family's **child of the month** (children rotate month to month). The prompt reaches them through the bell, web push, email, and a dismissible in-app card, and it *skips anyone who has already added a memory that month* so it rewards activity instead of nagging. It reuses the notification system, the daily maintenance sweep, and the `FundNudge` throttle pattern — almost no net-new machinery.

## Locked decisions (founder)

- **Target:** one **rotating child per month** — each month deterministically picks one of the family's children; a 1-child family always gets that child.
- **Cadence:** **shared calendar month** — every eligible member is prompted at most once per calendar (UTC) month.
- **Satisfy logic:** **skip members who already added a memory this month** (generous: *any* memory for *any* child in this family this month counts — the goal is anti-nag, not per-child bookkeeping).
- **Channels:** in-app **bell + web push + email** (a new notification kind) **and** a dismissible in-app **card** on the family/child page.
- **Free** feature; **supporters excluded** (they cannot add memories — `add_vault_item` gates `require_not_supporter`).

## Design

**Rotating child (deterministic, no state).** For a family's active children sorted by `created_at, id`: `idx = (year*12 + (month-1)) % len(children)`; child-of-the-month = `children[idx]`. Same result on every read and in the sweep, so the card and the notification always agree. Zero children → no prompt, no card.

**Two independent surfaces from one rule:**
1. **In-app card** = computed **on read**, no table. `GET /families/{family_id}/memory-prompt` → `{ period: "YYYY-MM", child: {id, first_name}, satisfied: bool } | null` (null for supporters or childless families). `satisfied` = the caller has any non-deleted `VaultItem` on a child of this family with `created_at` in the current UTC month. The card shows "Add {Month}'s memory for {child}" with a CTA deep-linking to `/family/{family_id}/child/{child_id}`; it auto-hides once `satisfied`, plus a soft client-side dismiss (localStorage, per period) so it never nags.
2. **Notification** = sent by the **daily maintenance sweep**, idempotent via a throttle table.

**The sweep — new `run_memory_prompts(db)` in `services/maintenance.py`** (added to `run_maintenance`, counted in its summary, mirroring the `fund_nudges` step). For each family with children, resolve the month's child, then for each active **non-supporter** member who (a) has **no** `memory_prompts` row for `(user_id, family_id, period)` and (b) is **not** already satisfied this month: insert the throttle row (unique-constraint claim, `IntegrityError`-rescue like `FundNudge`), and stage a `notify(kind=memory_request, ...)` batch; commit, then `batch.deliver(db)` post-commit. Sends at most one prompt per member per family per month, catches members who join mid-month, and is safe to run daily (idempotent) — the existing `FundNudge` idiom exactly, but system-initiated inside the sweep instead of an endpoint. Fan-out is inline per family (small scale; note the async self-invoke scale seam already documented for broadcasts).

**No feed event** — a personal reminder is not a family occurrence (matches `call_live`/`announcement`, which emit none). The real `memory_added` feed event still fires when the member responds.

## Data model (one Alembic migration off head `b8f2c1a9d4e7`)

- **New table `memory_prompts`** (throttle/idempotency, mirrors `FundNudge`): `id`, `user_id` FK, `family_id` FK, `child_id` FK (the child prompted that month — for audit/copy), `period` `String(7)` ("YYYY-MM"), `created_at`. **Unique `(user_id, family_id, period)`**; index on `family_id`. Pruned after 90 days in `run_maintenance` (mirror the `fund_nudges` prune).
- **New notification kind `memory_request`** — the full checklist established for the notification system:
  - `NotificationKind.memory_request` (`services/notify.py`), `PREF_ATTRS["memory_request"] = ("email_memory_request","push_memory_request")`.
  - Two `NotificationPreference` boolean columns `email_memory_request` / `push_memory_request` (both **default true** — a valued monthly ritual across the chosen channels), same migration; `DEFAULT_PREFS` + its lockstep count comment (`services/notifications.py`) updated to eleven kinds / 22 switches.
  - `NotificationPrefs` pydantic schema and the web `NotificationPrefs`/`PrefKey` type gain both keys; a new settings row.

## Workstreams (parallelizable; API contract frozen)

**WS1 — Backend model + migration.** `memory_prompts` table + `memory_request` kind + 2 pref columns; one migration (add-columns loop from `b8f2c1a9d4e7_expanded_notifications.py:29-57` + `create_unique_constraint` from `d41f7b6a90c3`). `FeedEventType` untouched (no prompt event).

**WS2 — Sweep + service.** `services/memory_prompts.py` (or fold into maintenance): rotating-child selector, satisfied-this-month query (anti-join: active non-supporter members via the `family_recipients` shape, minus members with a qualifying `VaultItem`), the claim+notify loop with post-commit delivery; wire into `run_maintenance` + the 90-day prune. Notification `title`/`body`/`email_builder` + `url` deep-link.

**WS3 — API.** `GET /families/{family_id}/memory-prompt` (card state, computed on read; null for supporters/childless; no birthdate/sensitive data involved). Uses `get_active_membership`. No new write endpoint — responding is the existing `add_vault_item`.

**WS4 — Web (frontend + ux-designer + brand-guardian).** `MemoryPromptCard` on the family page (and/or child vault page) — warm CTA, auto-hide when satisfied, soft per-period dismiss; the settings toggle row ("Monthly memory prompt", Email + Push) in a **"Reminders"** group or the "Family moments" group in `settings/page.tsx`; the bell notification flows automatically. Copy via brand-guardian → `docs/brand/notifications-copy.md`.

**WS5 — Tests + review.** Sweep idempotency (run twice → one prompt); rotating-child determinism across months and child counts (0/1/N); satisfied-member skip; new-member-mid-month gets prompted; supporter never prompted and card is null; per-family independence for a multi-family member; pref default + mute honored; the `GET .../memory-prompt` matrix. Then a QA pass on the exactly-once behavior.

## Key files
- New: `apps/api/app/services/memory_prompts.py`, one Alembic revision, `apps/api/tests/test_memory_prompts.py`, `apps/web/src/components/memory-prompt-card.tsx`.
- Modified: `apps/api/app/models.py` (`MemoryPrompt` table + the two `NotificationPreference` columns), `apps/api/app/services/notify.py` (kind + PREF_ATTRS), `apps/api/app/services/notifications.py` (DEFAULT_PREFS), `apps/api/app/services/maintenance.py` (call sweep + prune), `apps/api/app/schemas.py` (NotificationPrefs + a `MemoryPromptOut`), `apps/api/app/routers/families.py` (the memory-prompt endpoint), `apps/web/src/lib/api.ts` (prefs keys + method + type), `apps/web/src/app/settings/page.tsx` (toggle row), `apps/web/src/app/family/[id]/page.tsx` (card).
- Reuse: `FundNudge` throttle idiom (`models.py:488-504`, `funds.py:200-218`); `notify()` + `NotificationBatch` post-commit (`services/notify.py`); `family_recipients` audience shape (`notify.py:144-170`); the notification-kind checklist from migration `b8f2c1a9d4e7`; the maintenance sweep + prune structure (`maintenance.py:117-182`).

## Verification
1. `uv run pytest` green (+ new tests); `uv run alembic upgrade head`; `npm run build` green.
2. Local: family with 2 children + 2 members + 1 supporter. Run the maintenance sweep → both non-supporter members get a `memory_request` bell row + (push/email per prefs) deep-linked to this month's rotating child; the supporter gets nothing; `GET .../memory-prompt` shows the correct child and `satisfied:false` for a member, `null` for the supporter. One member adds a memory → their `satisfied` flips true and the card hides. Re-run the sweep → no second prompt (idempotent); the member who added a memory is skipped. Advance the "month" (seed by computing a different period) → the rotation picks the other child.
3. Confirm muting `push_memory_request`/`email_memory_request` in settings suppresses those channels while the bell row still writes (the "bell is always written" rule).
4. Deploy note: after `cdk deploy`, force a Lambda cold start before verifying (warm containers serve stale code).

## Out of scope (MVP)
Per-child fan-out (one prompt per child); themed monthly prompts ("a holiday memory"); streaks/gamification; configurable cadence; a dedicated prompt-response screen (responding uses the normal add-memory flow); SES production access (email prompts only reach verified addresses until then — bell/push work regardless).
