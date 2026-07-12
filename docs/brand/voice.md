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
