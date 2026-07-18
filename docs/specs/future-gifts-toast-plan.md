# Future Gifts "gift added" toast — plan

## Context

**Future Gifts** (shipped earlier) is a per-child metric estimating the "meaningful time" preserved for a child, shown as an amber indicator on the vault page and family child card. Adding a memory grows that number silently. This feature adds a **quick, auto-dismissing banner (toast)** that fires the moment a member adds something that counts toward Future Gifts, telling them **how much they just added** — e.g. *"🎁 You just added about 2 minutes to Emma's Future Gift."* A small, warm reinforcement of the memory-preserving habit.

## Locked decisions (founder) + one required scope correction

- **Message = the delta they just added** (not the running total): "You just added about {duration} to {child}'s Future Gift."
- **Scope (as chosen):** everything that counts. **Correction from codebase review:** money **contributions must be excluded** from this toast. Future Gifts only counts a contribution once its payment *succeeds*, and in production that settlement happens **asynchronously via the Stripe webhook** (`settle_contribution` runs only from the signed webhook when `settles_via_webhook=True`), long after the giver has left the page — so there is no reliable delta to show at submit time. The toast therefore covers the three **synchronous** add flows: **memories, milestones, and time-capsule creation** (all on the child vault page). The contribution flow keeps its existing success confirmation; a future-gift toast there would be mistimed or wrong. (If desired later, a separate "your gift added X once it settles" could ride the contribution's `capsule_sealed`-style notification, but that's out of scope here.)

## Design

**All three triggers live on one page.** Memories (`MemoryForm`), milestones (`MilestoneForm`), and capsule creation (`CapsulesSection`) all render on `apps/web/src/app/family/[id]/child/[childId]/page.tsx` and, on success, call the page's `load()` refetch. So a **page-scoped toast** is sufficient — no app-wide provider or `layout.tsx` change needed (the root layout is a server component; leaving it untouched keeps this small).

**How the delta is computed — client-side diff, zero backend (recommended).** The page already holds the child's current score in state (`futureGiftsSeconds`, read from `child.future_gifts_seconds` in `load()`). On a successful add: capture the old value, run `load()` (which refetches `familyDetail` and sets the fresh value), then `delta = newValue - oldValue`; if `delta > 0`, show the toast using the existing `formatDurationLong` (an "about X" phrasing). This needs **no API change** and reuses everything Future Gifts already exposes. The only imprecision is a rare over-count if another member adds a memory in the same instant — acceptable for a warm, approximate nudge.
  - *Alternative (more precise, if wanted):* extract the per-item estimate inside `services/future_gifts.py` into a shared `estimate_gift_seconds(...)` helper (so aggregate and delta never diverge) and return `future_gifts_added_seconds` on the vault/milestone/capsule responses; the client shows that exact per-item value. More work (helper + `VaultItemOut`/`CapsuleOut` schema fields + `api.ts` types); not necessary for a delight feature. **Recommend the zero-backend diff.**

**The toast component.** No toast/snackbar exists today (only a persistent `ImpersonationBanner`, `Modal`, and inline `ErrorNote`). Add a small `"use client"` toast: fixed bottom-center, amber 🎁 treatment echoing the `FutureGifts` indicator, `role="status"` + `aria-live="polite"`, auto-dismiss via `setTimeout` (~3.5s, cleared on unmount/replace), click-to-dismiss, one-at-a-time, slide/fade honoring `prefers-reduced-motion`. Plain React + Tailwind, no dependency. Keep it a standalone component (`components/future-gift-toast.tsx` or a tiny generic `Toast`) driven by page state; promote to an app-wide provider only if a second use case appears.

**Copy** via brand-guardian: warm, "about X" to signal it's an estimate, child's first name, 🎁. Example: "🎁 You just added about 2 minutes to Emma's Future Gift."

## Workstreams

**WS1 — Toast component + page wiring (frontend + brand-guardian).** Build the toast; in `page.tsx`, wrap the three success paths (`MemoryForm` submit ~L612, `MilestoneForm` submit ~L480, and the capsule `onSealed`→`onChanged` path from `capsules.tsx`) so that after `load()` resolves, the page computes the delta and fires the toast. Because `load()` is a shared `useCallback` that sets score state directly, add a small "capture previous score → compare after refetch" step (e.g. `load()` returns the new score, or a dedicated `refreshAndToast()` wrapper reads the fresh child value). Copy from brand-guardian.

**WS2 — (Optional, only if precise deltas are chosen)** `services/future_gifts.py` `estimate_gift_seconds` extraction + `future_gifts_added_seconds` on `VaultItemOut`/`CapsuleOut` (`schemas.py`, `_vault_item_out` in `vault.py:111`, capsule serializer) + `api.ts` types + parity test that a single item's estimate equals its contribution to the aggregate. Skip if going with the zero-backend diff.

**WS3 — Tests.** `formatDurationLong` is already tested. Add: the toast renders on a positive delta and auto-dismisses; no toast on a zero/negative delta; reduced-motion path. Manual: add a photo (~30s), a ~5 MB video (~2 min), a milestone (~1 min), and a capsule → each shows the correct "about X" banner that disappears; confirm the on-page Future Gifts indicator also updated; confirm the contribute flow shows **no** future-gift toast.

## Key files
- New: `apps/web/src/components/future-gift-toast.tsx` (or a small generic toast).
- Modified: `apps/web/src/app/family/[id]/child/[childId]/page.tsx` (capture-diff + fire toast on the three add paths; ensure the capsule add path surfaces completion to the page). Possibly `apps/web/src/components/capsules.tsx` (bubble "added" up via the existing `onSealed`/`onChanged` callback, if the page needs the signal).
- Reuse: `formatDurationLong`/`formatDurationShort` (`apps/web/src/lib/text.ts`); the amber 🎁 visual language (`apps/web/src/components/future-gifts.tsx`); the existing `load()` refetch that already reads `future_gifts_seconds`; the `ImpersonationBanner` structure as a banner template.
- Backend only if the precise-delta alternative is chosen: `apps/api/app/services/future_gifts.py`, `apps/api/app/schemas.py`, `apps/api/app/routers/vault.py`, `apps/api/app/routers/capsules.py`, `apps/api/tests/test_future_gifts.py`.

## Verification
1. `npm run build` green (and `uv run pytest` if the backend alternative is used).
2. Local: on the child vault page, add a photo memory → "🎁 You just added about 30 seconds to {child}'s Future Gift." appears and auto-dismisses in ~3.5s; a ~5 MB video → "about 2 minutes"; a milestone → "about 1 minute"; a capsule → its delta. The on-page Future Gifts number updates in step. On the contribute flow, confirm **no** future-gift toast appears.
3. Accessibility: the toast is announced (`aria-live`) and dismissible by click; `prefers-reduced-motion` disables the slide.

## Out of scope
Money contributions (async settlement — see the scope correction); a persistent per-user contribution total; celebratory threshold toasts ("you crossed 1 hour!"); an app-wide toast/notification system (kept page-local); changing the Future Gifts scoring itself.
