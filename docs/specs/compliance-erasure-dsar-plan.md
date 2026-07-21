# Compliance: automated erasure + DSAR export + consent enforcement — plan

## Context

A compliance review (2026-07-21, during the Future Predictions build) confirmed a **platform-wide
capability gap**, not specific to any one feature: FutureRoots stores rich personal data about children and
adults (vault items, memories, capsules, contributions, and now predictions + an 18-year keepsake image) but
has **no self-serve / automated** path to (a) erase it, (b) export it for a subject-access / portability
request, or (c) enforce a consent revocation. Today the only tools are membership removal
(`family_members.status = 'removed'`, which erases nothing) and a **manual** operator runbook,
`docs/erasure-runbook.md` — thorough, but human-driven and slow.

This is a real GDPR / PIPEDA exposure for a **live** product (`https://futureroots.app`) whose primary
subjects are minors. It is a **founder + counsel decision**, and this plan is the engineering half of it: it
turns the manual runbook into code, adds the export half the runbook does not cover, and folds in the data
the four features shipped on 2026-07-21 added. **Nothing here should be built before the COUNSEL items
(retention periods, money-transmission posture, Stripe/Connect disposition) are signed off** — they are
inputs to the code, not afterthoughts.

The authoritative source-of-truth is **`docs/erasure-runbook.md` §3–§7** (the table walks, the financial
carve-out under GDPR Art. 17(3)(b)/(e), the media walk, the Stripe steps, the log template, and the §7
automation checklist). This plan does not restate those; it references them and specifies what is new.

## Why now (the trigger)

- The platform is live and can receive an Art. 17 erasure request or an Art. 15/20 access/portability
  request today, with only a manual, multi-day process to satisfy it (Art. 12(3) allows one month — tight
  for a hand process).
- **`consent_records.revoked_at` is modeled but never written anywhere in code** — "consent is revocable" is
  true on paper, false in effect.
- Future Predictions added a new, long-lived class of child personal data (free-text opinions about a named
  minor, retained up to 18 years, plus a rendered keepsake PNG). And **`docs/specs/future-predictions.md` §7
  claims a deletion cascade + admin erasure runbook + image re-render that do not exist in code** — a spec
  that overstates the product's actual erasure posture must be corrected regardless of when the code lands.

## Locked decisions (proposed — confirm before building)

- **Anonymize-not-delete for financial rows** (`contributions`, `fund_ledger_entries`,
  `family_subscriptions`, `premium_grants`) — retained under GDPR Art. 17(3)(b)/(e), identity link severed
  only. (Already the runbook's §3.D rule; carried forward verbatim.)
- **Tombstone-not-hard-delete for `users`** until nullable-FK migrations land, OR land those migrations
  first — pick ONE and enforce it in code (today it is silently neither). This plan proposes **landing the
  `ON DELETE` / nullable-FK migrations** for the tables where a hard-delete or SET NULL is always correct, so
  the erasure code is a clean transactional walk rather than a tombstone workaround.
- **Scope granularity** mirrors the runbook §2 tree: member-only, child-profile, whole-family.
- **DSAR export is machine-readable JSON + the subject's media files** (a zip), covering the same subject
  scopes, per GDPR Art. 20 portability.

## New data these four features added (must be covered)

| Table / object | Erasure | Export (DSAR) | Consent |
|---|---|---|---|
| `prediction_rounds` (child-scoped) | DELETE on child/family erasure, in leaf order before `children` | included in a child's export (the Book) | under the child's `profile_creation` consent |
| `predictions` (round + author scoped) | DELETE on child/family erasure; on **author** erasure, `author_user_id` follows the §3.A `users` handling (anonymize `author.display_name` in the Book, or hard-delete the author's rows if the requester wants their words gone) | a user's own predictions are their personal data → included in **member-only** export too | — |
| keepsake **MediaObject** (`content_type=image/png`, `child_id` set) | DELETE bytes via the §4 media walk (`storage.delete`) + the row; child-scoped so the existing walk reaches it | included as a media file in a child's export | — |
| `memory_prompts` (throttle, `user_id`+`family_id`) | DELETE on member-only / whole-family erasure (no retention value; already 90-day pruned) | trivial, low-value; include for completeness | — |
| the two new `NotificationPreference` columns | already covered — the whole `notification_preferences` row is DELETE'd in §3.A | included | — |

**Anonymization nuance for predictions:** the Book of Predictions shows `author.display_name`. There is
**no "anonymize to 'A family member'" path today** (the compliance review flagged this). Author erasure must
either rewrite that display name to a neutral label at render time (reading the tombstoned `users.display_name`
already does this if we set it to "Former member" in §3.A) or hard-delete the author's prediction rows —
a per-request choice, per runbook §3.A's comment handling.

## Workstreams (gated on the COUNSEL sign-offs)

**WS0 — Counsel inputs (blocking).** Financial-record retention duration (§3.D — typically 6–7 yr, set a firm
purge date); money-transmission posture; Stripe Customer delete vs. anonymize and Connect **deauthorize vs.
parent-closes-own-account** + un-transferred-balance disposition (runbook §5); who has standing for a
child/whole-family request in a dispute (§1). No code merges until these are answered.

**WS1 — Schema: close the FK gaps.** One migration adding `ON DELETE CASCADE` (where hard-delete is always
correct: `child_relationships`, `capsule_release_votes`, `fund_nudges`, the four video-call tables,
`prediction_rounds`→`predictions`, `predictions`→`prediction_rounds`) and nullable + `ON DELETE SET NULL`
(where a row must survive with a severed author: `*.created_by`, `feed_events.actor_user_id`, the financial
`*_user_id` columns). This makes hard-deleting `users` safe and removes the tombstone workaround. Chains off
the then-current head. (Alternative accepted by runbook §7: keep the walk explicit in app code and skip the
CASCADE — but it must be ONE or the other, enforced, not neither.)

**WS2 — `services/erasure.py`** (analogous to `services/premium.py`): three transactional entry points
`erase_member(user_id)`, `erase_child(child_id)`, `erase_family(family_id)` encoding the §3.A/B/C table walks
in dependency order; the §3.D anonymize path as a first-class branch (financial rows never enter the delete
loop); a `erase_media_for(child_id=|family_id=|user_id=)` helper on the existing `MediaStorage.delete()`
primitive; `handle_owner_departure` wired in (as in `leave_family`); a `consent_records.revoked_at` write on
child-profile erasure. Idempotent, single-writer, money-path rigor (WS6).

**WS3 — `services/export.py` + DSAR endpoints.** `POST /me/data-export` (member-only) and admin-mediated
child/family exports: assemble machine-readable JSON per the same scope tree + the subject's media as a zip
(reusing `download_media`'s per-object authz to gather keys). Predictions, memories, capsules (released +
the subject's own sealed authorship), contributions (the money facts the subject is entitled to see), and
prefs all included. Rate-limited; delivered via a short-lived signed link, not email attachment.

**WS4 — Stripe (`PaymentProvider`).** Add `delete_or_anonymize_customer`, reuse `cancel_subscription_now`,
add Connect `deauthorize` — behind the abstraction, honoring the WS0 counsel decisions (not defaulted).

**WS5 — Endpoints + step-up auth.** `DELETE /me`, child- and family-scoped erasure endpoints; enforce §1/§2
standing server-side (re-auth / step-up for a destructive action; `child_relationships` role check;
all-active-parent consent or sole-parent for whole-family). Auto-generate the §6 erasure-log entry from the
transaction.

**WS6 — Tests + review.** Erasure idempotency + order (no FK violation, no orphaned media, financial rows
survive with severed identity); export completeness (every subject-scoped table represented; no cross-family
leak; supporter scope respected); consent-revocation write; a compliance + security re-review (an erasure
endpoint is as consequential as a settlement path).

**WS7 — Doc truth-up (do this now, independent of code).** Correct `docs/specs/future-predictions.md` §7 to
state the *actual* posture (manual runbook today; no cascade/admin-re-render in code) and point at this plan;
update `docs/deploy.md` hardening-backlog line to reference this spec.

## Key files
- New: `apps/api/app/services/erasure.py`, `apps/api/app/services/export.py`, one Alembic migration,
  erasure/export routers, `apps/api/tests/test_erasure.py`, `apps/api/tests/test_export.py`; web self-serve
  "Download my data" / "Delete my account" surfaces in `settings/`.
- Modified: `apps/api/app/models.py` (FK `ondelete`/nullable), `services/premium.py` (reuse
  `handle_owner_departure`, `cancel_subscription_now`), `app/services/payments.py` (Stripe additions),
  `docs/specs/future-predictions.md` (§7 truth-up), `docs/deploy.md` (backlog line).
- Reuse: **`docs/erasure-runbook.md` §3–§7 is the authoritative behavior spec** — this code must encode it
  exactly, not a simplified version. The `services/premium.py` settlement-function pattern; the
  `MediaStorage.delete()` primitive; `download_media` per-object authz for the export media walk.

## Verification
1. `uv run pytest` green incl. new erasure/export tests; `uv run alembic upgrade head`.
2. Local end-to-end: seed a family with a child (vault items, a sealed + an open prediction round, a
   contribution, Premium). Run `erase_child` → predictions/rounds/keepsake-media/vault gone, `contributions`
   retained with severed identity, no FK error, `consent_records.revoked_at` set. Run `POST /me/data-export`
   → a zip with complete JSON + the caller's media, no other family's data. Revoke consent → enforced.
3. Confirm `future-predictions.md` §7 no longer claims an unimplemented cascade.

## Out of scope / COUNSEL (not an engineering call)
Retention duration for financial records; money-transmission / merchant-of-record posture; legacy
platform-held-balance escheatment; Connect deauthorize vs. parent-closes-account + un-transferred balance;
standing disputes (custody orders, estates, subpoenas). These are the WS0 blockers — flagged, not decided
here. This plan also does NOT change the supporter data-scoping (already correct) or add new consent *types*.
