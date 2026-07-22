# FutureRoots — GDPR/PIPEDA Erasure Runbook

Status: **operational runbook, manual process**. No self-serve deletion endpoint
exists today (verified against `apps/api/app/routers/*` as of 2026-07). This
document tells a human operator (or an AI agent under human supervision) how to
execute an erasure request end to end, by hand, against the current schema and
storage layer. See `docs/data-model.md` (schema, access rules, Premium
retention section) and `docs/deploy.md` (hardening backlog) for design context;
this doc operationalizes both.

**Regulatory frame:** GDPR Art. 17 (Right to Erasure), COPPA (parental
control over a child's data — the parent *is* the requester for a child
profile, since children never hold credentials here), PIPEDA Principle
4.5/4.9 (retention limits, individual access/correction). This runbook is
**not legal advice**; items marked **COUNSEL** must go through actual counsel
before the operator acts.

> **Decisions resolved (founder, 2026-07-21).** Several COUNSEL items below are
> now decided and encoded in code: **financial-record retention = 7 years**
> (then the maintenance sweep purges fully-severed rows — see §3.D); **Stripe
> Connect on erasure = leave connected, don't auto-deauthorize** (the parent
> manages/closes their own account and any balance — see §5). The automated
> erasure/export code (`services/erasure.py`, `services/export.py`,
> `routers/erasure.py`) now implements the §7 backlog. See
> `docs/specs/compliance-erasure-dsar-plan.md` (WS0 RESOLVED) for the full set.

---

## 0. Ground truth from the codebase (read this before touching data)

- **No account-deletion or family-deletion endpoint exists.** Grep of
  `apps/api/app/routers/` for delete/remove/cascade turns up only:
  `POST /families/{id}/members/me/leave` and
  `DELETE /families/{id}/members/{user_id}` (`apps/api/app/routers/families.py`).
  These set `family_members.status = 'removed'` and stop
  nothing else — **this is membership removal, not erasure.** Docstring in
  code is explicit: "Nothing the member authored is touched: memories,
  contributions, capsules, and legacy items stay with the family." Do not
  treat a "leave" or "remove member" action as satisfying an erasure request.
- **No FK in `models.py` declares `ON DELETE CASCADE`.** Every relationship
  (`children.family_id`, `vault_items.child_id`, `contributions.child_id`,
  `fund_ledger_entries.account_id`, the four video-call tables, the four
  Premium tables, etc.) is a bare `ForeignKey(...)` with default `NO ACTION`.
  Deleting a parent row without manually clearing children rows first will
  raise an FK violation (or, if you delete children rows in the wrong order,
  silently orphan something). **Every deletion in this runbook is manual and
  order-dependent** — see §3.
- **The storage abstraction (`apps/api/app/services/storage.py`) has a
  working `delete(storage_key)` on both `LocalDiskStorage` and
  `S3MediaStorage`.** But as of this writing it is called from exactly two
  places, both in `apps/api/app/routers/vault.py`, both **upload-rejection
  cleanup** (file too large; a video sniffed under a non-video declared
  content-type) — **not** from any erasure/cascade path. The `docs/deploy.md`
  hardening-backlog line "S3 cascade delete exists in code" overstates this:
  the *primitive* exists and is proven correct, but there is no code path
  that walks a child's/family's media and calls it for erasure. Deleting
  media for an erasure request today means finding every
  `media_objects.storage_key` for the subject and calling `storage.delete()`
  (or the S3 console/CLI equivalent) one by one — see §4.
- **`consent_records.revoked_at` is never written anywhere in the codebase.**
  Consent revocation is modeled but not implemented; there is no "revoke
  consent" endpoint. An erasure request is the practical trigger for setting
  it manually (§3).
- **`docs/data-model.md` documents a `notifications` table (payload, sent_at,
  read_at) that does not exist in `models.py`.** Only `NotificationPreference`
  (per-user on/off switches, no content, no per-message history) exists in
  code. There is nothing to purge for "notification history" beyond that
  preferences row — flagging this doc/code drift for the data-model owner,
  but it does not change this runbook's actions.
- **Testnet tables** (`testers`, `x_auth_states`, `wallet_nonces`,
  `point_events`, `bug_reports.tester_id`) belong to the separate
  `testnet.futureroots.app` deployment/database and gamified testing program.
  They are out of scope for a family-product erasure request; if a *tester*
  (not a family user) requests deletion, handle it against the testnet DB
  under the same principles, scoped to `testers.id`.
- **Stripe integration reference:** `.claude/skills/stripe-integration/SKILL.md`
  is the authoritative map of money tables/flows; §5 below is derived from it.

---

## 1. Request intake

1. **Only an adult can request erasure.** Children hold no credentials and
   cannot submit a request (COPPA — there is no child account to authenticate).
   A request "for a child" must come from an adult holding a `parent` or
   `guardian` `child_relationships` row for that child (or, absent that,
   a documented legal guardian — **COUNSEL** if there's any dispute about who
   has authority, e.g. divorced parents, revoked guardianship).
2. **Verify identity and standing** before touching any data:
   - Confirm the requester authenticates as the `users` row they claim to be
     (existing session/login), OR, if they can no longer log in, verify via
     the email on file plus a second factor (e.g. reply-to a link sent to
     `users.email`, or admin lookup + a call-back to a known number if one is
     on file). Do not act on an unauthenticated inbound email alone.
   - Confirm standing for the requested scope:
     - **Member-only** (their own adult account): any authenticated user may
       request erasure of themselves.
     - **Child-profile erasure**: requester must hold `parent` or `guardian`
       in `child_relationships` for that child. A `relative`/`grandparent`/
       `supporter` may request erasure of *their own* contributions/memories
       but cannot unilaterally erase a child's profile.
     - **Whole-family erasure**: requires either (a) all active parents'
       consent, or (b) the sole remaining parent (a family being erased
       entirely has no "orphaned children" problem, but confirm there is no
       other parent who still wants the family to exist before deleting it).
   - **COUNSEL**: any request from someone other than the account holder
     asserting legal authority (subpoena, custody order, deceased user's
     estate) needs a lawyer's sign-off before the operator proceeds.
3. **Log the request immediately** using the template in §6, before doing
   anything else, so the clock (§6 timelines) starts accurately.

---

## 2. Scope decision tree

```
Who/what is being erased?
├─ A. One adult's own account, staying a member of families they don't own
│     → "Member-only erasure" (§3.A)
├─ B. One child's profile, requested by a parent/guardian of that child
│     → "Child-profile erasure" (§3.B)
│        (family and other children in it are untouched)
└─ C. An entire family (all children, all adults' membership in it)
      → "Whole-family erasure" (§3.C)
         (an adult's OTHER family memberships, if any, are untouched —
         erase per-family, not per-user-everywhere, unless the user
         explicitly also requested member-only erasure of themselves)
```

Combine as needed: e.g., a parent leaving one family (member-only in that
family) while the family and other children continue to exist; or a single-
child single-family household requesting C which also fully satisfies A/B for
everyone in it.

---

## 3. Table-by-table actions

Legend: **DELETE** = hard-delete the row(s). **ANONYMIZE** = keep the row
(legal/financial retention) but sever the identity link. **RETAIN** = keep
as-is under a stated legal basis. **MANUAL FK GAP** = no cascade exists in
the DB; you must delete/anonymize this table's rows for the subject
explicitly, in the order given, before/after the table it references.

### 3.A Member-only erasure (one adult leaves the platform; family continues)

Order matters — children/dependents of a row first, then the row itself.

| Table | Action | Notes |
|---|---|---|
| `notification_preferences` | DELETE (row for this `user_id`) | No content, but is PII-adjacent; simplest to remove |
| `password_resets` | DELETE (rows for this `user_id`) | Token hashes only, but tied to identity |
| `reactions`, `comments` (`user_id`) | **ANONYMIZE**: keep row (family history — others' reaction context). Comments have a `body` (free text) — if the requester wants their words removed too, DELETE the comment rows instead of anonymizing; confirm with requester which they want | |
| `capsule_release_votes` (`user_id`) | DELETE | No content beyond the vote itself; a capsule missing one vote reverts to needing a fresh vote from a live guardian |
| `call_participants`, `call_child_presence.marked_by`, `family_calls.started_by`, `planned_calls.set_by` | **MANUAL FK GAP — DELETE/reassign.** For an ended call, deleting the participant row is safe. For `started_by`/`set_by` on a still-relevant row, you cannot leave a dangling FK — either delete the row (if the call/plan is stale) or, if it must be kept, this is a code gap requiring a nullable/ON DELETE SET NULL migration (flag to eng; do not silently violate the constraint) | |
| `goals.created_by`, `time_capsules.created_by`, `legacy_items.created_by`, `vault_items.created_by`, `feed_events.actor_user_id` | **ANONYMIZE.** These are family history (memories, milestones) that other members and the child rely on. Keep the row; because the FK must stay valid, **tombstone the `users` row** (see below) rather than hard-deleting it, until nullable-FK migrations land | |
| `contributions.contributor_user_id`, `fund_nudges.user_id`, `premium_grants.granted_by_user_id`, `premium_gift_intents.gifter_user_id`, `family_subscriptions.owner_user_id` | **ANONYMIZE per the financial carve-out** (§3.D) — do not delete; decouple identity, keep the money row | |
| `child_relationships` (`user_id`) | DELETE | Removes their visibility into any child; matches "access scoping" principle |
| `family_members` (`user_id`) | Already `status='removed'` if they used leave/remove; if not, set it now | This alone is NOT erasure — it only stops future access |
| `users.avatar_media_id` media object | See §4 (media deletion) | |
| `users` row itself | **Tombstone, don't hard-delete, until FK gaps above are closed.** Null `email`, `password_hash` (or a random unusable hash), `stripe_customer_id` (after §5's Stripe step), `avatar_media_id`; set `display_name` to a generic label (e.g. "Former member"); disable login. Record in the erasure log that this is a tombstone, not a full delete, and why (dangling FKs from family-history rows that must keep an author reference) | GDPR permits pseudonymization in lieu of deletion where deletion would harm the rights of others (Art. 17(1) balanced against others' right to their own family history) |

### 3.B Child-profile erasure (one child, family continues)

Cascade order: leaf tables referencing the child first, then `children`
itself.

| Table | Action |
|---|---|
| `consent_records` (`child_id`) | Set `revoked_at = now()` on all open rows, then DELETE (no ongoing purpose once the child profile is gone) |
| `badges`, `goal_completions` (via `goals.child_id`), `goals` | DELETE all for this child |
| `time_capsules` (`child_id`), `capsule_release_votes` (via capsule ids) | DELETE. **Sealed capsules**: still delete — erasure overrides the "hidden until released" design; there is no third party relying on a sealed capsule surviving the child's erasure |
| `vault_items` (`child_id`) | DELETE rows; DELETE the referenced `media_objects` + underlying bytes (§4) |
| `feed_events` (`child_id`) | DELETE the child-scoped ones. For family-level events that merely *mention* the child: if the row is entirely about this child, delete it; if it's mixed, redact the child's name from `payload` (jsonb) rather than deleting a family-relevant event |
| `contributions` (`child_id`) | **ANONYMIZE per §3.D** — do not delete (financial linkage); the UI should stop displaying contribution history for a deleted child even though the ledger persists |
| `fund_ledger_entries` (via `fund_accounts.child_id`) | **RETAIN per §3.D**, append-only, never touched |
| `fund_accounts` (`child_id`) | **MANUAL FK GAP**: do not delete this row while `fund_ledger_entries` reference `account_id` — the account row must persist as the anchor for the retained ledger. See §3.D/§5 for the Stripe Connect account disposition. Mark it inactive in an admin note; do not blank `stripe_account_id` (needed for any future Stripe-side reconciliation) |
| `fund_nudges` (`child_id`) | DELETE — no retention need, not a financial record |
| `call_child_presence` (`child_id`) | **MANUAL FK GAP**: DELETE any rows for this child now (should already be ephemeral by design, but confirm) |
| `children.avatar_media_id` media object | Delete per §4 |
| `child_relationships` (`child_id`) | DELETE all |
| `children` row | DELETE |
| `anchor_ref` values in retained `fund_ledger_entries` | **No action needed** — by design these are hashes/proofs only, never the child's name or PII, so their survival alongside an anonymized ledger entry does not reintroduce personal data |

### 3.C Whole-family erasure

Run §3.B for every child in the family, then §3.A for every adult member
whose *only* family is this one (an adult in multiple families keeps their
`users` row and other memberships), then:

| Table | Action |
|---|---|
| `legacy_items` (`family_id`) | DELETE rows + referenced media (§4) — family-level archive has no purpose without the family |
| `feed_events` (`family_id`, not already handled per-child) | DELETE |
| `family_invites` (`family_id`) | DELETE (pending invites become meaningless) |
| `planned_calls`, `family_calls`, `call_participants` (`family_id` / via `call_id`) | **MANUAL FK GAP**: DELETE all, in order `call_child_presence` → `call_participants` → `family_calls` → `planned_calls` |
| `family_subscriptions`, `premium_grants` (`family_id`) | **RETAIN/ANONYMIZE per §3.D** — financial records; keep, decouple owner/gifter identity per the `*_user_id` handling in §3.A |
| `premium_gift_intents`, `premium_email_log` (`family_id`) | DELETE — non-financial staging/log data, no retention value (mirrors the existing 30-day admin prune for gift intents) |
| `family_members` (`family_id`) | DELETE all rows |
| `families` row | DELETE |

### 3.D Financial-records carve-out (applies across A/B/C)

Per `docs/data-model.md`'s "Premium data retention & erasure" section and the
`docs/deploy.md` hardening-backlog note, the following are **never
cascade-deleted** on an erasure request — they are retained under
**GDPR Art. 17(3)(b)** (compliance with a legal obligation — tax/accounting
retention for payment records) and **Art. 17(3)(e)** (establishment/defence
of legal claims, e.g. chargebacks):

- `contributions`
- `fund_ledger_entries` (already immutable/append-only by design)
- `family_subscriptions`
- `premium_grants`

**What "anonymize" means concretely for these rows:** the money fields
(amounts, currency, status, timestamps, Stripe ids) stay exactly as they are
— never edit financial facts. Only the *person link* is treated:

- Drop the erased user's `users.stripe_customer_id` when their `users` row
  is tombstoned (their own linkage is gone), but do **not** touch the
  Stripe-side transaction records (see §5).
- `premium_grants.message` / `premium_gift_intents.message` may name a child
  or contain personal text — clear to `NULL` (the admin-void path already
  does this automatically for voided grants; do it explicitly here too for
  any non-voided grant belonging to the erasure subject).
- The `*_user_id` FK values (`contributor_user_id`, `owner_user_id`,
  `granted_by_user_id`, `gifter_user_id`) point at a `users` row you are
  tombstoning, not deleting outright (§3.A) — so these FKs stay valid without
  a schema change. If a future account-deletion endpoint truly hard-deletes
  `users`, these FKs become another **MANUAL FK GAP**/migration item; note it
  in the automation backlog (§7).
- **COUNSEL — retention duration**: how long "the legal obligation runs"
  (typically 6–7 years for tax records in most US states / CRA in Canada /
  EU member-state equivalents) is jurisdiction-specific; a firm purge date
  for financial records must be set with counsel, since indefinite retention
  itself violates minimization once the legal basis lapses.

**COUNSEL** items flagged in `docs/deploy.md` that this runbook does not
resolve and must not be decided by the operator alone: money-transmission
posture (processor exemption / merchant-of-record status), disposition of
any legacy platform-held balance (pre-Connect contributions — escheatment
rules vary by state/province), "earmarked for the child" marketing language
versus actual legal custody (any future UTMA/529-style product is
lawyer-first, not an engineering decision).

---

## 4. Media (S3 / local disk) deletion

**What exists in code today:** `apps/api/app/services/storage.py` defines
`MediaStorage.delete(storage_key) -> None`, implemented for both backends:

- `LocalDiskStorage.delete`: `self._path(storage_key).unlink(missing_ok=True)`
  (dev only — files under `apps/api/var/media`).
- `S3MediaStorage.delete`: `self.client.delete_object(Bucket=self.bucket,
  Key=storage_key)` (prod — bucket name from the stack output
  `MediaBucketName`).

The S3 bucket (`infra/lib/futureroots-stack.ts`) has **no versioning
enabled** — `delete_object` is a genuine, permanent delete with no old
version left behind to separately purge.

**What does not exist:** anything that walks a child's/family's
`media_objects` and calls `delete()` for erasure. Today's only callers are
upload-rejection cleanup in `vault.py` — unrelated to erasure.

**Manual procedure per erasure:**

1. Query `media_objects` for every row scoped to the subject:
   `child_id = <child>` (vault media, child avatar), or `family_id =
   <family>` (legacy archive media), or `user_id = <user>` (adult avatar).
2. For each row, call `get_storage().delete(row.storage_key)` (a one-off
   Python invocation against the deployed environment is the only way to do
   this today — there is no admin endpoint). In prod this needs Lambda/VPC
   execution context or direct
   `aws s3api delete-object --bucket <MediaBucketName> --key <storage_key>`
   via the AWS CLI with appropriate credentials.
3. After the bytes are gone, delete the `media_objects` row (once dependents
   like `vault_items`/`children.avatar_media_id`/`legacy_items.media_id` are
   themselves being removed per §3).
4. **Order**: delete the referencing row (`vault_items`, `time_capsules`,
   `legacy_items`, `children.avatar_media_id`, `users.avatar_media_id`,
   `contributions.media_id`) before or atomically with the `media_objects`
   row, since `media_objects.id` is the FK target.
5. **Contribution video messages** (`contributions.media_id`): the
   contribution row itself is retained under the financial carve-out (§3.D),
   but the attached video/message media is personal content, not a financial
   fact — delete the media object and null `contributions.media_id` (a
   narrow, deliberate exception to "don't touch financial rows": you are
   editing a non-financial column on an otherwise-retained row).
6. Double-check no other `media_objects` row references the same
   `storage_key` before deleting bytes (`storage_key` is `unique`, so this
   is structurally guaranteed — one key, one owning row).

---

## 5. Stripe-side actions

Per `.claude/skills/stripe-integration/SKILL.md`, two independent Stripe
relationships can exist per adult/family:

1. **The Stripe Customer** (`users.stripe_customer_id`, one per adult,
   billing for Premium). On erasure of that adult:
   - Delete or anonymize the Customer object via the Stripe Dashboard/API
     (`stripe.Customer.delete(...)`). Note: no dedicated "delete customer"
     method exists in the `PaymentProvider` protocol today — a gap for §7.
   - **Stripe retains transaction/invoice records regardless of Customer
     deletion** (their own tax/regulatory obligation) — the Stripe-side
     mirror of our own §3.D retention; you cannot make Stripe forget a
     completed charge, and you should not try.
   - If there is a live subscription, cancel it first. For an erasure,
     `cancel_subscription_now` (exists in the protocol; currently used only
     by the double-subscribe guard) is a legitimate new call site — but
     confirm no other family member is relying on continued Premium coverage
     first, since `family_subscriptions` is family-level, not per-user.
2. **The Stripe Connect Express account** (`fund_accounts.stripe_account_id`,
   one per child, legally owned by the parent who did `setup_by` — **not
   owned by the platform**). On child-profile or whole-family erasure:
   - Do **not** delete the connected account's transaction history — same
     legal-obligation logic as above, and it is the parent's account, not
     ours to unilaterally erase.
   - The likely correct action is to **deauthorize/disconnect** the
     platform's relationship to the account (removes our platform's access
     without deleting the parent's own Stripe-held funds or history) rather
     than deleting the Express account outright. **COUNSEL**: confirm
     deauthorize (vs. instructing the parent to close their own Express
     account directly with Stripe) is the right posture, and confirm what
     happens to any **un-transferred balance** sitting in the connected
     account at deauthorize time — a live-money question, not a data
     question; decide before an operator acts on a real account.
3. Record every Stripe-side action (customer id acted on, account id
   deauthorized, ticket/support-case reference) in the erasure log (§6).

---

## 6. Timelines, confirmation, and log template

**Timeline (GDPR Art. 12(3)):** respond "without undue delay and in any
event within one month of receipt of the request." A further two months is
permitted for complex requests if the requester is informed within the first
month, with reasons. Given this is currently a fully manual process, budget
real calendar time accordingly — do not wait until day 29 to start.

**PIPEDA:** respond "as soon as possible, and in any event not later than
30 days" — practically the same clock; run both in parallel, don't treat
them as two separate timers.

**Confirmation to the requester** (send once complete): what was deleted,
what was anonymized and why (financial carve-out, with the Art. 17(3)(b)/(e)
citation), what could not be deleted due to a manual FK gap and what interim
mitigation was applied (e.g., tombstoning instead of hard-deleting a `users`
row), and a contact point for follow-up questions.

**Erasure log template** (keep these outside the production DB — e.g. a
restricted admin document/ticket system, not a table that would itself need
erasing later):

```
Erasure Request Log
--------------------
Request ID:            <uuid or ticket #>
Received at (UTC):     <timestamp>
Requester user_id:     <uuid>
Requester verified via:<method — session / email link / callback>
Requester standing:    <self | parent/guardian of child <id> | all-parent consent for family <id>>
Scope:                 <member-only | child-profile | whole-family>
Subject ids:            users: [...]  children: [...]  families: [...]
Tables hard-deleted:    <list>
Tables anonymized:      <list, with what was nulled/decoupled>
Tables retained (carve-out): <list, citing GDPR Art. 17(3)(b)/(e)>
Manual FK gaps hit:     <list — e.g. call_child_presence, fund_accounts>
Media objects deleted:  <count, storage_keys or a reference file>
Stripe actions taken:   <customer id / subscription id / connect account id + action + date>
Counsel consulted:      <yes/no — which item, outcome>
Completed at (UTC):     <timestamp>
Confirmation sent at:   <timestamp>
Operator:               <name/id>
```

---

## 7. Automation backlog — what a self-serve deletion endpoint must do

When `DELETE /users/me` (or equivalent) account-deletion /
`DELETE /families/{id}` endpoints are built, they must encode **exactly**
the manual procedure above, not a simplified version of it:

- [ ] Enforce the §1/§2 identity-and-standing checks server-side (require
      re-auth/step-up for a destructive action; verify `child_relationships`
      role for child-scoped requests; verify all-active-parent consent or
      sole-parent status for whole-family).
- [ ] Implement the §3.A/§3.B/§3.C table walks as a single transaction per
      scope, in the stated dependency order, rather than relying on DB
      cascade (either add `ON DELETE CASCADE` via migration for the tables
      where hard-delete is always correct — e.g. `child_relationships`,
      `capsule_release_votes`, `fund_nudges`, the four video-call tables —
      or keep the deletion explicit in application code; either is
      acceptable, but it must be **one or the other**, not silently neither,
      which is today's state).
- [ ] Implement the §3.D anonymize-not-delete path as a first-class code
      path (a `services/erasure.py` analogous to `services/premium.py`'s
      settlement-function pattern) so `contributions` /
      `fund_ledger_entries` / `family_subscriptions` / `premium_grants` are
      never in the generic delete loop.
- [ ] Implement the §3.A tombstone-not-delete path for `users` (or land the
      nullable-FK migrations that make hard-delete safe first — pick one and
      make it the enforced behavior, not a judgment call left to whoever
      writes the endpoint).
- [ ] Wire `handle_owner_departure` (`services/premium.py`) into the new
      endpoint(s), matching its wiring in `leave_family`/`remove_member`.
- [ ] Implement the §4 media walk as a service function
      (`erase_media_for(child_id=... | family_id=... | user_id=...)`) built
      on the existing `MediaStorage.delete()` primitive — the one piece of
      infrastructure that genuinely is ready today; it just needs a caller.
- [ ] Implement the §5 Stripe calls (`Customer.delete`/anonymize,
      subscription cancel-now, Connect deauthorize) behind the
      `PaymentProvider` abstraction, honoring the counsel-required decision
      points flagged there rather than making them a default behavior.
- [ ] Auto-generate the §6 log entry from the transaction (subject ids,
      tables touched, media keys deleted, Stripe calls made) instead of
      relying on an operator to fill it in by hand.
- [ ] Add a `consent_records.revoked_at` write as part of child-profile
      erasure (currently never written anywhere in the codebase — see §0).
- [ ] Add tests mirroring the money-path discipline already used for
      Premium/contributions (idempotent, verifiable, single writer) — an
      erasure endpoint is as consequential as a settlement path and should
      get the same rigor.
