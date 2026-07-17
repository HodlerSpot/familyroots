# Future Predictions — implementation plan

Consolidated, actionable plan for the Future Predictions game. The two companion docs remain the deep
reference: `future-predictions.md` (product spec) and `future-predictions-architecture.md` (technical design).
**This plan is authoritative on the sealed-image format: it is a PNG rendered with Pillow** (superseding the
SVG approach in the architecture doc's §4 / §13.1 — see the banner at the top of that file).

## Context

A yearly, family-wide game tied to each child: family members **and supporters** predict the child's future in
short phrases; all predictions form a live **word cloud** viewable by everyone while the round is open. On the
child's birthday the round **seals** — the cloud is rendered to a keepsake image and preserved to open on the
child's **18th birthday** — and a fresh round opens. This repeats every year until 18, when all sealed years
release together as a chronological **"Book of Predictions"** (each year: the cloud image + the full attributed
list of who predicted what, when). Free feature; a decade-long family-graph engagement + retention hook.

Design decisions are locked in the two companion docs, both reviewed against the live codebase. The only change
this plan makes to them: **the sealed word-cloud image is a PNG rendered with Pillow, not SVG** (founder
preference for a real raster image; PNG over JPG because a word cloud is text on flat color, where JPEG
compression visibly degrades letter edges — PNG is lossless and crisp).

## Key design decisions

- **Two new tables, no TimeCapsule row.** The live round can't be a `TimeCapsule` (sealed capsules are
  creator-only-visible, which would let a parent peek and would fire N release events at 18 instead of one grand
  opening). New `prediction_rounds` + `predictions` tables own the whole lifecycle; round `status`
  (`open`/`sealed`/`skipped`) is the sole visibility authority. The birthday-sweep + lazy-on-read *pattern* and
  the `capsule_sealed`/`capsule_released` notification *kinds* are reused; no `time_capsules` write anywhere.
- **One prediction per member per round** (2–120 chars, editable/replaceable until seal; unique
  `(round_id, author_user_id)`). Authors edit/delete their own; parents/guardians may delete anyone's. Nothing
  is mutable after seal.
- **No peek after sealing** — sealed is sealed for everyone (including parents) until 18. Empty rounds are
  `skipped` (no image, no fanfare).
- **Word weighting, no AI** — lowercase, strip punctuation, drop stopwords + the child's first name; weight =
  number of distinct predictions containing the word; top 60; deterministic tie-break. One
  `services/predictions.py` tokenizer feeds both the live-cloud JSON (client-rendered for the open round) and
  the sealed PNG (server-rendered).
- **Supporters participate** — submit/view the open round via the `create_contribution` precedent
  (`get_child_with_access`, no `require_not_supporter`); never see the birthdate or seal date ("seals on
  {child}'s next birthday", no date/countdown/timestamps); sealed + released rounds are supporter-invisible;
  feed shows them `prediction_added` only.
- **Zero new NotificationKinds / no enum migration** — the seal task calls `notify()` with `capsule_sealed`; the
  18th-birthday release uses `capsule_released`. New `FeedEventType` values
  `prediction_added`/`predictions_sealed`/`predictions_released` are VARCHAR (no migration).
- **Free**, no Premium messaging.

## Sealed image: PNG via Pillow (the change from the architecture doc)

- **Dependency:** add `pillow` to `apps/api/pyproject.toml`. It publishes manylinux wheels, so it bundles through
  the existing `--only-binary :all:` cross-compiled Lambda packaging (`apps/api/scripts/package_lambda.ps1`)
  exactly like `cryptography`/`pywebpush` do today (~+3 MB; the ~54 MB zip stays within limits and deploys via
  S3 asset). This replaces the architecture doc's "no image library" rationale for SVG.
- **Font:** Lambda has no system fonts, so bundle one permissively-licensed TTF (e.g. an OFL font such as DejaVu
  Sans, or a brand face) under `apps/api/app/assets/fonts/` and load it with `ImageDraw.truetype(path, size)`.
  Confirm `package_lambda.ps1` includes `app/` assets in the zip; if it filters by extension, add `.ttf`.
- **Renderer** (`services/predictions.py`, `render_cloud_png(round, words) -> bytes`): a fixed-size RGB canvas
  (e.g. 1200×900) on a brand background; words placed largest-first, font size ∝ weight, 2–3 brand colors;
  **deterministic layout** via `random.Random(seed=str(round.id))` so re-running produces the identical image;
  child first name as a title and a footer "Sealed on her {N}th birthday · {YEAR} · {N} predictions"; **no
  author names on the image**. Export with `img.save(buf, format="PNG")`. Reuse the same `cloud_words(...)`
  weighting used by the live JSON. (Replaces the architecture doc's `render_cloud_svg` / §4 SVG layout; the
  deterministic-and-dependency-free requirement is dropped in favor of Pillow, which the founder accepted.)
- **Storage (net-new capability):** creating a `MediaObject` server-side is new. Add
  `put_object(storage_key, data, content_type)` to the `MediaStorage` protocol — implement on
  `LocalDiskStorage` (write bytes) and `S3MediaStorage` (`self.client.put_object`; the `s3:PutObject` grant
  already exists). The seal task creates the `MediaObject` row (`content_type="image/png"`, `child_id`,
  `uploaded_by=child.created_by` for provenance only, `byte_size`, `status=uploaded`). `download_media` serves
  `image/png` bytes to an `<img>` and gates access by the owning round's status (mirrors the sealed-capsule
  guard). No SVG anywhere.

## Workstreams (parallelizable; API contract frozen by the architecture doc)

**WS1 — Schema (backend).** `prediction_rounds` (child_id, sequence/year, opens_at, seals_on, status, unique
`(child_id, seals_on)`) + `predictions` (round_id, author_user_id, body ≤120, created_at, updated_at, unique
`(round_id, author_user_id)`); ONE Alembic migration off head `b8f2c1a9d4e7`. `FeedEventType` values added (no
migration). Extract the birthday helpers from `capsules.py` into `services/birthdays.py` and have capsules
import them (no duplication).

**WS2 — Predictions service + seal task (backend).** `services/predictions.py`: tokenizer/weighting
(`cloud_words`), `render_cloud_png`, and `seal_due_prediction_rounds(db)` — idempotent via compare-and-swap
(`UPDATE ... WHERE status='open'`) + the unique constraint; skip-if-empty; render PNG → `put_object` →
`MediaObject` → mark round sealed + link media → open next round → emit feed events → `notify(capsule_sealed)`;
post-commit `NotificationBatch.deliver`. Wire into `run_maintenance` AND lazily on the predictions read path
(shared function). Storage `put_object` additions.

**WS3 — API endpoints (backend).** Per the architecture contract: create/edit/delete prediction; get open round
+ cloud JSON + attributed list; member sealed-rounds summary; released "Book of Predictions" view. Role gates:
open-round submit/view allow supporters (no `require_not_supporter`); birthdate/seal-date stripped for
supporters; sealed/released member-only. `access.py` allowlist: supporters see `prediction_added`.

**WS4 — Web (frontend + ux-designer + brand-guardian).** Prediction composer (modeled on the `feed.tsx` comment
composer); **client-side live word cloud** rendered from the cloud JSON so the open round is always current;
sealed-round card near `CapsulesSection`; the Book-of-Predictions release view; placement on the child vault
page **including the supporter branch**. Copy from brand-guardian; the sealed keepsake PNG shown via `<img>`
from `download_media`.

**WS5 — Infra/packaging.** Confirm Pillow bundles via `package_lambda.ps1`; ensure the bundled `.ttf` ships in
the zip; verify zip size still deploys. No new AWS resources (reuses the daily EventBridge maintenance rule).

**WS6 — Tests + review.** Sweep idempotency (run twice → no double seal); birthday-today seeding; empty-round
skip; full supporter matrix (predict + see open cloud; never birthdate/seal-date/sealed/released);
one-prediction-per-member uniqueness + edit/replace; 18th-birthday finale (all sealed rounds release as the
Book); **PNG determinism** (same round id → byte-identical image) and that a real `image/png` `MediaObject` is
produced and served. Then a security + QA review pass — the seal task's exactly-once behavior and the
supporter/birthdate-leak matrix are the hard-verify items.

## Key files
- New: `apps/api/app/services/predictions.py`, `apps/api/app/services/birthdays.py`,
  `apps/api/app/assets/fonts/<font>.ttf`, one Alembic revision, `apps/api/tests/test_predictions.py`; web
  `apps/web/src/components/predictions/*` (composer, live cloud, sealed card, book view).
- Modified: `apps/api/app/models.py` (2 tables, `FeedEventType`), `apps/api/app/schemas.py`,
  `apps/api/app/routers/` (new predictions router + child-vault wiring), `apps/api/app/services/maintenance.py`
  (call the seal task), `apps/api/app/services/storage.py` (`put_object`), `apps/api/app/routers/vault.py`
  (`download_media` png + round-status guard), `apps/api/app/services/access.py` (supporter allowlist),
  `apps/api/pyproject.toml` (pillow), `apps/api/scripts/package_lambda.ps1` (font asset if needed),
  `apps/web/src/lib/api.ts`, `apps/web/src/app/family/[id]/child/[childId]/page.tsx`.
- Reuse: birthday helpers (moving to `services/birthdays.py`); the `create_contribution` supporter precedent;
  the `release_due_capsules` sweep+lazy pattern; `notify()` + `NotificationBatch` post-commit delivery; the
  `FundNudge` unique-constraint idempotency pattern; the `feed.tsx` comment composer.

## Verification
1. `uv run pytest` green (incl. new prediction tests) and `uv run alembic upgrade head`; `npm run build` green.
2. Local end-to-end: family + child; a member and a supporter each add a prediction → live cloud + list update;
   confirm the supporter sees the open cloud but `null` birthdate and no seal date. Set the child's birthdate
   month/day to today, run the maintenance sweep → round seals, a PNG `MediaObject` is generated and viewable
   via `<img>`, a new round opens, the sealed round is now hidden from everyone. Re-run the sweep → nothing
   double-seals. Seed a child turning 18 today → all sealed rounds release as the Book of Predictions.
3. Confirm the generated file is a valid **PNG** (`image/png`, opens as an image) and byte-deterministic per round.
4. Deploy note: after `cdk deploy`, force a Lambda cold start before verifying (warm containers serve stale code).

## Out of scope (MVP)
AI keyword extraction; reactions on predictions; editing after seal; cross-year comparison views; external
sharing/rasterization beyond the in-app PNG; JPG output (PNG chosen).
