# FutureRoots Notifications — copy deck

Status: **final, ready to paste** · Owner: brand-guardian
Sources: `docs/brand/voice.md` (style rules), `docs/vision.md` (positioning), existing
notification copy in `apps/api/app/routers/{invites,vault,legacy,capsules,funds}.py`
and `apps/api/app/services/notifications.py` (tone + naming continuity).

Conventions:

- Placeholders use `{curlyBraces}`. Eleven notification kinds, using these exact
  keys throughout (match them in code): `call_live`, `contribution`,
  `fund_activated`, `capsule_sealed`, `capsule_released`, `announcement`,
  `new_member`, `milestone`, `memory`, `legacy`, `memory_request`.
- **Push and bell rows share one string.** Per the brief, the in-app bell row
  reuses the exact same title/body as the OS push notification, no separate
  "long" copy. Write for the lock screen; the bell gets the same result.
- **Character budgets are hard limits, not guidance:** push **title ≤ 50
  characters**, **body ≤ 120 characters**, both counted with placeholders
  filled in. Every string below is shown with a realistic filled example and
  its character count so engineers can spot-check.
- **Truncation rule:** when a *variable* (a person's name, a child's name, a
  parent-typed milestone/vault-item title) would push a string past budget,
  truncate that variable only, to the nearest word boundary, and append an
  ellipsis (`…`). Never truncate the fixed phrase around it, and never use an
  em-dash as a truncation mark.
- **No amounts, ever, on `contribution` pushes or bell rows.** This is a
  privacy rule, not a style preference: contributions can appear on a locked
  phone screen, and no one else's device should reveal what someone gave.
- Email fields map 1:1 to `render_email(preheader, greeting, paragraphs,
  cta_label/url)`, matching `docs/brand/premium-copy.md` §2. The sign-off
  ("With warmth, The FutureRoots team") lives in the shared layout; do not
  repeat it in paragraphs.
- Every string below is em-dash-free and free of banned vocabulary
  (wallet, seed phrase, gas, token, NFT, Web3, crypto, blockchain, on-chain,
  DeFi, mint) by construction.

---

## 1. Push / bell strings, all 11 kinds

| Kind | Title | Body | Tap opens | Register |
|---|---|---|---|---|
| `call_live` | `{starterName} started a family call` | `Tap in now. The family's together and would love to see you.` | The live call | Urgency + warmth |
| `contribution` | `{contributorName} just gave to {childName}'s Future Fund` | `Every gift adds up to something wonderful for {childName}.` | Child's fund/vault page | Gratitude + legacy (never the amount) |
| `fund_activated` | `{childName}'s Future Fund is ready for gifts` | `The whole family can start giving to {childName}'s future today.` | Child's fund page | Celebratory invitation |
| `capsule_sealed` | `{creatorName} sealed a time capsule for {childName}` | `A private message for {childName}'s future, safely tucked away until it's time.` | Child's vault (capsule stays locked) | Tenderness |
| `capsule_released` | `A time capsule for {childName} just opened` | `The moment has finally arrived. Open it together as a family.` | The opened capsule | Celebratory |
| `announcement` | Admin-authored, verbatim (see §1a) | Admin-authored, verbatim | Wherever the admin links to, or the family feed by default | Whatever the admin intends, brand-checked before send |
| `new_member` | `{memberName} joined the family` | `Say hello and give them a warm family welcome.` | Family page / member's profile | Pride + invitation |
| `milestone` | `{childName} just hit a milestone` | `{milestoneTitle}. Tap in to celebrate with the family.` | Child's vault, milestone open | Pride + invitation |
| `memory` | `A new memory for {childName}` | `Take a look: {itemTitle} just joined the vault.` | Child's vault | Warm, low-key |
| `legacy` | `A new story in the family archive` | `{itemTitle} just joined your family's legacy archive.` | Family legacy archive | Warm, low-key |
| `memory_request` | `Share a memory for {childName}` | `It's {childName}'s month. Add a memory to their vault?` | Child's vault | Gentle reminder + invitation (never pressure) |

Filled examples, with character counts, to confirm they fit:

- `call_live`: "Grandma Rose started a family call" (34) / "Tap in now. The family's together and would love to see you." (60)
- `contribution`: "Grandpa Joe just gave to Emma's Future Fund" (43) (typical names; see truncation rule for long ones) / "Every gift adds up to something wonderful for Emma." (52)
- `fund_activated`: "Emma's Future Fund is ready for gifts" (37) / "The whole family can start giving to Emma's future today." (58)
- `capsule_sealed`: "Grandma Rose sealed a time capsule for Emma" (43) / "A private message for Emma's future, safely tucked away until it's time." (73)
- `capsule_released`: "A time capsule for Emma just opened" (35) / "The moment has finally arrived. Open it together as a family." (63)
- `new_member`: "Aunt Carol joined the family" (28) / "Say hello and give them a warm family welcome." (47)
- `milestone`: "Emma just hit a milestone" (25) / "First piano recital. Tap in to celebrate with the family." (58)
- `memory`: "A new memory for Emma" (21) / "Take a look: Beach day photos just joined the vault." (52)
- `legacy`: "A new story in the family archive" (33) / "Grandma's apple pie recipe just joined your family's legacy archive." (69, tight; truncate the recipe title first if a longer one runs over)
- `memory_request`: "Share a memory for Emma" (23) / "It's Emma's month. Add a memory to their vault?" (47)

The `milestone` and `memory`/`legacy` bodies carry parent-typed free text
(`{milestoneTitle}` / `{itemTitle}`). Deliberately keep that text out of the
title (which has almost no character budget to spare) and give it the roomier
120-character body instead.

### 1a. `announcement` fallback / prefix convention

Admin broadcasts are authored, not templated: title and body are exactly what
the admin typed in the composer, sent verbatim. Two rules:

- **No auto-added prefix.** Never render `"FutureRoots: {title}"` or similar.
  The notification's own icon and sender name already read as FutureRoots;
  a text prefix is redundant and looks like spam.
- **Title is a required field**, enforced in the composer with the same
  50-character counter used above, so there is no legitimate "blank title"
  path in normal use. If a backend fallback is ever needed (a scheduled or
  system-triggered send with no admin-typed title), use:
  - Fallback title: `An update from FutureRoots`
  - Fallback body: `Tap to see what's new.`

---

## 2. New email copy

### 2.1 `fund_activated` (default: on)

Sent to active family members when a child's Future Fund finishes setup.

| Field | Copy |
|---|---|
| Subject | `{childName}'s Future Fund is ready for gifts` |
| Preheader | `Gifts can reach {childName} starting today.` |
| Greeting | `Hi {recipientName},` |

Paragraphs:

1. `Wonderful news: {childName}'s Future Fund is set up and ready. Gifts can reach {childName}'s future starting today.`
2. `Birthdays, holidays, or just because, any gift helps build something lasting for {childName}.`

- CTA: `Give to {childName}'s Future Fund` → `/family/{id}/child/{childId}/contribute`

### 2.2 `call_live` (default: off, exists as an option)

Register: honest that the call may already be over. Never oversell urgency in
an email, since email is inherently late.

| Field | Copy |
|---|---|
| Subject | `{starterName} started a family call` |
| Preheader | `The family gathered on a call. It might still be going.` |
| Greeting | `Hi {recipientName},` |

Paragraphs:

1. `{starterName} started a family video call a little while ago. By the time you read this, it may already be over, but if the family's still gathered, there's room for you too.`
2. `Either way, it's always lovely when everyone finds a moment to connect.`

- CTA: `Join if it's still going` → `/family/{id}`

### 2.3 `capsule_sealed` (default: off, gentle FYI)

| Field | Copy |
|---|---|
| Subject | `{creatorName} sealed a time capsule for {childName}` |
| Preheader | `A little something for {childName}'s future, safely tucked away.` |
| Greeting | `Hi {recipientName},` |

Paragraphs:

1. `{creatorName} just sealed a time capsule for {childName}. It's tucked away safely until it's time to open.`
2. `You won't see what's inside. That's part of the magic, but we thought you'd like to know it's there.`

- CTA: `See {childName}'s vault` → `/family/{id}/child/{childId}`

### 2.4 `memory_request` (default: on)

The monthly "add a memory" nudge for the family's rotating child of the month.
Reminder register: warm and low-pressure, never a chore. Sent by the daily
maintenance sweep, once per member per calendar month.

| Field | Copy |
|---|---|
| Subject | `Share a memory for {childName} this month` |
| Preheader | `Add a memory for {childName} this month.` |
| Greeting | `Hi {recipientName},` |

Paragraphs:

1. `This month, {childName} is your family's memory keeper. Is there a moment, a photo, or a few words you'd like to add to {childName}'s vault?`
2. `Even something small becomes part of the story {childName} will treasure one day.`

- CTA: `Add a memory for {childName}` → `/family/{id}/child/{childId}`

### 2.5 Unchanged (do not rewrite)

- `contribution` confirmation email: keep existing copy.
- `capsule_released` email: keep existing copy in `apps/api/app/routers/capsules.py`
  (`"A time capsule for {child.first_name} just opened"` / `"A moment years in
  the making..."`). It already matches this deck's voice.

---

## 3. Settings page copy

### 3.1 Section grouping (heading → kinds)

| Heading | Kinds |
|---|---|
| **Family moments** | `new_member`, `milestone`, `memory`, `legacy` |
| **Reminders** | `memory_request` |
| **Money & funds** | `contribution`, `fund_activated` |
| **Time capsules** | `capsule_sealed`, `capsule_released` |
| **Calls** | `call_live` |
| **From FutureRoots** | `announcement` |

### 3.2 One-line description per kind

| Kind | Description |
|---|---|
| `new_member` | When someone joins your family on FutureRoots. |
| `milestone` | When a child reaches a milestone worth celebrating. |
| `memory` | When a new photo, video, or memory is added to the vault. |
| `legacy` | When a new story or piece of wisdom joins your family's archive. |
| `memory_request` | A gentle monthly nudge to add a new memory for one of your children. |
| `contribution` | When someone gives to a child's Future Fund. |
| `fund_activated` | When a child's Future Fund is ready to receive gifts. |
| `capsule_sealed` | When someone seals a time capsule for a child. |
| `capsule_released` | When a time capsule opens. |
| `call_live` | When a family video call starts. |
| `announcement` | Occasional news and updates from the FutureRoots team. |

### 3.3 Column labels

Two columns per row: **Email** and **Push**. (Not "Notifications on/off" or
any systemy phrasing; the row description already says what it's for.)

### 3.4 "This browser" push-enrollment card

- **Enable CTA:** `Turn on push notifications on this browser`
- **Enabled confirmation:** `Push notifications are on for this browser.`
- **Browser-blocked help text:** `Notifications are blocked for FutureRoots in this browser. Look for a lock or bell icon next to the address bar to turn them back on.`

### 3.5 iOS instruction (polished)

`On iPhone and iPad, add FutureRoots to your Home Screen first: tap Share, then Add to Home Screen. Open FutureRoots from there to turn on push notifications.`

(Split into two sentences to drop the parenthetical from the draft, and to
keep each sentence short for the grandparent-facing register.)

### 3.6 Standing footer line

`No matter what's on or off above, you'll always find everything waiting for you in the app.`

(Slightly warmer expansion of the draft "You'll always see everything in the
app," placed once at the bottom of the whole settings page, not per section.)

---

## 4. Bell UI copy

- **Empty state:** `You're all caught up.` with a quiet secondary line beneath it: `New family moments will show up here.`
- **Read-all affordance:** label it `Mark all as read` (plain, no icon-only button; grandparents need the words).
- **Relative-time conventions**, oldest-safe fallback last:
  - Under 1 minute: `Just now`
  - Under 60 minutes: `{n}m ago`
  - Under 24 hours: `{n}h ago`
  - Yesterday: `Yesterday`
  - This past week: weekday name, e.g. `Monday`
  - Older, same year: short date, e.g. `Jul 10`
  - Older, past year: short date with year, e.g. `Jul 10, 2025`

---

## 5. Admin broadcast page copy

| Field | Copy |
|---|---|
| Title field label | `Title` |
| Body field label | `Message` |
| Push toggle | `Send as a push notification` |
| Email toggle | `Send as an email` |
| Dry-run button | `Check who this reaches` |

**Confirm dialog** (after dry-run, before sending):

- Title: `Send this to your families?`
- Body: `This reaches {pushCount} people by push and {emailCount} people by email. Once it sends, it can't be recalled.`
- Confirm: `Send now` · Dismiss: `Not yet`

**Caution note** (shown near the email toggle, always visible, not just on submit):

`Email can't be unsent once it goes out. Give it one more read before you send.`

---

## Naming decisions

- Eleven notification kind keys used consistently across push, bell, email, and
  settings copy: `call_live`, `contribution`, `fund_activated`,
  `capsule_sealed`, `capsule_released`, `announcement`, `new_member`,
  `milestone`, `memory`, `legacy`, `memory_request`.
- Settings grouping headings: "Family moments," "Reminders," "Money & funds,"
  "Time capsules," "Calls," "From FutureRoots."
- Bell read-all label: "Mark all as read." Bell empty state: "You're all
  caught up."
- Push/bell character budgets (50 title / 120 body) are treated as hard
  limits with a defined truncation rule (truncate the variable, not the
  fixed phrase; ellipsis, never an em-dash).
