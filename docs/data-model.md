# FutureRoots — Data Model (PostgreSQL)

Status: design phase. This is the target relational model for the MVP; tables land incrementally per the roadmap.

## Principles

- **Children are profiles, not accounts** — no credentials on `children`; all access flows through adult family members (COPPA).
- **The Family Graph is explicit** — adult↔child relationships are rows, not inferred, because relationship type (parent/grandparent/relative/guardian) drives permissions and product behavior.
- **Money is integer cents + currency**, and the future fund ledger is append-only.
- **Everything meaningful emits a feed event** — the Family Feed is a read model over domain activity.

## Entity overview

```
users ──< family_members >── families ──< children
  │                                          │
  └──────< child_relationships >─────────────┤   (parent/grandparent/relative/guardian per child)
                                             │
        vault_items · goals · contributions · fund_ledger_entries
        time_capsules · feed_events · legacy_items  ──── all hang off child or family
```

## Tables

### Identity & graph

**users** — authenticated adults
- `id` (uuid pk), `email` (unique), `display_name`, `auth_provider_sub` (Cognito sub, nullable in local dev), `created_at`

**families**
- `id`, `name`, `created_by` → users, `created_at`

**family_members** — adult membership in a family
- `id`, `family_id` → families, `user_id` → users, `role` (`parent | grandparent | relative | guardian`), `status` (`invited | active | removed`), `invited_by`, `joined_at`
- unique (`family_id`, `user_id`)

**family_invites**
- `id`, `family_id`, `email`, `role`, `token`, `invited_by`, `expires_at`, `accepted_at`

**children** — managed profiles, never authenticate
- `id`, `family_id`, `first_name`, `birthdate`, `avatar_media_id`, `created_by`, `created_at`

**child_relationships** — the Family Graph edges
- `id`, `child_id` → children, `user_id` → users, `relationship` (`parent | grandparent | relative | guardian`)
- unique (`child_id`, `user_id`)

**consent_records** — compliance is first-class
- `id`, `child_id`, `granted_by` → users (must hold `parent`/`guardian` relationship), `consent_type` (e.g. `profile_creation | media_storage | contributions`), `granted_at`, `revoked_at`

### Vault & memories

**media_objects** — one row per stored binary (S3 in prod, local disk in dev)
- `id`, `child_id` → children, `storage_key`, `content_type`, `byte_size`, `uploaded_by`, `status` (`pending | uploaded | deleted`), `created_at`
- media is child-scoped at creation so download access control follows the Family Graph, and uploaded media can never be attached to a different child's vault

**vault_items** — the child's lifetime vault
- `id`, `child_id`, `type` (`photo | video | voice | message | document | achievement`), `media_id` → media_objects (nullable for text), `title`, `body` (text messages/captions), `created_by`, `created_at`, `deleted_at`

**legacy_items** — family-level archive (heritage, not child-specific)
- `id`, `family_id`, `type` (`story | recipe | document | photo | wisdom`), `title`, `body`, `media_id`, `created_by`, `created_at`

### Feed

**feed_events** — private family timeline (read model)
- `id`, `family_id`, `child_id` (nullable), `type` (`milestone | achievement | contribution | memory_added | capsule_created | member_joined`), `actor_user_id`, `payload` (jsonb), `created_at`
- index (`family_id`, `created_at desc`)

### Achievement economy

**goals**
- `id`, `child_id`, `created_by`, `title`, `description`, `reward_type` (`cash | fund_contribution | badge | privilege`), `reward_amount_cents` (nullable), `currency`, `status` (`active | completed | archived`), `due_at`, `created_at`

**goal_completions**
- `id`, `goal_id`, `completed_at`, `verified_by` → users, `notes`
- completion triggers: feed event + reward (ledger entry or badge) + notifications

**badges**
- `id`, `child_id`, `label`, `icon`, `source_goal_id`, `awarded_at`

### Money

**contributions** — gifts and milestone contributions from family members
- `id`, `child_id`, `contributor_user_id`, `amount_cents`, `currency`, `fee_cents` (platform contribution fee), `message`, `media_id` (optional video message), `stripe_payment_intent_id`, `status` (`pending | succeeded | failed | refunded`), `trigger_feed_event_id` (the milestone that prompted it, nullable), `created_at`
- ledger entries are written **only** when a verified Stripe webhook marks it `succeeded`

**fund_accounts** — one per child
- `id`, `child_id` (unique), `currency`, `created_at`
- balance is always derived: `sum(fund_ledger_entries.amount_cents)`

**fund_ledger_entries** — append-only
- `id`, `account_id`, `amount_cents` (signed), `entry_type` (`contribution | goal_reward | adjustment`), `source_contribution_id` / `source_goal_completion_id` (nullable), `anchor_ref` (nullable — blockchain proof reference, invisible to users), `created_at`
- **no updates or deletes**; corrections are new compensating entries

### Time capsules

**time_capsules**
- `id`, `child_id`, `created_by`, `type` (`letter | audio | video`), `media_id`, `body`, `release_condition` (`age | date | milestone`), `release_age` / `release_date` / `release_milestone` (per condition), `status` (`sealed | released`), `released_at`, `created_at`
- sealed capsules are hidden from everyone except the creator until released

### Notifications

**notifications**
- `id`, `user_id`, `type`, `payload` (jsonb), `channel` (`email | in_app`), `sent_at`, `read_at`

## Access rules (enforced in the API layer)

- A user sees only families where they hold an active `family_members` row.
- Child data visibility requires a `child_relationships` row (any type); **writes** to child-critical data (goals, consent, profile) require `parent` or `guardian`.
- Grandparents/relatives can: view feed, add memories/messages, contribute, create time capsules — but not manage the child profile or goals.
- Sealed time capsules are visible only to their creator.

## Blockchain touchpoint

The only chain-aware column is `fund_ledger_entries.anchor_ref` (plus a future `anchors` table mapping refs to Base transactions). Anchors store **hashes/proofs only — never personal data** — so GDPR erasure remains possible. The MVP `AnchorService` is a stub.
