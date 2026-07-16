# FutureRoots Premium — copy deck

Status: **final, ready to paste** · Owner: brand-guardian
Sources: `docs/specs/premium.md` (flows, touchpoints), `docs/specs/premium-architecture.md` (§4 API, §8 web pages, `render_email` fields), `docs/brand/voice.md` (style rules).

Conventions:

- Placeholders use `{curlyBraces}`. Dates render long form: "March 12, 2027".
- Email fields map 1:1 to `render_email(preheader, greeting, paragraphs, highlight, cta_label/url, secondary_label/url, footnote)`. The sign-off ("With warmth, The FutureRoots team") is in the shared layout; do not repeat it in paragraphs.
- Every string below is em-dash-free and crypto-term-free by construction. Do not "fix" punctuation back toward the spec drafts (two spec strings contained em-dashes; they are rewritten here, which is intentional).
- Prices are static marketing strings. The app never computes them. Math behind the savings claim: 12 × $9.99 = $119.88; $119.88 − $99 = **$20.88** saved, which is a little more than two months at $9.99 ($19.98). "About 2 months free" is therefore honest and slightly modest.

---

## 1. Naming & framing (decisions)

| Decision | Choice |
|---|---|
| Product name | **FutureRoots Premium** on first mention per surface (page titles, email subjects on first reference, feed events). Plain **Premium** thereafter and in tight UI (pills, buttons, dialogs). Never "FR Premium", never "Premium+", never "Pro". |
| Badge text | **"Premium"** (amber pill) and **"Free"** (quiet neutral pill). One word each, no icons, no lock glyphs. |
| One-line value proposition | **"More room for your family's story. One membership covers everyone."** |
| Free-tier framing | Free is a full product, never a demo. Standard reassurance line: "Photos, voice notes, milestones, contributions, goals, capsules, and the archive stay free, always." Premium copy never implies Free families are missing the heart of FutureRoots. |
| Annual savings phrasing | **"Save $20.88 (about 2 months free)"** everywhere the claim appears. Never round the dollar figure; never claim exactly "2 months free". |
| Gift framing | "A year of Premium" is the unit. Always one-time, always no strings: "It never charges the parents, and it doesn't renew." Amounts appear in checkout, receipts, and plan cards, never on the feed. |
| Price style | UI cards and buttons: `$9.99/month`, `$99/year`. Prose and email: "$9.99 a month", "$99 a year", "$99, one time". |

### Feature bullets (canonical set, used on the upgrade page and anywhere benefits are listed)

1. **Video memories.** Save the recitals, first steps, and belly laughs, in the vault and on the feed.
2. **Family video calls.** See everyone's faces, from anywhere, and plan the next call together.
3. **And everything we add next.** Premium grows as FutureRoots grows.

---

## 2. Emails (8 touchpoints, Flow F)

### 2.1 Premium activated — to all active parents

| Field | Copy |
|---|---|
| Subject | `Welcome to FutureRoots Premium` |
| Preheader | `Video memories and family video calls are on for the whole family.` |
| Greeting | `Hi {parentName},` |

Paragraphs:

1. `Your family is now on FutureRoots Premium. Video memories and family video calls are ready for everyone, starting right now.`
2. Monthly: `Your plan is $9.99 a month and renews automatically on {renewalDate}. You can cancel anytime from your family's Plan settings, no questions asked.`
   Annual: `Your plan is $99 a year and renews automatically on {renewalDate}. You can cancel anytime from your family's Plan settings, no questions asked.`
3. `A lovely first step: share a video the whole family will smile at.`

- CTA: `Share your first video` → `/family/{id}/moments`
- Secondary link: `Manage your plan` → Plan section
- Footnote: `This email confirms your subscription. Receipts and payment details live in your family's Plan settings.`

### 2.2 Gift confirmation — to the gifter (doubles as receipt)

| Field | Copy |
|---|---|
| Subject | `Your gift to {theFamilyName} is live` |
| Preheader | `A year of FutureRoots Premium, from you. Thank you.` |

> `{theFamilyName}` is the family name run through the shared `family_phrase`
> helper: `"Smith"` → `the Smith family`, `"The Free Family"` → `The Free Family`
> (no doubled article, no doubled "family").
| Greeting | `Hi {gifterName},` |

Paragraphs:

1. `What a lovely thing to do. Your gift of one year of FutureRoots Premium is now live for {theFamilyName}, and they know it came from you.`
2. `All year long, the family can save video memories and gather for family video calls.`
3. `This was a one-time payment. Nothing renews, and no one will ever be charged when the year ends.`

Highlight (the receipt card):

```
One year of FutureRoots Premium for the {familyName} family
$99.00, paid once on {paymentDate}
Coverage: {startDate} to {endDate}
```

- CTA: `Visit the family feed` → `/family/{id}`
- Footnote: `Keep this email as your receipt.`

### 2.3 Gift received — to all active parents

| Field | Copy |
|---|---|
| Subject | `{gifterName} gave your family a year of Premium` |
| Preheader | `Twelve months of video memories and family calls, with love from {gifterName}.` |
| Greeting | `Hi {parentName},` |

Paragraphs:

1. `Wonderful news: {gifterName} just gave your family a full year of FutureRoots Premium. Video memories and family video calls are on for everyone, through {endDate}.`
2. `The gift is fully paid. It will never charge you, and it doesn't renew. When it ends, your family simply returns to the Free plan, and everything you've saved stays yours.`
3. Only when the family also has an active subscription: `Since your family already has a Premium plan, the gift stacks on after it, so you're covered through {combinedEndDate}. If you'd like, you can turn off your own renewal and let the gift carry you. You'll find that option in your family's Plan settings.`

Highlight, only when a gift message exists (message first, attribution on a new line):

```
“{message}”
{gifterName}
```

- CTA: `See it on the family feed` → `/family/{id}`

### 2.4 Payment failed — to the subscription owner only

Register: gentle, zero blame, zero alarm. The family is never told.

| Field | Copy |
|---|---|
| Subject | `A quick note about your Premium payment` |
| Preheader | `We'll retry automatically. Premium stays on for your family.` |
| Greeting | `Hi {ownerName},` |

Paragraphs:

1. `Your family's Premium payment of {amount} didn't go through this time. This happens: cards expire, banks get cautious. It's easy to sort out.`
2. `Nothing changes for your family right now. Premium stays fully on, and we'll retry the payment automatically over the next few days.`
3. `If your card has changed, you can update it in a minute on our secure billing page.`

- CTA: `Update payment details` → Billing Portal link
- Footnote: `If a retry goes through, you're all set and can safely ignore this email. We'll only write again if we still need you.`

### 2.5 Premium ended — to owner + all active parents

Register: reassurance first, features second. Shame-free; being on Free is a fine place to be.

| Field | Copy |
|---|---|
| Subject | `Your family is back on the Free plan` |
| Preheader | `Every photo, video, and memory is exactly where you left it.` |
| Greeting | `Hi {parentName},` |

Paragraphs:

1. `Your family's time on FutureRoots Premium has ended, and you're now on the Free plan.`
2. `First, the important part: everything you've saved stays yours. Every photo, milestone, contribution, and memory is safe, and every video you've already shared will always play and download just as before.`
3. `The Free plan still holds everything at the heart of FutureRoots: the family feed, photos and voice notes, milestones, contributions, goals, time capsules, and the family archive. Only new video uploads and family video calls wait for Premium.`
4. `Whenever you'd like those back, Premium is a minute away.`

- CTA: `Return to Premium` → `/family/{id}/premium`

### 2.6 Cancellation confirmed — to owner (+ other parents, same copy)

| Field | Copy |
|---|---|
| Subject | `Premium stays on until {endDate}` |
| Preheader | `Auto-renewal is off. Nothing else changes until then.` |
| Greeting | `Hi {parentName},` |

Paragraphs:

1. `As requested, your family's Premium plan is set to end on {endDate}. You won't be charged again.`
2. `Until then, nothing changes: videos, family calls, everything stays on. After {endDate} your family moves to the Free plan, and everything you've saved stays yours.`
3. `If you change your mind before {endDate}, you can resume with one tap. No new checkout, no interruption.`

- CTA: `Resume Premium` → Plan section
- Footnote: `This change was made from your family's Plan settings. Any parent in the family can manage the plan.`

### 2.7 Annual renewal reminder — to owner, ~7 days ahead (annual plans only)

Must plainly state price, date, and how to cancel (legally required in several states; also just good manners).

| Field | Copy |
|---|---|
| Subject | `Your FutureRoots Premium renews on {renewalDate}` |
| Preheader | `$99 for another year of family videos and calls. Nothing to do if that sounds right.` |
| Greeting | `Hi {ownerName},` |

Paragraphs:

1. `A friendly heads-up: your family's annual Premium plan renews on {renewalDate} for $99.`
2. `If you'd like to keep going, there's nothing to do. Video memories and family video calls continue without interruption.`
3. `If you'd rather not renew, you can cancel anytime before {renewalDate} from your family's Plan settings. Your family keeps Premium until then, and everything you've saved stays yours either way.`

- CTA: `Manage your plan` → Plan section

### 2.8 Gift ending soon — to all active parents, ~7 days before a grant lapses

Sent only when no active subscription continues coverage.

| Field | Copy |
|---|---|
| Subject | `{gifterName}'s gift of Premium ends on {endDate}` |
| Preheader | `One more week of Premium. Keep it going anytime, or let it rest.` |
| Greeting | `Hi {parentName},` |

Paragraphs:

1. `The year of FutureRoots Premium that {gifterName} gave your family ends on {endDate}. What a year of memories it has held.`
2. `If you'd like to keep saving videos and gathering for family calls, you can pick up right where the gift leaves off: $9.99 a month or $99 a year.`
3. `And if now isn't the time, that's completely fine. Everything you've saved stays yours on the Free plan, including every video.`

- CTA: `Keep Premium going` → `/family/{id}/premium`

---

## 3. Web UI copy

### 3.1 Upgrade page — `/family/[id]/premium` (plan picker)

- **Headline:** `FutureRoots Premium`
- **Subhead (value prop):** `More room for your family's story. One membership covers everyone.`
- **Benefits list:** the three canonical bullets from §1.
- **Free-tier reassurance line (below the bullets, muted):** `Photos, voice notes, milestones, contributions, goals, capsules, and the archive stay free, always.`

Plan cards (Annual preselected):

| | Annual (preselected) | Monthly |
|---|---|---|
| Card title | `Annual` | `Monthly` |
| Price | `$99/year` | `$9.99/month` |
| Badge on card | `Save $20.88 (about 2 months free)` | none |
| Card note | `Renews yearly. Cancel anytime.` | `Renews monthly. Cancel anytime.` |

- **CTA:** `Continue to secure checkout`
- **Fine print (under CTA):** `Your plan renews automatically until you cancel. Cancel anytime; your family keeps Premium until the end of the paid period.`
- **Already-Premium state (server 409 `already_premium`):** `Your family is already on Premium. There's nothing to buy twice.`
- **Checkout-cancelled return (`?canceled=1` banner):** `No problem. Everything you already love about FutureRoots stays free, and Premium will be right here if you ever want it.`

### 3.2 Gift page — `/family/[id]/premium/gift`

- **Headline:** `Give the {familyName} family a year of Premium`
- **Subhead:** `$99, one time. Twelve months of video memories and family video calls, from you.`
- **Explanation paragraph:** `Your gift is fully prepaid. It never charges the parents, it doesn't renew, and there's nothing for them to set up. The whole family gets Premium the moment your gift goes through, and they'll see it came from you.`
- **Message field label:** `Add a note the family will see`
- **Message field placeholder:** `For all the recital videos to come ♥`
- **Message helper text (char limit):** `Up to 500 characters. It appears on the family feed and in the parents' email.`
- **Already-Premium notice (shown before payment):** `This family already has Premium. Your gift will extend it by a full year, starting when their current coverage ends.`
- **CTA:** `Continue to payment`
- **Fine print (under CTA):** `One-time payment of $99. Nothing renews, and no one is charged later.`
- **Checkout-cancelled return (`?canceled=1` banner):** `No worries at all. The family is right here whenever you're ready, and so is the gift.`

### 3.3 Success pages

**Subscribe success** (`/family/[id]/premium/success`):

- Headline: `Welcome to Premium`
- Body: `Your family's videos start now. The whole family is in.`
- Buttons: `Share a video` → Moments · `Start a family call` → Video Call
- Webhook-pending state (poll/sync): `Finishing up. This takes a few seconds.`

**Gift success** (`/family/[id]/premium/gift/success`):

- Headline: `Your gift is on its way to the family feed ♥`
- Body: `The {familyName} family now has a full year of Premium, thanks to you. We've let the parents know, and your note is on the feed.` (Drop the final clause when no message was written: `We've let the parents know.`)
- Button: `See the family feed` → `/family/{id}`
- Webhook-pending state: `Finishing up. This takes a few seconds.`

### 3.4 Upsell component (`PremiumUpsell`) — invitation, never a wall

Shared modal/inline card. No lock icons, no greyed-out dead zones, no "you can't" phrasing.

**Variant: video upload** (Moments + vault memory form, when a free family picks a video file):

- Title: `Videos are part of FutureRoots Premium`
- Body: `Photos and voice notes are always free. Premium adds video memories and family video calls for the whole family, $9.99 a month or $99 a year.`

**Variant: family video call** (Start / Join / Schedule for free families):

- Title: `Family video calls are part of Premium`
- Body: `See everyone's faces, from anywhere. One membership covers the whole family, $9.99 a month or $99 a year.`

**Actions by role** (both variants):

- Parent: primary `Upgrade to Premium` → `/family/{id}/premium` · secondary `Maybe later` (dismiss)
- Non-parent: primary `Gift Premium to the family` → `/family/{id}/premium/gift` · secondary `Maybe later` (dismiss) · helper line under the buttons (plain text, sends nothing): `Or mention it to a parent. Upgrading takes about a minute.`

**API 402 fallback message** (server `premium_required` detail, normally never shown raw): `This is part of FutureRoots Premium.` (Confirmed brand-safe as-is.)

### 3.5 Plan section (`PlanSection`, family settings)

- **Section title:** `Plan`
- **Free state:** pill `Free` + `Everything at the heart of FutureRoots, free forever: photos, voice notes, milestones, contributions, goals, capsules, and the archive.`
  - Parent CTA: `Upgrade to Premium`
  - Non-parent CTA: `Give this family a year of Premium`
- **Premium state (subscription):** pill `Premium` + status line `FutureRoots Premium · {Monthly, $9.99/month | Annual, $99/year} · Renews {renewalDate}`
  - When `cancel_at_period_end`: `Premium until {endDate}. Auto-renewal is off.` + button `Resume Premium`
  - Resume confirmation toast: `Welcome back. Premium continues without interruption.`
- **Premium state (gift coverage):** grants list heading `Gifts` · each row: `A year of Premium from {gifterName}, {startDate} to {endDate}`
- **Owner-only billing entry:** button `Manage billing` · description `Update your card or view receipts on our secure billing page.`
- **Cancel button:** `Cancel Premium`
- **Cancel confirmation dialog** (honest and easy):
  - Title: `Cancel Premium?`
  - Body: `Premium stays on until {endDate}. After that your family is on the Free plan, and everything you've saved stays yours, including every video.`
  - Confirm: `Cancel Premium` · Dismiss: `Keep Premium`

### 3.6 Families-list badges (home page)

- Pill text: `Premium` / `Free` (see §1).
- Tooltip on `Premium`: `This family is on FutureRoots Premium.`
- Tooltip on `Free`, parent viewer: `On the Free plan. See what Premium adds.`
- Tooltip on `Free`, non-parent viewer: `On the Free plan. You can gift Premium anytime.`

---

## 4. Feed event strings

Feed events carry no amounts ("a year of Premium" is the unit of love) and are family-private.

**`premium_activated`** (actor: the subscribing parent):

```
The {familyName} family is now on FutureRoots Premium
```

**`premium_gifted`** (actor: the gifter):

- Headline: `{gifterName} gave the family a year of FutureRoots Premium ♥`
- With a message, the quote renders beneath the headline in the feed card:

```
“{message}”
```

- Without a message: headline only. Never render an empty quote block.

---

## Appendix: edge-case emails referenced by the architecture (§6/§7.3/§7.4)

Not in the 8-touchpoint table but required by the settlement service; copy provided so backend never improvises.

**A. Double-subscribe apology** — to the parent whose duplicate subscription was auto-cancelled and refunded:

- Subject: `One Premium plan was plenty (you weren't charged twice)`
- Preheader: `Two of you upgraded at the same moment. We've tidied it up.`
- Greeting: `Hi {parentName},`
- Paragraphs:
  1. `Great minds: another parent upgraded your family at the same moment you did. A family only ever needs one Premium plan, so we cancelled the second one and refunded your payment in full.`
  2. `Your family is fully on Premium, and there's nothing you need to do. The refund of {amount} will appear on your card within a few business days.`
- CTA: `See your family's plan` → Plan section

**B. Owner departure** — to remaining parents when the subscription owner leaves the family:

- Subject: `Premium stays on until {endDate}`
- Preheader: `The plan won't renew. Resubscribe anytime, in about a minute.`
- Greeting: `Hi {parentName},`
- Paragraphs:
  1. `{ownerName}, who managed your family's Premium plan, is no longer part of the family on FutureRoots, so the plan won't renew.`
  2. `Premium stays fully on until {endDate}. After that your family moves to the Free plan, and everything you've saved stays yours, including every video.`
  3. `Any parent can restart Premium anytime. It takes about a minute.`
- CTA: `Manage your plan` → Plan section
