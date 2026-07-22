# Future Predictions — the family prediction game (Spec)

Status: **Scoped — ready to build** · Owner: PM · Fits: post-Phase-5 engagement (vision.md: Family Feed heartbeat + Legacy Time Capsules + Family Graph growth)

Future Predictions is a yearly game attached to every child profile. Family members **and supporters** write short predictions about the child's future ("astronaut", "she'll be the kindest person in any room", "world-champion whistler"). All predictions render live in a **word cloud** for that child. On the child's **birthday**, the round seals: the word cloud is rendered into an image and locked into a time capsule that opens on the child's **18th birthday** — along with the full attributed list of every prediction. A new round opens immediately and seals on the next birthday, every year until 18. On the 18th birthday, **every capsule opens at once**: the family's book of predictions, year by year.

Predictions are viewable by everyone in the game **while the round is open**. Once sealed, they vanish for everyone — parents included — until the 18th birthday. That's the magic.

This is a **free** feature. No video, no money, no Premium gating — it exists to pull the whole family (and supporters) back at least once a year.

---

## Key decisions (summary)

| Question | Decision |
|---|---|
| Prediction length | **2–120 characters**, plain text. Long enough for a sentence, short enough to stay cloud-friendly and skimmable in the list. |
| One or many per person per round | **One per member per round** (editable/replaceable until seal). One voice per person per year is the emotional unit ("what Grandma predicted the year you turned 8"), it keeps the cloud representative (nobody can flood it), and it makes weighting honest (word weight = how many *people* said it). Unique index enforces it. |
| Edit/delete | Authors edit or delete **their own** prediction any time while the round is open. **Parents/guardians** of the child can delete any prediction in an open round (moderation). **Nothing** is editable or deletable after seal (append-only history, like the ledger spirit). |
| Parental peek after seal | **No.** Sealed means sealed for everyone — parents, the author, everyone. (Admin erasure path excepted, for GDPR only.) The 10-year surprise is the product. |
| What feeds the cloud | **Simple word extraction, no AI**: lowercase, strip punctuation, drop a small stopword list. Weight = number of **distinct predictions** containing the word. Whole predictions live in the list panel next to the cloud. |
| Empty round on birthday | **Seal nothing** — no image, no capsule, no "sealed" fanfare. The round is marked `skipped` and the next round opens. An empty capsule at 18 is a sad artifact; a skipped year is invisible. |
| Notifications | **Zero new notification kinds** (new kinds cost 4 pref columns + copy each). Seal rides `capsule_sealed`, the 18th-birthday opening rides `capsule_released`. Individual predictions get a feed event only, no bell/email/push. |
| Supporters | May predict, edit/delete their own, and view the **open** round (cloud + list). They never see the seal **date** — only "seals on {child}'s next birthday." Sealed and opened capsules are **not** visible to supporters (consistent with the existing "supporters blocked from capsules" rule). |
| Premium | **Free for everyone.** It's an engagement and Family-Graph-growth loop with no storage-heavy media; gating it would starve the 18th-birthday payoff. No Premium messaging anywhere in the game. |
| Storage model | New tables `prediction_rounds` + `predictions` (not rows in `time_capsules` — see Data model rationale). Sealing reuses the capsule release pattern (lazy check on access + the daily maintenance sweep). |

---

## 1. Personas & user stories

- **Grandparent** — "As a grandparent, I want to write what I think Emma will become, see everyone else's guesses in a beautiful cloud, and know that on her 18th birthday she'll read that Grandma always said 'kind, stubborn, brilliant.'" (Bar: making a prediction is ~3 taps + typing — comfortably inside the 60-second discipline.)
- **Parent** — "As a parent, I want an easy yearly ritual around each birthday that pulls the whole family in, and I want to be able to quietly remove anything inappropriate before it's sealed forever."
- **Child** — Children are **profiles, not accounts**: the child never authenticates and has no game surface of their own. The payoff at 18 is delivered *to the family*, who share it with the (now adult) child. No new consent type is required: predictions are family-authored text about the child, covered by the existing `profile_creation` parental consent, same as memories and messages.
- **Extended family (relative/guardian)** — "As an aunt, I want to toss in a fun guess each year and watch the cloud grow — it's the lowest-effort way to be part of the story."
- **Supporter** — "As a family friend, I want to add my prediction and see the cloud, without gaining access to anything else about the child" (no birthdate, no funds, no capsules — existing supporter rules unchanged).

---

## 2. Data model (extends `docs/data-model.md`)

### New tables

**prediction_rounds** — one row per child per year of the game
- `id`, `child_id` → children, `opened_at`, `seals_on` (date — the child's next birthday; **server-only for supporters**, never serialized to them), `status` (`open | sealed | skipped | released`), `sealed_at`, `released_at`, `cloud_media_id` → media_objects (nullable; set at seal), `created_at`
- Partial unique index: **at most one `open` round per child.** Unique (`child_id`, `seals_on`).

**predictions** — one row per person per round
- `id`, `round_id` → prediction_rounds, `author_user_id` → users, `text` (varchar 120), `created_at`, `updated_at`
- Unique (`round_id`, `author_user_id`) — the one-per-person rule, enforced at the DB.
- Deletion (author self-delete or parent moderation) is a hard delete while the round is open; after seal the table is frozen (API refuses all writes to non-open rounds).

### Why not rows in `time_capsules`

`time_capsules` is creator-owned ("sealed capsules are visible only to their creator") and `created_by` is a user FK — a round is authored by the whole family and sealed by the system, so a capsule row would either leak the sealed body to a "creator" or need a fake system user. Instead, rounds **are** the capsules: `status = sealed` hides everything from everyone (which is exactly the founder rule), and release reuses the existing capsule release *pattern* — lazy check on access plus the daily EventBridge maintenance sweep — without touching the `time_capsules` table. The Time Capsules UI lists sealed rounds alongside real capsules as a read-model concern ("The family's predictions for Emma · 2027 — opens on her 18th birthday").

### Other touches

- `media_objects`: the rendered cloud image is a **system-generated, child-scoped** media object (PNG, rendered server-side at seal — deterministic layout, no AI, no external calls). `uploaded_by` is nullable-or-system for this row (architect to pick; flagged).
- `feed_events.type` gains three values (cheap enum/migration): `prediction_added`, `predictions_sealed`, `predictions_released`.
- **Feed payloads carry no prediction text** — only actor + child ("June added a prediction for Emma"). This keeps moderation/erasure simple (deleting a prediction never requires feed scrubbing) and keeps the feed a teaser that drives people to the live cloud.

### Access rules

- **View open round (cloud + list) and write/edit/delete own prediction:** any active family member with a `child_relationships` row to the child, **plus** active supporters of the family. This is the widest child-adjacent surface supporters get; it exposes prediction text + author display names + dates only.
- **Moderate (delete others' predictions in an open round):** `parent`/`guardian` relationship to the child.
- **Sealed rounds:** nobody sees text, list, or image. The round's *existence* + "opens on {child}'s 18th birthday" is visible to family members (like sealed capsules today). Supporters don't see sealed rounds at all.
- **Released rounds (at 18):** all family members with a relationship to the child. **Not supporters** (consistent with the capsule exclusion; their contribution was theirs to see while open).
- **Never, for supporters:** `seals_on`, `birthdate`, any countdown, any exact seal/release timestamp (see §7).

---

## 3. Flow A — The game loop (open round)

### Entry points

1. **Child page** (`/family/[id]/child/[childId]`): a "Future Predictions" card — live mini-cloud, "Add your prediction" button.
2. **Feed events**: `prediction_added` / `predictions_sealed` events link to the game.
3. Supporters: the same card on their supporter view of shared content (their scoped surface), minus dates.

### Making a prediction (screens & taps)

1. Child page → **Predictions card** → tap "Add your prediction". *(1 tap)*
2. One text field ("What do you predict for Emma?"), 2–120 chars, live counter. Type. *(typing)*
3. **Submit.** *(1 tap)* The cloud animates the new words in; the list shows "You — just now".

~2 taps + typing. If the member already has a prediction this round, the same control reads "Edit your prediction" and pre-fills their text (replace-in-place; `updated_at` bumps). Delete is a small "Remove" on their own list entry with one confirm.

### Viewing the open round

- **Word cloud** (top): rendered client-side from an API-computed `{word, weight}` payload (server does the tokenizing so family and supporters see the identical cloud and the client stays dumb). Capped at the top **60** words for legibility.
- **Contribution list** (below): every prediction in full — text, author display name, date added — newest first. Parents/guardians see a quiet "Remove" affordance on every row; everyone else only on their own.
- **Seal banner**: family members see "Seals on Emma's birthday — March 12" ; supporters see "Seals on Emma's next birthday" (no date, ever).

### Reads / writes

- Reads: `prediction_rounds` (open round for child), `predictions`, `child_relationships` / `family_members` (access + supporter check), `children` (first name; birthdate **only** for the family-facing banner).
- Writes: `predictions` (insert/update/delete), `feed_events` (`prediction_added` — on first submission only, not on edits; edits are not feed-worthy noise).

### Acceptance criteria

- [ ] Any active family member with a relationship to the child, and any active supporter of the family, can create exactly **one** prediction per round; a second create attempt from the same user updates-or-errors gracefully (client shows edit mode; API enforces the unique index).
- [ ] Text is validated server-side: 2–120 chars after trimming; empty/whitespace rejected with a friendly message; no HTML/markup rendered (plain text only, escaped everywhere).
- [ ] Author can edit and delete their own prediction while the round is `open`; both return 4xx (friendly domain error) once the round is anything else — including a race where the round seals mid-request (the write re-checks round status in the same transaction).
- [ ] Parent/guardian of the child can delete anyone's prediction in an open round; grandparents/relatives/supporters cannot delete others'. Moderation delete is silent in MVP (no notification to the author — deferred, see Out of scope).
- [ ] `prediction_added` feed event fires exactly once per author per round (first submit), never on edit; payload contains actor + child + round year, **never the prediction text**.
- [ ] Cloud payload and list are identical for family and supporters **except** all date-of-birth-derived fields (`seals_on`, banner date) are omitted for supporters.
- [ ] A user with no relationship to the child and no supporter membership gets a clean denial (no existence leak beyond the family's own surface).
- [ ] Grandparent path (child page → add → type → submit) is ≤ 3 taps + typing; no step mentions or requires anything Premium, and no crypto/Web3 terminology appears anywhere.

---

## 4. Flow B — Word cloud semantics & the sealed image

### Tokenization (MVP-simple, no AI)

1. Take every prediction in the round; lowercase; strip punctuation; split on whitespace.
2. Drop words in a small built-in English stopword list ("will", "be", "the", "a", "she", "he", "they", …) and drop the child's own first name (it would always win).
3. **Weight = number of distinct predictions containing the word** (per-prediction dedupe; with one prediction per person this equals "how many people said it"). Repeating a word inside your own prediction doesn't inflate it.
4. Deterministic ordering: weight desc, then alphabetical — the cloud is stable across reloads and identical for every viewer.
5. A prediction made entirely of stopwords still appears in the list; it just doesn't feed the cloud. If a round's cloud would be empty but predictions exist, fall back to using all words (stopwords included) rather than showing an empty cloud.

Bigrams/phrases ("prime minister"), multilingual stopwords, and AI keyword/theme extraction are all deferred (§9).

### The sealed image (rendered server-side at seal, PNG)

Must contain, and only contain:

- The word cloud (same top-60, deterministic layout — seeded by round id so re-renders are identical),
- The child's **first name** and round label: "The family's predictions for Emma",
- The **seal year** and count: "Sealed on her 8th birthday · 2027 · 14 predictions",
- A small FutureRoots wordmark.

No author names on the image (they live in the preserved list), no birthdate beyond what the label implies, and — as everywhere — no blockchain anything. The image is stored as a child-scoped `media_objects` row and referenced by `prediction_rounds.cloud_media_id`; access to it follows the round's status rules (i.e., effectively nobody until release).

### Acceptance criteria

- [ ] Same input predictions always produce the same weights, ordering, and rendered image bytes-stable layout (deterministic; testable).
- [ ] Child's first name and stopwords never appear in the cloud; per-prediction word dedupe verified.
- [ ] The live cloud and the sealed image use the same tokenizer (one implementation, two consumers).
- [ ] The sealed PNG renders correctly for rounds of 1 prediction and of 100+ predictions (cap at 60 words), and for 1-word and 120-char predictions.
- [ ] The image contains child first name, ordinal birthday, year, prediction count, wordmark — and nothing else.

---

## 5. Flow C — Sealing day, the new round, and the sealed years

### What happens on the birthday

Sealing runs via the existing two-path release pattern: the **daily maintenance sweep** (EventBridge) seals any open round whose `seals_on` ≤ today (UTC dates, matching capsule behavior), and a **lazy check on access** seals inline if someone loads the game first. On seal, in one transaction:

1. Round status → `sealed` (`sealed_at` set) — or → `skipped` if it has **zero predictions** (no image, no capsule, no fanfare; skipped years are simply absent from the book at 18).
2. If sealing: tokenizer runs, PNG renders, `media_objects` row + `cloud_media_id` written.
3. **The next round opens immediately** (`opened_at` = now, `seals_on` = next birthday) — unless this was the 18th-birthday seal (Flow D).
4. Feed: exactly **one** event per birthday — `predictions_sealed`, whose copy also announces the new round ("The family's 2027 predictions for Emma are sealed until she's 18 — a new round just opened. What do you predict?"). There is deliberately no separate `predictions_opened` event: when a round opens *without* a seal (first round ever, or after a skipped year) the round's presence on the child page is the invitation, and a standalone announcement would be feed noise. (So the earlier list of new feed types is exactly three: `prediction_added`, `predictions_sealed`, `predictions_released`.)
5. Notification: rides **`capsule_sealed`** (existing kind — audience: family members, supporters excluded, per the standing taxonomy) with prediction-specific copy doubling as the new-round invitation. No new `NotificationKind`.

Predictions submitted **on the birthday** land wherever the atomic status check puts them: before the seal transaction → sealed with the old round; after → they're the first entry of the new round. No prediction is ever lost or straddles rounds.

### While sealed (the quiet years)

- Family members see the sealed round as a locked entry: "2027 · sealed · opens on Emma's 18th birthday" — no cloud, no list, no count teaser beyond what the seal-day feed event said. **Parents cannot peek.** Recommendation confirmed: the decade of not-knowing is the feature; a peek path would also become the divorce/dispute lever nobody wants to build.
- Supporters see nothing of sealed rounds.
- The only read path into sealed content is the admin GDPR-erasure runbook (author asks for their words removed — see §8).

### Reads / writes

- Reads: `prediction_rounds`, `predictions`, `children.birthdate` (server-side seal computation only).
- Writes: `prediction_rounds` (status transitions), `media_objects` (cloud PNG), `feed_events` (`predictions_sealed`), `notifications` via `capsule_sealed`.

### Acceptance criteria

- [ ] Seal is idempotent and race-safe: sweep + lazy access + concurrent prediction writes produce exactly one sealed round, one image, one feed event, one notification batch (post-commit delivery, matching the `notify()` pattern).
- [ ] A zero-prediction round seals as `skipped`: no image, no `predictions_sealed` event, no notification; the next round still opens the same day.
- [ ] After seal, **no API response** to any non-admin caller — parent, guardian, author, anyone — contains sealed prediction text, author list, weights, or the image. (Test: parent of the child gets existence + open-at metadata only.)
- [ ] The new round opens in the same transaction as the seal; there is never a moment with no open round for an under-18 child with a birthdate (except post-18, Flow D).
- [ ] `capsule_sealed` notification respects existing preference columns and excludes supporters; copy passes brand-guardian review.

---

## 6. Flow D — The 18th birthday: final seal + grand opening

On the child's 18th birthday (same sweep/lazy trigger):

1. The final round (age 17→18) seals exactly like any other (or skips if empty).
2. **Every** `sealed` round for the child flips to `released` (`released_at` set) — all years at once.
3. **No new round opens.** The game is complete.

### The experience

- **"Emma's Book of Predictions"** — a dedicated view (`/family/[id]/child/[childId]/predictions`) that switches from "game mode" to "book mode": chronological chapters, one per year, each showing the sealed **cloud image** plus the full attributed **list** (text + author display name + date). Skipped years are silently absent. Warm framing throughout: "Ten years of the family imagining who you'd become."
- **Feed**: one `predictions_released` event ("A decade of predictions for Emma just opened ♥") — one event, not one per round.
- **Notification**: rides **`capsule_released`** (existing kind; audience parents/guardians per the standing taxonomy). The rest of the family catches it on the feed — this matches how capsule releases already work.
- The (now adult) child still has no account — the family opens the book *with* them. A future "hand the vault to the adult child" flow is a separate, existing roadmap concern, not this spec's.

### Acceptance criteria

- [ ] On the 18th-birthday trigger: final round seals, all sealed rounds release atomically, no new round opens, and subsequent prediction writes for this child return a friendly "Emma's book is complete" domain error.
- [ ] The book shows every non-skipped year in order with image + full attributed list; authors who have since left the family still appear by display name; erased authors appear as "A family member" (§8).
- [ ] A child who joined at 17 gets a one-chapter book: the round sealed on the 18th releases **immediately** (seal → release in one step, image still rendered) — the family sees it open the same day, not never.
- [ ] Exactly one `predictions_released` feed event and one `capsule_released` notification batch, replay-safe.
- [ ] Released content is visible to family members with a relationship to the child; **not** to supporters.

---

## 7. Flow E — Cadence, rollout & edge cases

| Case | Behavior |
|---|---|
| Child joins the platform at age 7 | Round 1 opens at child-profile creation (birthdate present): `opened_at = now`, `seals_on` = next birthday. Then yearly. First round may be short (e.g., 2 months) — fine. |
| Existing children at feature launch | Backfill migration opens round 1 for every child with a birthdate and age < 18. No feed spam: the backfill emits **no** feed events; discovery is the child-page card (first seal produces the first fanfare). |
| Prediction made ON the birthday | Atomic: lands in whichever round is `open` at write-commit time (see Flow C). Never lost. |
| Zero predictions in a round | Round → `skipped`; nothing sealed, nothing announced; next round opens. |
| Child turns 18 | Flow D: final seal + all-years release, game closes. |
| Child is already ≥ 18 at profile creation | Feature never activates for that child (no rounds, no card). |
| Leap-day birthday (Feb 29) | In non-leap years the birthday observes **March 1**: rounds seal Mar 1, and the 18th-birthday trigger uses the same rule. (Convention matches how banks/passports treat Feb 29; document in code next to the date math.) |
| No birthdate on file | Feature is **unavailable and invisible** for that child — no card, no rounds, for everyone (family included), so the absence itself can't signal anything to supporters. A parent/guardian adding a birthdate later opens round 1 at that moment. The child-profile form gets a gentle hint: "Add a birthdate to unlock the family prediction game." |
| Supporters & timing (birthdate protection) | Supporters never receive `seals_on`, a countdown, or seal/release timestamps; their banner says only "seals on Emma's next birthday." They get no seal-time notification or feed event (both already exclude supporters). Residual risk: a supporter polling daily could infer the seal day from the round flipping — accepted for MVP and mitigated by showing supporters no state-change timestamps (their view of a new round shows no "sealed on {date}" history at all — they only ever see the current open round). |
| Birthdate corrected mid-round | Parent edits birthdate → the open round's `seals_on` recomputes to the next occurrence of the new birthday. Sealed rounds are never retro-adjusted. |
| Author leaves the family / supporter removed | Their predictions **stand** (like memories and contributions); attribution keeps their display name. They lose access to view/edit the moment membership ends. |
| Author account erasure (GDPR) | **Intended:** attribution anonymized to "A family member" (achieved via the tombstoned `users.display_name`); text retained by default as family-vault content, with a specific request to delete the text honored too. |
| Child profile deleted | **Intended:** rounds, predictions, and cloud media for that child are hard-deleted, sealed or not (child erasure beats the seal, like the rest of the vault). |
| Family deleted | **Intended:** same for every child in the family. |
| Duplicate submit race (double-tap) | There is **no** `(round_id, author_user_id)` unique constraint (the design allows up to **3** predictions per author per round). The create endpoint enforces the ≤3 cap with an in-transaction count; a rare concurrent double-submit racing to a 4th row is an accepted minor over-count at this scale. `prediction_added` fires only on the author's first prediction in the round. |

> **Erasure status (corrected 2026-07-21).** The three erasure rows above are the **designed intent**, not current behavior. As of this writing there is **no automated deletion cascade, no admin read/write into sealed rounds, and no sealed-image re-render** in code — an earlier version of this table overstated that. Today erasure is a **manual** operator process (`docs/erasure-runbook.md`); child/family/author erasure of prediction rows + the keepsake `MediaObject` must be done by hand per that runbook. The automated path (including how these rows get folded into a cascade) is specified in `docs/specs/compliance-erasure-dsar-plan.md` and is gated on the counsel sign-offs listed there.

---

## 8. Emotional framing & touchpoints (summary)

| Moment | Feed event | Notification | Copy direction (brand voice) |
|---|---|---|---|
| First prediction by a member in a round | `prediction_added` (no text in payload) | none | "June added a prediction for Emma — what do you predict?" |
| Edit/delete own prediction | none | none | quiet |
| Round seals (non-empty) | `predictions_sealed` | `capsule_sealed` (existing kind; family, no supporters) | "14 predictions for Emma are sealed until she's 18. A new round just opened ♥" |
| Round skipped (empty) | none | none | silence — never guilt a family |
| 18th birthday grand opening | `predictions_released` (one event) | `capsule_released` (existing kind; parents/guardians) | "A decade of predictions for Emma just opened" |

Rationale for **no new `NotificationKind`**: each new kind costs 4 preference booleans, migration, prefs UI, and copy. The two moments that deserve an interrupt (seal, grand opening) map cleanly onto the capsule kinds' semantics and audiences; per-prediction interrupts would be noise the feed already carries better. If engagement data later says the seal-day invitation needs its own switch, adding a kind is a known, deferred cost.

---

## 9. Out of scope (MVP)

- **AI anything**: keyword/theme extraction, prediction prompts, "the family thinks you'll be…" summaries (Phase 6 candidates, API-model-based per vision).
- Reactions/comments on predictions; "prediction of the year" voting.
- Editing or deleting after seal (absolute; only the GDPR admin path touches sealed data).
- Notifying an author when a parent moderates their prediction away.
- Cross-year comparison views before 18 ("what did people say last year") — sealed means sealed.
- "Was Grandma right?" scoring, badges, or any achievement-economy tie-in.
- Bigrams/phrase extraction, multilingual stopword lists, custom cloud styles/colors/fonts.
- Multiple predictions per person per round; anonymous predictions.
- Milestone-based (non-birthday) rounds; custom round lengths; pausing the game.
- Printed/physical "Book of Predictions" (lovely future upsell; not now).
- A dedicated "new round opened" notification kind; supporter out-of-band notifications of any sort.
- Profanity filtering / automated moderation (parents moderate; revisit with scale).

---

## 10. Non-negotiables checklist

- **Zero crypto surface:** no chain involvement at all (no `anchor_ref`, nothing); no Web3/crypto terminology in any string, image, or email.
- **60-second flows:** grandparent adds a prediction in ~2–3 taps + one short text field — well under the bar.
- **Children are profiles, not accounts:** no child-facing surface; the 18th-birthday book is delivered to the family. No new consent type; existing `profile_creation` consent covers family-authored text about the child; parent/guardian moderation is the control surface. Access is scoped strictly by `child_relationships` + supporter rules.
- **Private by design:** everything is family-scoped; supporters get the narrowest possible slice (open round only, no dates); released books are family-only; nothing is ever public or cross-family.
- **Feed heartbeat:** predictions added, rounds sealed, and the grand opening all emit feed events. Deliberate exceptions: edits, empty-round skips, and backfill (noise/guilt avoidance — flagged as intentional).
- **Free feature:** no entitlement checks, no Premium pills, no upsell adjacency anywhere in the game.
