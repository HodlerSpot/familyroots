# FutureRoots Mobile — Store Submission Runbook (Phase 6)

Operational guide for submitting the Expo iOS + Android apps. Companion to the
build plan (`.claude/plans/compressed-growing-sparrow.md`) and the mobile memory.
**Not legal advice** — the privacy-label mappings below reflect the app's actual
data practices; confirm against the *current* App Store / Play questionnaires
(they change) and your counsel before publishing.

App identity (already wired in `app.config.ts` / `eas.json`):
- Name **FutureRoots**, bundle/package **`com.futureroots.mobile`** (both platforms)
- Expo org **`futureroots-technologies-ltd`**, EAS project `5b375e7f-…`
- Apple Team **`LZ3T3RWRZ8`**, Apple Pay merchant `merchant.com.futureroots.mobile`
- Publisher **FutureRoots Technology Ltd.**, Winnipeg, Manitoba, Canada
- Support **support@futureroots.app**, Privacy **privacy@futureroots.app**
- Privacy Policy URL: **https://futureroots.app/privacy** · Terms: **https://futureroots.app/terms** *(publish `docs/legal/*` at these URLs first — see Prereqs)*

## 0. Positioning (drives both stores' questionnaires)

FutureRoots is a **private, adults-only family app**. **Users are 18+**; children
are **profiles managed by adults**, never account holders. Do **NOT** enrol in
Apple's **Kids Category** or Google Play's **"Designed for Families"** program —
those impose child-directed rules that don't fit (and would conflict with the
COPPA "children are not users" model). It is a **family/lifestyle** app.
Content is **private to a family** — no public feeds, no discovery, no ads, no
third-party tracking, no cross-family access. Zero crypto/blockchain references
anywhere in the listing or screenshots.

## 1. iOS App Privacy (App Store Connect → App Privacy)

**"Used to track you": NONE.** No cross-app/website tracking, no ad identifiers,
no data brokers.

**Data collected & Linked to the user** (all for **App Functionality** only —
never Tracking, never Third-Party Advertising):
| Category | Specific types | Notes |
|---|---|---|
| Contact Info | Name, Email address | account holders |
| User Content | Photos or Videos, Audio, Other user content (memories, messages, comments, predictions, milestones, capsules, legacy items) + child profile info (first name, birthdate, photo) entered by adults | private to the family |
| Identifiers | User ID; Device ID (Expo/APNs push token) | push token = App Functionality |
| Purchases | Purchase history (Premium subscription, Future Fund gifts) | **payment card data is collected by Stripe, not by the app** |
| Diagnostics | Crash data / performance (if you enable any) + minimal security logs | declare only what you actually collect |
| Usage Data | Product interaction (only if you add analytics — currently none) | omit if no analytics SDK |

- **Payment method / card numbers:** collected by **Stripe's** SDK, not stored by
  the app or our servers — declare under Stripe's SDK disclosure, not ours.
- **Location:** none collected by the app (no precise/coarse location APIs). IP at
  the network layer is not a declared App-Privacy type.

## 2. Android Data Safety (Play Console → App content → Data safety)

- **Data collected:** Personal info (name, email); Photos/videos; Audio; Files/docs;
  App activity (in-app content the user creates); Financial info = **"Purchase
  history"** (card data handled by Stripe, not collected by the app); Device IDs
  (push token). **Approximate/precise location: No.**
- **Data shared:** with **service providers** to run the app — AWS (hosting/storage),
  Stripe (payments), Amazon SES (email), Expo/Apple/Google (push delivery). These are
  processors acting on our instructions, **not** shared for their own use, **not**
  sold. Answer "Is data shared?" per Play's definition (transfer to third parties);
  most processor relationships are **"data processed by a service provider,"** not
  "shared" — verify each against Play's current definitions.
- **Security:** Data **encrypted in transit** (HTTPS/TLS): **Yes**. Encrypted at rest
  (AWS): yes.
- **Data deletion:** **Yes — users can request deletion.** The app has in-app
  **Settings → Your data → Delete my account** (`DELETE /me`, password step-up) and
  **privacy@futureroots.app**. Provide the deletion URL/instructions Play asks for.
- **Committed to Play Families Policy?** No — not a child-directed app (see §0).

## 3. Store listing copy (brand voice — warm, family-centered, no crypto)

- **App name:** FutureRoots
- **Subtitle (iOS, ≤30) / Short description (Android, ≤80):** "Your family's memories, milestones, and future — private and together."
- **Promotional text (iOS):** "Preserve the moments that matter, celebrate milestones, and build a child's future — all in one private family space."
- **Description (both):** *(draft — brand-guardian to finalize)*
  > FutureRoots is a private space for your whole family to preserve memories,
  > share wisdom, celebrate milestones, and build a child's future together.
  > Capture photos, videos, and voice notes into each child's vault. Cheer on
  > milestones. Seal time capsules to open years from now. Play the yearly family
  > predictions game. Contribute to a child's Future Fund. Gather everyone on a
  > family video call. Private by design — only your family, no ads, no public
  > profiles, ever.
- **Keywords (iOS, ≤100 chars):** family,memories,kids,milestones,vault,keepsake,journal,grandparents,legacy,album
- **Category:** Primary **Lifestyle** (alt: Social Networking is riskier re: UGC rules — prefer Lifestyle). Android: **Lifestyle** or **Parenting**.
- **Age rating:** target **4+ / Everyone**. BUT the app has **user-generated content** (photos/messages), so both stores' questionnaires will ask about UGC — answer honestly: content is **private to a family (not publicly shared)**, and there is an in-app **Report a problem** path. Apple requires UGC apps to have moderation/reporting/blocking; our private-family model + report flow + member removal covers this — describe it in the review notes.
- **Support URL:** https://futureroots.app (support@futureroots.app) · **Marketing URL:** https://futureroots.app
- **Screenshots:** capture from the dev/preview build — Home feed, a child vault, the contribute/celebrate flow, a capsule, a family video call. No crypto, no real children's PII (use seeded demo data).
- **App Review notes (iOS):** provide a **demo family login** (seeded account) so review can see the private family experience without creating data; explain children are profiles managed by adults (not users), and that payments use Stripe.

## 4. Credentials to upload (founder — secrets, never pasted into chat)

| Secret | Where it goes | Purpose |
|---|---|---|
| APNs key (.p8) | Expo project credentials (EAS prompts during iOS build) or expo.dev → credentials | iOS push |
| FCM v1 service-account JSON | Expo project → Android push credentials | Android push |
| Google Play service-account JSON | `eas submit` prompt / `eas.json` `submit.production.android.serviceAccountKeyPath` | Play upload |
| App Store Connect API key (.p8 + Key ID + Issuer ID) | `eas submit` prompt | App Store upload |
| `EXPO_ACCESS_TOKEN` | `infra/.env` → `push_secrets.ps1` → `futureroots/api` Secrets Manager | backend Expo Push sends |

## 5. Submission sequence

**Prereqs (do first):**
1. Publish the legal docs at `https://futureroots.app/privacy` and `/terms` (turn `docs/legal/*` into web routes, counsel-reviewed) — both stores require a reachable Privacy Policy URL.
2. Replace placeholder icon/splash with the finalized assets (Phase 6 asset task).
3. Finalize the demo/review account with seeded data.
4. SES is in sandbox — verify the review/demo email addresses, or note email is transactional-only.

**Build → internal test → submit:**
1. `eas build --profile production --platform android` and `--platform ios` (or promote the dev/preview builds). EAS manages signing.
2. **Android:** `eas submit --platform android` (uploads to Play) → Play Console → Internal testing track → add testers → validate on device → then Closed/Open testing → Production (staged rollout, e.g. 20%).
3. **iOS:** `eas submit --platform ios` → App Store Connect → TestFlight (internal testers) → validate → submit for App Review → phased release.
4. Fill **App Privacy** (§1) / **Data Safety** (§2), the **age rating** questionnaire (§3), and the listing (§3) in each console.
5. After first prod deploy of the API push change: confirm push end-to-end from a device (register token → trigger a notify() event → OS notification arrives).

## 6. Known items / follow-ups
- The workspace/`amplify.yml` change on `mobile/foundation` must be verified on an **Amplify preview branch before merging to `main`** (the web still builds green locally at every step).
- Invite share-sheet can't carry the tokenized link yet (InviteOut doesn't expose the token) — a future additive API change.
- Icon/splash may want a professional design pass before public launch.
- Confirm the Apple Pay **merchant ID** `merchant.com.futureroots.mobile` is registered in the Apple Developer account (Identifiers → Merchant IDs) for Apple Pay to work in Contribute.
