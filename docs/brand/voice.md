# FutureRoots copy style reference

Working patterns for user-facing copy. Brand truth lives in `docs/vision.md`;
this file records concrete phrasing rules as they accumulate.

## Punctuation

### No em-dashes (hard rule, 2026-07)

Em-dashes (—) are banned in all user-facing text: UI strings, placeholders,
button labels, error messages, email subjects and bodies, page titles, and
metadata. Code comments, docstrings, docs, and tests are exempt.

Rewrite with whichever reads most naturally in the brand voice:

| Pattern | Before | After |
| --- | --- | --- |
| Appositive after a name | "Welcome to FutureRoots — your family's private space..." | "Welcome to FutureRoots, your family's private space..." |
| Examples in the middle of a sentence | "Set a goal — reading, chores, practice — and celebrate..." | "Set a goal (reading, chores, practice) and celebrate..." |
| Two-beat error message | "Something went wrong — please try again" | "Something went wrong. Please try again" |
| Introducing a list or elaboration | "...its first treasure — a recipe, a story..." | "...its first treasure: a recipe, a story..." |
| Announcement + payoff | "Wonderful news from your family — Emma just..." | "Wonderful news from your family: Emma just..." |
| Trailing afterthought | "...builds a future together — for the children you love" | "...builds a future together, for the children you love" |
| Title/tagline separator | "FutureRoots — Building Generational Wealth & Memories" | "FutureRoots: Building Generational Wealth & Memories" |

Also avoid the bare em-dash as an empty-value placeholder in the UI; use an
ellipsis (…) while a value is loading.

Watch the sentence that follows a split: if an interpolation fallback starts
the new sentence, capitalize it ("...today. {childName || \"They\"} will open
it years from now").

## Error messages

Two short beats: what happened, then the gentle next step. "The payment
didn't go through. Please try again." Never blame the user, never get
technical.

## Emotional register by surface

Match the feeling to the moment:

| Surface | Register | Example |
| --- | --- | --- |
| Milestone notification | Pride + invitation | "Emma just finished her first piano recital 🎹" |
| Contribution confirmation | Gratitude + legacy | "You just added to Emma's future" |
| Time capsule | Tenderness | "Only you can see it until the day it opens." |
| Goals | Encouragement, never pressure | "When they reach a goal" |
| Empty state | Gentle, inviting | "Be the first to say something kind." |

## Enum / option labels read as warm phrases, not form fields (2026-07)

When a dropdown or setting exposes a set of choices, keep the whole set in one
warm, parallel cadence. Avoid clinical noun phrases that read like a form field.

- Capsule "When should it open?" options:
  - ✅ "At an age" · "On a date" · "At a life moment" · "When they reach a goal"
  - ❌ "Specific goal completion" (cold noun phrase; breaks the pattern)
- Derived labels should match the same cadence:
  - ✅ "Opens when they reach '{goal}'"
  - ❌ "Opens when '{goal}' is completed" (transactional)

## Status labels are humane, not systemy

Prefer plain, kind words over technical states.

- Contribution statuses: "Given" · "Processing" · "Didn't go through" · "Refunded"
  (not "succeeded / failed / error"). "Didn't go through" is deliberately
  non-blaming.

## Naming people

- A supporter (coach, mentor, friend, neighbour) is a "trusted family friend,"
  never a "user" or "external party." Invite label that reads well:
  **"Supporter (coach, mentor, friend)"**.

## Email sign-off (use verbatim, every family email)

```
With warmth,
The FutureRoots team
```

## Quick self-check before shipping copy

1. Any em-dashes? Replace them (see the table above).
2. Any banned/technical vocabulary (wallet, token, crypto, blockchain, …)?
   Rewrite as "securely recorded" or drop it.
3. Does money talk about the child's future, not returns or yield?
4. Would this read warmly to a grandparent on their phone?
5. Do sibling labels share one cadence?
