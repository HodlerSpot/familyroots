# Future Fund — real accounts (UX spec)

**Goal:** each child's Future Fund becomes a real bank-connected account. A parent sets it up once
via a FutureRoots-branded, Stripe-hosted page; after that, any family member or supporter gives by
card and the money lands in the account the parent chose. FutureRoots keeps a small fee equal to
card-processing cost; the net amount is always shown before paying.

**Personas:** parent (sets up, resumes, fixes), grandparent/supporter (gives — must stay under 60s),
guardian (sees status, can nudge). Children never see any of this directly.

**Vocabulary rules (all surfaces):** the account is always "{Name}'s Future Fund". Stripe may be
named exactly once per screen, only as "our secure payments partner, Stripe" / "secured by Stripe".
Never: Connect, Express, KYC, onboarding, payout, platform fee, connected account, verification
flow, crypto/wallet anything. Allowed honesty: "banks are required to verify who's opening the
account", "card processing".

**Fund states (drives every surface):** `none` → `setting-up` (started, incomplete) → `active`,
with `needs-attention` possible from `setting-up` (Stripe wants more info) or `active` (account
restricted later). Contributions are only possible in `active`.

---

## 1. Fund card on the child vault (parent/guardian column)

Same grid slot as today's 🌳 card. One primary action per state. All buttons full-width, ≥44px.

### (a) `none` — parent sees

```
+--------------------------------------------------+
| 🌳 Future fund                                   |
|                                                  |
| A real account in Maya's corner. Set it up once  |
| and every family gift lands there, safe until    |
| she's grown.                                     |
|                                                  |
| +----------------------------------------------+ |
| |        Set up Maya's Future Fund             | |  ← Button (primary)
| +----------------------------------------------+ |
|                                                  |
| About 5 minutes · secured by Stripe              |  ← text-xs stone-400
+--------------------------------------------------+
```

### (a) `none` — guardian (non-parent family member) sees

```
+--------------------------------------------------+
| 🌳 Future fund                                   |
|                                                  |
| Maya's Future Fund isn't set up yet. Ask         |
| Priya to set it up — then the whole family       |  ← "{a parent}" = first
| can start giving.                                |     parent's first name
|                                                  |
| +----------------------------------------------+ |
| |            💌  Let Priya know                | |  ← Button (soft), one tap
| +----------------------------------------------+ |
+--------------------------------------------------+

After tap (button swaps in place, aria-live="polite"):
| ✓  We let Priya know you're ready to give        |  ← emerald-800 text, no button
```

The nudge sends the parent a gentle in-app/email note: *"Rosa is ready to give to Maya's Future
Fund — set it up and the gifts can start."* One nudge per member per week (silently deduped;
the ✓ state always shows).

**Supporter view, `none` / `setting-up`:** the "Give a gift that grows" card stays, but the
contribute button is replaced by a calm line — no button, no error styling:

```
| 🌳 Give a gift that grows                        |
| Maya's family is getting her Future Fund ready.  |
| We'll be glad to see you back soon.              |
```

### (b) `setting-up` (started, incomplete) — parent sees

Gentle "needs attention" treatment: amber left border (`border-l-4 border-amber-400`),
`bg-amber-50/50`. Never red — nothing is wrong.

```
+--------------------------------------------------+
| 🌳 Future fund            ( ⏳ Almost there )    |  ← chip: amber-100 bg,
|                                                  |     amber-900 text
| You're partway through setting up Maya's         |
| Future Fund. Pick up right where you left off.   |
|                                                  |
| +----------------------------------------------+ |
| |             Finish setting up                | |  ← Button (primary),
| +----------------------------------------------+ |    resumes Stripe link
|                                                  |
| You'll finish on our secure payments partner,    |
| Stripe, then come right back.                    |
+--------------------------------------------------+
```

Guardians in `setting-up` see the same card minus the button: *"Priya is finishing the setup —
gifts open the moment it's done."*

**`needs-attention` variant** (Stripe requires more info, or an active account gets restricted):
same amber treatment, chip becomes `( ✋ Needs a quick check )`, body: *"Our payments partner
needs one more detail from you before gifts can continue. It usually takes a minute."* Button:
**See what's needed** (primary → resume link). If the fund was already active, the balance stays
visible above the notice — the money never "disappears."

### (c) `active` — unchanged from today

Balance + gift count + **Add to Maya's future** (primary). Optionally add the trust footer
`Gifts go straight to the account Maya's family chose` in text-xs stone-400 under the button.

---

## 2. Setup flow (parent) — intro before the redirect

**Route:** `/family/{id}/child/{childId}/fund/setup` · **Entry points:** fund card button, nudge
email link. Parents/guardians-with-manage only; anyone else → redirected to vault.
**Emotional beat:** stewardship and pride — "I'm opening the door for everyone else's love."

```
+----------------------------------------------------+
|                     [logo-mark]                     |
|                                                     |
|        Set up Maya's Future Fund                    |  ← h1, emerald-900
|   One-time setup, then anyone in the family         |
|   can give — grandparents included.                 |
|                                                     |
|  Have these ready:                                  |
|   🏦  The bank account where gifts should go        |
|       (your routing and account numbers)            |
|   🪪  A photo ID — banks are required to verify     |
|       who's opening the account                     |
|                                                     |
|  How it works:                                      |
|   1  You'll finish on our secure payments           |
|      partner, Stripe — about 5 minutes              |
|   2  Confirm your details and choose the bank       |
|      account gifts should land in                   |
|   3  Come right back here, and the giving begins    |
|                                                     |
|  +-----------------------------------------------+  |
|  |  Every gift goes straight to the account you  |  |  ← Card, emerald-50/50
|  |  choose. FutureRoots never holds Maya's money.|  |
|  +-----------------------------------------------+  |
|                                                     |
|  +-----------------------------------------------+  |
|  |          Continue to secure setup  →          |  |  ← Button (primary)
|  +-----------------------------------------------+  |
|                                                     |
|              Maybe later                            |  ← text link → back to vault
+----------------------------------------------------+
```

On "Continue": full redirect to the FutureRoots-branded Stripe-hosted page. Return URL comes back
to the return-landing below; the same URL serves as the refresh/resume link.

### Return landing — `/family/{id}/child/{childId}/fund/setup/return`

Polls fund status once on load; shows one of three cards. All three have exactly one button.

**Success:**
```
+----------------------------------------------+
|                    🎉                        |
|      Maya's Future Fund is ready             |
|                                              |
|  Gifts from the whole family now go          |
|  straight to the account you chose.          |
|                                              |
|  [        Add the first gift        ]        |  ← primary → contribute page
|                                              |
|         Back to Maya's vault                 |  ← text link
+----------------------------------------------+
```

**Still pending (Stripe reviewing):**
```
|                    🌱                        |
|        Almost there — just growing           |
|  Our payments partner is doing a final       |
|  review. This usually takes less than a      |
|  day, and we'll email you the moment         |
|  Maya's fund is ready.                       |
|  [       Back to Maya's vault       ]        |  ← primary
```
(While pending, the vault card shows the `setting-up` chip with body: *"All done on your end —
we're just waiting on a final review. We'll email you."* — no button.)

**Needs more info:**
```
|                    ✋                        |
|          One more thing needed               |
|  Our payments partner needs an extra         |
|  detail before Maya's fund can open —        |
|  it usually takes a minute.                  |
|  [        Finish setting up         ]        |  ← primary, resume link
|         Back to Maya's vault                 |  ← text link
```

**Abandoned mid-flow** (closed the Stripe tab): nothing breaks — the vault card is already in
`setting-up` state (1b), and its "Finish setting up" button mints a fresh resume link. A single
reminder email after 48h: *"Maya's Future Fund is almost ready — finish setting up in a few
minutes."* No further nagging.

---

## 3 & 4. Contribute page — transparency block

The amount step is unchanged (presets $10/$25/$50, custom, note). The transparency block lives on
the **payment step**, between the header and the PaymentElement, so the giver sees the net before
entering a card. Zero added taps — the grandparent flow stays ~4 taps + card entry, under 60s.

Presentation: not a table, no rules/borders — a soft emerald `Card` (`bg-emerald-50/50`,
`rounded-xl`) with three lines. The net line is the visual anchor (semibold, emerald-900,
largest). Fee math from engineering; wireframe uses $25.00 → $1.75 → $23.25.

```
+------------------------------------------------+
|              [logo-mark]                       |
|        $25.00 for Maya's future                |  ← h1 (unchanged)
|                                                |
|  +------------------------------------------+  |
|  |  Your gift                      $25.00   |  |  ← stone-700
|  |  Card processing                 $1.75   |  |  ← stone-500, smaller
|  |                                          |  |
|  |  🌳 Goes straight to Maya       $23.25   |  |  ← semibold emerald-900
|  |                                          |  |
|  |  FutureRoots keeps only what the card    |  |  ← text-xs stone-500
|  |  costs to process — the rest is all      |  |
|  |  Maya's.                                 |  |
|  +------------------------------------------+  |
|                                                |
|  [        Stripe PaymentElement         ]      |
|                                                |
|  [       Send $25.00 with love          ]      |  ← primary (charges gross)
|                                                |
|            ← Change amount                     |
+------------------------------------------------+
```

Rules:
- Amounts right-aligned with `tabular-nums`; base text ≥16px (fee line may be 14px, net line 18px+).
- No minus signs, no "fee" as a label, no strikethrough — "Card processing" is the honest name.
- The pay button always shows the **gross** (that's what the card is charged); the block makes the
  net unmissable above it. Screen-reader order matches visual order, so the net is announced
  before the pay button.
- **Success card** keeps the gross for the emotional beat, plus one honest line:
  *"You just added to Maya's future"* … *"$23.25 is on its way to her account, and your note is on
  her timeline for the whole family to see."* Feed/timeline continue to show the gift as $25.00
  (the gift is what the giver gave); the ledger detail records gross/fee/net.
- If the fund flips to non-active between steps (restriction race): replace the payment step with
  the paused card — *"Gifts to Maya are paused just now while her family updates a detail.
  Please try again soon."* + soft **Back to the vault** button. Never expose Stripe status words.

---

## 5. Admin / status surfacing

On the family detail page, child rows (parents/guardians only) get a small status chip after the
child's name — `none`: no chip · `setting-up`: amber "Fund: finishing setup" · `active`: emerald
"Fund active" · `needs-attention`: amber "✋ Fund needs attention" (links to resume) — and the
internal ops/admin view additionally shows the Stripe account id (`acct_…`) on the row; the
account id never appears in the family-facing UI.

---

## 6. Edge & error states (summary)

| Situation | Parent sees | Contributors see |
|---|---|---|
| Never started | Card 1a, "Set up …" | Guardian: ask/nudge card · Supporter: "getting ready" line |
| Abandoned mid-Stripe | Card 1b "Finish setting up" (fresh resume link); one 48h reminder email | Same as above |
| Stripe reviewing after submit | "Almost there" — no action, email on resolution | Same as above |
| Stripe needs more info | "Needs a quick check" chip + "See what's needed" | Same as above |
| Active account later restricted | Balance still shown + "Needs a quick check" notice + resume | "Gifts to Maya are paused just now — please try again soon" (calm, no error color) |
| Refunds | Unchanged visually — existing ledger/feed treatment | Unchanged |
| Redirect fails / link expired | ErrorNote on intro: "That link went stale — start again from Maya's vault" + button back | — |

---

## Copy table (canonical strings)

| Key | String |
|---|---|
| fund.none.parent.body | A real account in {name}'s corner. Set it up once and every family gift lands there, safe until {she/he/they}'s grown. |
| fund.none.parent.cta | Set up {name}'s Future Fund |
| fund.none.parent.footer | About 5 minutes · secured by Stripe |
| fund.none.guardian.body | {name}'s Future Fund isn't set up yet. Ask {parentName} to set it up — then the whole family can start giving. |
| fund.none.guardian.nudge | 💌 Let {parentName} know |
| fund.none.guardian.nudged | ✓ We let {parentName} know you're ready to give |
| fund.nudge.notification | {memberName} is ready to give to {name}'s Future Fund — set it up and the gifts can start. |
| fund.notready.supporter | {name}'s family is getting {her/his/their} Future Fund ready. We'll be glad to see you back soon. |
| fund.settingup.chip | ⏳ Almost there |
| fund.settingup.parent.body | You're partway through setting up {name}'s Future Fund. Pick up right where you left off. |
| fund.settingup.parent.cta | Finish setting up |
| fund.settingup.parent.footer | You'll finish on our secure payments partner, Stripe, then come right back. |
| fund.settingup.guardian.body | {parentName} is finishing the setup — gifts open the moment it's done. |
| fund.pending.parent.body | All done on your end — we're just waiting on a final review. We'll email you. |
| fund.attention.chip | ✋ Needs a quick check |
| fund.attention.parent.body | Our payments partner needs one more detail from you before gifts can continue. It usually takes a minute. |
| fund.attention.parent.cta | See what's needed |
| fund.active.footer | Gifts go straight to the account {name}'s family chose |
| setup.title | Set up {name}'s Future Fund |
| setup.subtitle | One-time setup, then anyone in the family can give — grandparents included. |
| setup.ready.bank | The bank account where gifts should go (your routing and account numbers) |
| setup.ready.id | A photo ID — banks are required to verify who's opening the account |
| setup.how.1 | You'll finish on our secure payments partner, Stripe — about 5 minutes |
| setup.how.2 | Confirm your details and choose the bank account gifts should land in |
| setup.how.3 | Come right back here, and the giving begins |
| setup.trust | Every gift goes straight to the account you choose. FutureRoots never holds {name}'s money. |
| setup.cta | Continue to secure setup → |
| setup.later | Maybe later |
| return.success.title | {name}'s Future Fund is ready 🎉 |
| return.success.body | Gifts from the whole family now go straight to the account you chose. |
| return.success.cta | Add the first gift |
| return.pending.title | Almost there — just growing |
| return.pending.body | Our payments partner is doing a final review. This usually takes less than a day, and we'll email you the moment {name}'s fund is ready. |
| return.info.title | One more thing needed |
| return.info.body | Our payments partner needs an extra detail before {name}'s fund can open — it usually takes a minute. |
| return.info.cta | Finish setting up |
| return.back | Back to {name}'s vault |
| pay.line.gift | Your gift |
| pay.line.processing | Card processing |
| pay.line.net | 🌳 Goes straight to {name} |
| pay.footnote | FutureRoots keeps only what the card costs to process — the rest is all {name}'s. |
| pay.paused | Gifts to {name} are paused just now while {her/his/their} family updates a detail. Please try again soon. |
| success.net | {net} is on its way to {her/his/their} account, and your note is on {name}'s timeline for the whole family to see. |
| email.reminder.48h | {name}'s Future Fund is almost ready — finish setting up in a few minutes. |
| error.stale_link | That link went stale — start again from {name}'s vault. |

---

## Accessibility & grandparent legibility

- Status chips always pair icon + words (⏳/✋ + text) — never color alone. Chip contrast:
  amber-900 on amber-100, emerald-800 on emerald-50 (both pass AA).
- All CTAs ≥44px tall, full-width on mobile; one primary action per card/screen in every state.
- Transparency block: base 16px+, `tabular-nums`, net line is the largest text in the block;
  reading order (gift → processing → net → pay button) identical for screen readers.
- Return-landing states each have a single `<h1>` and one button — safe at 200% zoom, no
  horizontal scroll (single-column max-w-lg card, same as contribute).
- Nudge confirmation uses `aria-live="polite"`; state changes never rely on toast-only feedback.
- Tap counts: grandparent contribute flow unchanged at **4 taps + card entry (< 60s)**; guardian
  nudge is **1 tap**; parent resume-setup is **1 tap** to re-enter Stripe.

**Handoff:** frontend-engineer needs `FundOut` extended with `account_status`
(`none | setting_up | active | needs_attention`) + `pending_review: bool`, endpoints for
create/resume setup link + return-status poll, fee preview (gross/fee/net) in the
create-contribution response, and the nudge endpoint. Exact fee math from engineering; design
locks only the presentation above.
