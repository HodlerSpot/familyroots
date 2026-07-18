# Add Aunt / Uncle / Cousin family roles (inherit relative's permissions)

## Context

FutureRoots family members hold a role (`parent`, `grandparent`, `relative`, `guardian`, `supporter`). Families want more specific relationship labels for the "relative" tier — **Aunt, Uncle, Cousin** — without changing what those members can do. This adds the three as first-class `FamilyRole` values that are **permission-identical to `relative`**: full (non-supporter) family members who can view everything, add memories, contribute, and vote on capsule releases, but cannot manage child profiles, send invites, or manage billing.

## Why this is small and safe

Codebase review confirms **`relative` is never checked explicitly anywhere.** Every role gate is one of: `== supporter` / `!= supporter`, `in (parent, guardian)`, or `== parent`. A `relative` is simply "a member who is not a supporter and not a parent/guardian." So a new non-supporter role inherits relative's behavior automatically — **the only explicit list that enumerates the non-supporter roles is `GUARDIAN_ROLES`**, which must gain the three values. The role columns are `VARCHAR` (`native_enum=False`), so **no Alembic migration** is needed; the invite schema accepts any `FamilyRole`; and the web renders role labels with a CSS `capitalize` class, so "aunt" -> "Aunt" needs no label map.

## Changes (the complete set)

1. **`apps/api/app/models.py`** — add `aunt = "aunt"`, `uncle = "uncle"`, `cousin = "cousin"` to the `FamilyRole` enum (after `relative`, ~line 32).
2. **`apps/api/app/models.py` `GUARDIAN_ROLES` (lines 42-47)** — add the three values to this set. **This is the one critical edit**: it's an explicit enumeration ("everyone who is not a supporter"), and its two usages (`routers/capsules.py:80` and `:392`, the milestone-capsule release-vote gate) are how the new roles get relative's full-member trust. Missing this would silently deny them the capsule vote.
3. **`apps/web/src/lib/api.ts:3`** — extend the `FamilyRole` TS union with `"aunt" | "uncle" | "cousin"`.
4. **`apps/web/src/app/family/[id]/page.tsx` (~lines 531-535)** — add three `<option>`s (Aunt/Uncle/Cousin) to the invite role dropdown, grouped next to "Relative". The member-list role pill (`:230`, `capitalize {m.role}`) and the invite-preview page (`apps/web/src/app/invites/[token]/page.tsx:55`) already display any role string automatically.
5. **Tests** — see below.

**No changes needed** in `deps.py`, `services/access.py`, `services/notify.py`, `routers/{feed,vault,funds,premium,social,families,invites}.py`, or `schemas.py`: they are all supporter/parent/guardian-tier checks that treat any new non-supporter role exactly like `relative`. (Cosmetic only: `invites.py:73` scores testnet points specially for `grandparent`; new roles fall to the generic path — leave as-is.)

## Tests (`apps/api/tests`)

- Generalize the existing per-role helper (`make_grandparent` in `test_goals.py:4-18`, `make_supporter` in `test_supporter_access.py:9-22`) into a small `make_member(client, parent, family_id, role, email, name)` that runs the invite -> signup -> accept flow for any role.
- Add a **relative-parity matrix** for `aunt`/`uncle`/`cousin` (parametrized): each new role (a) passes `require_not_supporter` surfaces — funds/capsules/goals/legacy visible; (b) is denied `require_guardian_role` actions — cannot send an invite or create a child (403); (c) can vote to release a milestone capsule (`GUARDIAN_ROLES`); (d) gets the full, non-supporter feed and sees child birthdates; (e) an invite with the new role round-trips through preview/accept and sets `FamilyMember.role` + `ChildRelationship.relationship_type`. Mirror `test_invites.py` and `test_supporter_access.py` assertions.

## Verification
1. `uv run pytest` green (incl. the new parity tests); `uv run alembic check` reports no migration needed; `npm run build` + `tsc --noEmit` clean.
2. Local: invite someone as "Aunt" -> the option appears in the dropdown, the invite preview and member list show "Aunt", and after accepting, that member can open funds/capsules and vote on a milestone capsule, but the invite/add-child controls are absent/403 — identical to a "relative". Confirm a supporter still cannot do those things (no regression to the supporter tier).

## Out of scope
Any permission *difference* between the new roles and relative (they are intentionally identical); reordering or renaming existing roles; a central role->label helper (the `capitalize` class suffices); per-role iconography; changing `relative` itself.
