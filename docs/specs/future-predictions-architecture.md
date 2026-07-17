# Future Predictions — Technical Architecture

> **⚠️ SUPERSEDED — sealed-image format (founder decision, 2026-07-17).** The sealed word-cloud image is a
> **PNG rendered with Pillow**, NOT the hand-built SVG described below. This changes: the "Sealed image format"
> row in §0, all of **§4** (`render_cloud_svg` → `render_cloud_png`, a Pillow raster-drawing routine with a
> bundled TTF font instead of an SVG string), the §5 `put_object` content-type default (`image/png`), §13.1's
> SVG-vs-PNG trade-off (PNG chosen; the "no image library" rationale no longer applies — `pillow` is added to
> `pyproject.toml` and bundles like `cryptography` via the `--only-binary :all:` Lambda packaging), and every
> other "SVG" mention in this file. **`docs/specs/future-predictions-plan.md` is authoritative on the image
> format and the Pillow/font/`put_object` specifics.** Everything else in this document (schema, tokenizer,
> seal task, API contract, supporter rules, notifications, workstreams) stands unchanged.

Status: **approved design — drives implementation** · Owner: Technical Architect
Product truth: `docs/specs/future-predictions.md` (locked — do not redesign flows here). Companion doc deltas (`docs/data-model.md`, `docs/architecture.md`) are itemized in §12 and land with workstream B1.

Future Predictions is a free, yearly game per child: family **and supporters** write one short prediction each, everyone watches a live word cloud, the round seals into an image on the child's birthday, and every sealed year opens at once on the 18th birthday. No money, no Premium gating, no chain involvement, no new notification kinds.

---

## 0. Key architecture decisions (summary)

| Decision | Choice |
|---|---|
| Storage model | New tables `prediction_rounds` + `predictions`. **No `time_capsules` rows anywhere in this feature** — the sealed snapshot is `prediction_rounds.status='sealed'` + `cloud_media_id`, released by our own (self-contained) due-check. Rationale + code evidence in §1.4. |
| Sealed image format | **Hand-built SVG** (`image/svg+xml`), rendered server-side by a deterministic, dependency-free layout algorithm (§4). No Pillow, no new packages — pyproject has zero image libs and Lambda packaging is `--only-binary :all:` cross-compiled; a C-extension is avoidable risk. Trade-off vs PNG in §13.1. |
| Server-generated media | Net-new capability: a `MediaObject` row created server-side with `status=uploaded`, `child_id` set, `uploaded_by = child.created_by` (provenance only — confers no read access; §5). New `MediaStorage.put_object()` method on both backends; the S3 impl is `s3:PutObject` (IAM already granted — `mediaBucket.grantPut(apiFn)`, `infra/lib/futureroots-stack.ts:200`). |
| Sealed-image access | New guard in `download_media` (`apps/api/app/routers/vault.py`) mirroring the sealed-capsule check at L248-257: media referenced by a **sealed** round is 404 for *everyone* — there is no creator exception because the system sealed it. Released rounds fall through to the existing child-scoped rules (family yes, supporters no). |
| Seal triggers | One idempotent `seal_due_prediction_rounds(db, ...)` shared by the daily maintenance sweep (EventBridge 09:00 UTC → `run_maintenance`) and a lazy check on game reads (the `release_due_capsules` pattern, capsules.py:181-211). Exactly-once via a compare-and-swap status UPDATE (`... WHERE status='open'`), not a log table (§6.2). |
| Birthday math | `_age_on` / `_birthday_at_age` are **moved out of `routers/capsules.py` (L46-55) into a new `app/services/birthdays.py`** (plus `next_birthday`); capsules.py imports them. Never duplicated. Feb-29 → Mar-1 rule rides along unchanged. |
| "Birthday" semantics | **UTC calendar dates**, matching capsule `release_date` behavior (`release_due_capsules` compares against `utcnow().date()`). `seals_on` is a `Date`; the round seals at the first trigger (sweep or lazy read) on/after that UTC date. Trade-off in §13.3. |
| Round lifecycle | Rounds are opened in three places, all idempotent under the one-open-per-child partial unique index: the Alembic backfill (existing children < 18), `create_child` (new profiles), and a lazy `ensure_open_round` on game reads (self-healing). |
| Feed | Three new `FeedEventType` values — `prediction_added`, `predictions_sealed`, `predictions_released`. VARCHAR(20) non-native enum ⇒ **no DDL** (`predictions_released` is exactly 20 chars — verified; anything longer would not fit). Payloads never contain prediction text. Supporters see **only `prediction_added`** (§8.2). |
| Notifications | Zero new `NotificationKind`s (spec decision). The seal task itself calls `notify(kind=NotificationKind.capsule_sealed, ...)` with prediction-specific copy; the 18th-birthday finale calls `notify(kind=NotificationKind.capsule_released, ...)` to parents/guardians. Post-commit `NotificationBatch.deliver(db)`, exactly like `release_due_capsules`. |
| Prediction column | The spec's `text` column is implemented as **`body` VARCHAR(120)** — codebase convention (`vault_items.body`, comments) and avoids shadowing `sqlalchemy.text`. Semantics unchanged. |
| Word cloud | One tokenizer (`services/predictions.py`) feeds both the live cloud JSON and the sealed SVG. The client renders the open round's cloud from API-computed `{word, weight}` (always current, client stays dumb); the SVG algorithm runs only at seal. |
| Serverless fit | Every side effect happens inside a request or the existing maintenance Lambda invocation. No new infra, no env vars, no cron beyond the existing rule. Cost impact ≈ $0. |

### 0.1 Rejected alternative: sealed snapshot as a `TimeCapsule` row

A design pass proposed materializing each sealed year as a real `TimeCapsule` (`release_condition=age, release_age=18`, `created_by` = a designated parent, `media_id` = the cloud image) to reuse `release_due_capsules` untouched. **Rejected — it breaks four locked spec criteria against current code:**

1. **Creator peek.** `_capsule_out` (capsules.py:61-62, 106-108) reveals `body`/`media_id` to the creator while sealed, and `download_media` (vault.py:256-257) lets the creator fetch sealed media. The designated parent could see the sealed cloud — spec Flow C: "no API response to any non-admin caller — parent, guardian, author, anyone".
2. **Creator early-open.** `release_capsule` (capsules.py:372-375) lets the creator open their own capsule at any time — the "divorce/dispute lever" the spec explicitly refuses to build.
3. **Fanfare shape.** `release_due_capsules` emits one `capsule_released` feed event + one notification batch **per capsule** (`_release`, capsules.py:116-178). Ten capsules at 18 ⇒ ten events/batches — spec Flow D requires exactly one `predictions_released` event and one batch.
4. **Attribution.** `_capsule_out` dereferences `capsule.author.display_name`; the family-authored, system-sealed round would surface as "sealed by {some parent}".

Special-casing all four in shared capsule code costs more than the self-contained release path in §6 (~30 lines) and pollutes the capsule module's invariants. The Time Capsules UI can still *list* sealed rounds alongside capsules as a pure read-model concern (§9).

---

## 1. Schema

One Alembic migration off HEAD **`b8f2c1a9d4e7`** (expanded_notifications): `e91c4a7d3b06_future_predictions.py`. All enums follow the existing `native_enum=False, length=20` pattern; all timestamps `DateTime(timezone=True)` via `utcnow`.

### 1.1 New enum

```python
class PredictionRoundStatus(str, enum.Enum):
    open = "open"
    sealed = "sealed"      # birthday passed, ≥1 prediction; hidden from everyone until 18
    skipped = "skipped"    # birthday passed, 0 predictions; invisible forever
    released = "released"  # 18th birthday: the book is open
```

### 1.2 `prediction_rounds` — one row per child per year of the game

```python
class PredictionRound(Base):
    """One year of the prediction game. Sealed rounds hide EVERYTHING from
    everyone (parents included) — the only sanctioned read into sealed data is
    the admin GDPR-erasure runbook. Status transitions are compare-and-swap
    (UPDATE ... WHERE status='open') so sweep + lazy reads never double-seal."""

    __tablename__ = "prediction_rounds"
    __table_args__ = (
        # Exactly-once per birthday: two rounds can never target the same date.
        UniqueConstraint("child_id", "seals_on", name="uq_prediction_rounds_child_date"),
        # At most one open round per child (double-open race guard; both
        # dialect kwargs so SQLite tests enforce the same partial semantics).
        Index(
            "uq_prediction_rounds_one_open",
            "child_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
        # Sweep scan: open rounds due on/before today.
        Index(
            "ix_prediction_rounds_due",
            "seals_on",
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"), index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # UTC date of the birthday this round seals on. SERVER-ONLY FOR SUPPORTERS:
    # never serialized to them, ever (it is birthdate-derived).
    seals_on: Mapped[date] = mapped_column(Date)
    status: Mapped[PredictionRoundStatus] = mapped_column(
        Enum(PredictionRoundStatus, native_enum=False, length=20),
        default=PredictionRoundStatus.open,
    )
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The rendered word-cloud SVG (system-generated media, §5). Set at seal;
    # NULL while open and forever for skipped rounds.
    cloud_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_objects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    child: Mapped[Child] = relationship()
    cloud_media: Mapped[MediaObject | None] = relationship()
```

No stored prediction count (derived; spec forbids a count teaser on sealed rounds anyway) and no denormalized "year" (it is `seals_on.year`).

### 1.3 `predictions` — one row per person per round

```python
class Prediction(Base):
    """One member's (or supporter's) prediction for one round. One per person
    per round, DB-enforced. Hard-deleted while the round is open (author
    self-delete or parent/guardian moderation); frozen once the round leaves
    'open' — the API refuses every write to non-open rounds."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("round_id", "author_user_id", name="uq_predictions_one_per_author"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("prediction_rounds.id"), index=True)
    author_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(String(120))   # 2–120 chars after trim, plain text
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    author: Mapped[User] = relationship()
```

Attribution survives membership loss (like memories/contributions): `author_user_id` stays; display name comes from the user row. GDPR-erased users surface as "A family member" via the existing user-anonymization path.

### 1.4 New feed event values (`FeedEventType`, models.py ~L82)

```python
    prediction_added = "prediction_added"          # 16 chars
    predictions_sealed = "predictions_sealed"      # 18 chars
    predictions_released = "predictions_released"  # 20 chars — VARCHAR(20) exact fit
```

Non-native enum ⇒ no migration DDL for these.

### 1.5 Migration contents (`e91c4a7d3b06`)

1. `create_table prediction_rounds` + `predictions` with the constraints/indexes above (hand-check the two partial indexes after `--autogenerate`).
2. **Backfill** (data migration, same revision): for every child with `_age_on(birthdate, today) < 18`, insert one `open` round with `opened_at = now`, `seals_on = next_birthday(birthdate, today)`. Children already ≥ 18 get nothing (feature never activates — spec Flow E). **No feed events, no notifications** — the migration inserts rows only; discovery is the child-page card. Date math is inlined in the migration (migrations never import app code).
3. Downgrade drops both tables.

Deletion cascade: child/family deletion is app-level in this codebase (no DB `ondelete`); the (future) child-deletion path must delete `predictions` → `prediction_rounds` → cloud `media_objects` + storage objects, sealed or not — child erasure beats the capsule, same as the rest of the vault. Noted in the data-model doc delta (§12).

---

## 2. Birthday helpers — `apps/api/app/services/birthdays.py` (new; extraction, not duplication)

Move `_age_on` and `_birthday_at_age` out of `routers/capsules.py:46-55` verbatim (public names), add the one new helper:

```python
def age_on(birthdate: date, on: date) -> int: ...           # ex _age_on — unchanged
def birthday_at_age(birthdate: date, age: int) -> date: ... # ex _birthday_at_age — Feb-29 → Mar-1, unchanged
def next_birthday(birthdate: date, today: date) -> date:
    """First birthday strictly AFTER today (a round opened ON the birthday
    seals next year — today's seal moment has already passed)."""
    return birthday_at_age(birthdate, age_on(birthdate, today) + 1)
```

`capsules.py` replaces its local defs with `from ..services.birthdays import age_on as _age_on, birthday_at_age as _birthday_at_age` — zero behavior change, existing capsule tests stay green.

---

## 3. Tokenizer & weighting — `apps/api/app/services/predictions.py`

One implementation, two consumers (live cloud JSON + sealed SVG). Pure functions, fully deterministic.

```python
CLOUD_WORD_LIMIT = 60

# Small built-in English stopword list (module-level frozenset, ~120 entries):
# articles/pronouns/auxiliaries/prepositions + future-tense fillers ("will",
# "gonna", "going", "she'll", "he'll", "they'll", "won't", "wont") — the exact
# list lives next to the code; multilingual lists are deferred (spec §9).
STOPWORDS: frozenset[str] = frozenset({...})

@dataclass(frozen=True)
class CloudWord:
    word: str
    weight: int

def tokenize(body: str) -> set[str]:
    """Normalized DISTINCT words of one prediction (the set() is the
    per-prediction dedupe — repeating a word inside your own prediction never
    inflates it). Rules, exactly:
      1. lowercase (str.lower);
      2. apostrophes (' and ') and hyphens are word-internal and kept; every
         other punctuation char (string.punctuation + “”‘’…–—) becomes a space;
      3. split on whitespace;
      4. strip leading/trailing apostrophes/hyphens from each token;
      5. drop tokens shorter than 2 chars."""

def cloud_words(
    bodies: list[str], *, child_first_name: str, limit: int = CLOUD_WORD_LIMIT
) -> list[CloudWord]:
    """Weight = number of distinct predictions whose token set contains the
    word. Drops STOPWORDS and the child's first name (casefold-compared; it
    would always win). Fallback (spec Flow B.5): if the filtered cloud is
    empty but bodies is not, recount with stopwords INCLUDED (the child's name
    stays excluded). Deterministic order: weight desc, then alphabetical.
    Returns at most `limit` words."""
```

Numbers ("2050") are kept — they are honest prediction words. A prediction made entirely of stopwords still appears in the list panel; it just doesn't feed the cloud.

---

## 4. The sealed image — deterministic hand-built SVG

```python
def render_cloud_svg(
    words: list[CloudWord], *, child_first_name: str, ordinal_age: int,
    year: int, prediction_count: int, seed: str,   # seed = str(round.id)
) -> bytes:
```

Contains, and only contains (spec Flow B): the cloud, the title, the seal line, the wordmark. **No pronouns** — `children` has no gender field, so the seal line uses the name, not the spec example's "her": `Sealed on Emma's 8th birthday · 2026 · 14 predictions` (brand-guardian confirms in F5).

### 4.1 Layout algorithm (concrete, deterministic)

- **Canvas** `viewBox="0 0 1200 900"`, background `#fafaf9` (stone-50) rounded rect. `font-family="Verdana, 'DejaVu Sans', sans-serif"` (stable, wide glyphs — safe with the width heuristic below).
- **Title** centered at y=84, 44px bold `#065f46` (emerald-800): `The family's predictions for {Name}`.
- **Footer** centered at y=856, 24px `#57534e`: the seal line; wordmark `FutureRoots` 20px semibold `#065f46` anchored `text-anchor="end"` at x=1160,y=856.
- **Cloud band** x∈[40,1160], y∈[140,780] (640px tall):
  1. Input order: `cloud_words` output (weight desc, alpha) — already deterministic.
  2. Font size: `w_min/w_max` over the input; `size(w) = 24 + round(60 * (w - w_min) / (w_max - w_min))` px (all-equal weights ⇒ 48px). Range 24–84.
  3. Width estimate (no text-measurement lib): `est_w = 0.62 * size * len(word) + 24` px padding — deliberately generous so overlap is impossible within a row.
  4. Greedy row packing in input order: append words to the current row until width would exceed 1120, then start a new row. Row height = `1.3 × max(size in row)`.
  5. If total height exceeds 640, drop the lowest-weight (last) word and repack — deterministic degrade, repeat until it fits.
  6. Aesthetics, still deterministic: `rng = random.Random(seed)`; shuffle word order **within each packed row** and pick each word's fill from the 3-color palette `["#065f46", "#b45309", "#44403c"]` via `rng.randrange(3)`. Same round id + same words ⇒ identical bytes.
  7. Rows are stacked top-down, each row horizontally centered; the whole block vertically centered in the band. Weight-8 words render 3.5× the size of weight-1 words — the cloud reads correctly even though placement is row-based rather than spiral.
- **Escaping**: every word and the child's name pass through `xml.sax.saxutils.escape` — prediction words are user-derived text going into XML. The SVG contains no `<script>`, no external refs, no event attributes; content is 100% server-composed.

Acceptance mapping: byte-stable for identical input (pure function of `(words, name, age, year, count, seed)`); handles 1 word and 60 words (packing degrades deterministically); a 120-char single-word prediction yields one long token that gets its own row at whatever size fits (est_w > 1120 at min size ⇒ clamp that word's size down so `est_w ≤ 1120` — one extra rule, deterministic).

---

## 5. Server-generated media (net-new capability)

### 5.1 Storage protocol extension (`apps/api/app/services/storage.py`, both impls)

`save()` keeps its meaning (client-push streaming, local backend only, S3 impl still raises). New method:

```python
class MediaStorage(Protocol):
    def put_object(self, storage_key: str, data: bytes, content_type: str) -> int:
        """Server-side write of generated bytes (e.g. the sealed cloud SVG).
        Returns byte size. Content type is load-bearing: browsers refuse SVG
        in <img> without image/svg+xml."""

# LocalDiskStorage: mkdir + path.write_bytes(data); return len(data).
# S3MediaStorage:  self.client.put_object(Bucket=self.bucket, Key=storage_key,
#                  Body=data, ContentType=content_type); return len(data).
```

IAM: already granted — `mediaBucket.grantPut(apiFn)` (`infra/lib/futureroots-stack.ts:200`). **No infra change.** The presigned-GET download path serves S3's stored ContentType, and `LocalDiskStorage.download` serves `media.content_type` — both render in `<img>`.

### 5.2 The media row

```python
def store_generated_media(
    db, *, child: Child, data: bytes, content_type: str = "image/svg+xml"
) -> MediaObject:
    """MediaObject(child_id=child.id, storage_key=str(uuid4()),
    content_type=content_type, byte_size=len(data),
    uploaded_by=child.created_by, status=MediaStatus.uploaded) + put_object.
    uploaded_by is NOT nullable (models.py:330) and stays that way:
    child.created_by is a real FK that always exists (the notify_fund_activated
    actor-fallback precedent). It is provenance only — read access to this
    media is governed by the ROUND's status (§5.3), never by uploaded_by."""
```

This resolves the spec's flagged "nullable-or-system" question: **keep NOT NULL, use `child.created_by`.**

### 5.3 `download_media` guard (`apps/api/app/routers/vault.py`, insert after the sealed-capsule block L248-257)

```python
# A sealed prediction round's cloud image is for NOBODY's eyes — the system
# sealed it; unlike capsules there is no creator exception. Released rounds
# fall through to the normal child-scoped rules below (family members may
# fetch; supporters may not — the image is neither an avatar nor a
# supporter-shared vault item, so the existing supporter branch already 404s).
sealed_round = (
    db.query(PredictionRound)
    .filter(
        PredictionRound.cloud_media_id == media.id,
        PredictionRound.status == PredictionRoundStatus.sealed,
    )
    .first()
)
if sealed_round is not None:
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
```

---

## 6. Round lifecycle service — `apps/api/app/services/predictions.py`

The only writer of `prediction_rounds` status transitions. Consumers: the game router (lazy), `run_maintenance` (sweep), `create_child` (round 1), the admin GDPR runbook (re-render).

### 6.1 Opening

```python
def ensure_open_round(db, child: Child) -> PredictionRound | None:
    """Idempotent, self-healing: if the child is under 18 (age_on(birthdate,
    utcnow().date()) < 18), has no open round, and has no released rounds (the
    game is not complete), open one: opened_at=now, seals_on=next_birthday(...).
    Returns the open round or None (18+ / complete). A concurrent double-open
    loses on uq_prediction_rounds_one_open — begin_nested() + rollback to the
    savepoint, then re-read."""
```

Call sites: game GET/PUT endpoints (§7), `create_child` in `routers/children.py` (round 1 at profile creation — birthdate is a required column today, so every new child gets one), and the migration backfill covers pre-existing children.

### 6.2 Sealing + the 18th-birthday finale

```python
def seal_due_prediction_rounds(
    db, *, child: Child | None = None
) -> tuple[dict[str, int], list[NotificationBatch]]:
    """Seal every open round with seals_on <= utcnow().date() — for one child
    (lazy read path) or globally (sweep). Idempotent and race-safe. Returns
    (counts, batches); THE CALLER COMMITS, THEN CALLS batch.deliver(db) for
    each batch — the release_due_capsules discipline (capsules.py:207-211)."""
```

Per due round, in the caller's transaction:

1. **Exactly-once guard (CAS).** `UPDATE prediction_rounds SET status=:new, sealed_at=:now WHERE id=:id AND status='open'` — check `rowcount`. Under READ COMMITTED a concurrent sweep/lazy racer blocks on the row lock, re-evaluates the WHERE, gets `rowcount=0`, and does nothing further. One sealed round, one image, one feed event, one batch — no log table needed (the row's own status is the ledger). `new` is `skipped` when the round has zero predictions, else `sealed`.
2. **Skipped** (empty): no image, no feed event, no notification — straight to step 5 (a skipped year is invisible; never guilt a family).
3. **Sealed** (non-empty): `cloud_words(bodies, child_first_name=...)` → `render_cloud_svg(..., seed=str(round.id))` → `store_generated_media` → `round.cloud_media_id`. Emit **one** `predictions_sealed` feed event — `actor_user_id=child.created_by` (system actions borrow the profile creator as actor, the `notify_fund_activated` precedent; the web renderer writes system-voice copy, §9.4), payload `{child_id, child_name, year, prediction_count}` — **never prediction text**. Stage the notification: `notify(kind=NotificationKind.capsule_sealed, recipients=family_recipients(db, child.family_id), ...)` — supporters excluded by default, nobody else excluded (no human sealer). Copy doubles as the new-round invitation ("14 predictions for Emma are sealed until she's 18 — a new round just opened. What do you predict?"); `url=f"/family/{fid}/child/{cid}"`; email builder included (`capsule_sealed` email prefs gate it per recipient).
4. **Final-round check.** `is_final = round.seals_on >= birthday_at_age(child.birthdate, 18)`. If final: flip **every** round of this child with `status='sealed'` (including the one just sealed — a child who joined at 17 gets seal→release in one step, image still rendered) to `released`, `released_at=now`, all in this same transaction. Emit **one** `predictions_released` feed event (actor `child.created_by`; payload `{child_id, child_name, years: n}`); stage **one** `notify(kind=NotificationKind.capsule_released, recipients=family_recipients(db, child.family_id, roles=[FamilyRole.parent, FamilyRole.guardian]), url=book_url)` — the standing capsule-released audience. **No new round opens. Ever again** (`ensure_open_round` guards on released-rounds-exist).
5. **Not final: open the next round** in the same transaction — `opened_at=now`, `seals_on=birthday_at_age(birthdate, sealed_age + 1)` where `sealed_age = age_on(birthdate, round.seals_on)`. Loop: if the platform was dark for >1 year the next round is also already due — it seals immediately as `skipped` (0 predictions) and the loop continues until `seals_on > today`. There is never a moment without an open round for an under-18 child, and no deliberately-empty capsules pile up.

Predictions submitted on the birthday land atomically: writes re-check `status='open'` inside their own transaction (§7), so a prediction commits into whichever round holds the status at its commit time. Nothing is lost or straddles rounds.

### 6.3 Sweep wiring (`apps/api/app/services/maintenance.py`)

At the top of `run_maintenance` (before the prune block, its own commit + delivery so notification batches follow the post-commit rule):

```python
prediction_counts, batches = seal_due_prediction_rounds(db)
db.commit()
for batch in batches:
    batch.deliver(db)
```

Counts merge into the returned dict as `prediction_rounds_sealed` / `prediction_rounds_skipped` / `prediction_rounds_released`. **Existing tests `tests/test_maintenance.py:150,163` assert exact dict equality — update the expected dicts.** No infra change: the EventBridge rule (stack:212-222) already invokes `{"futureroots_command": "maintenance"}` daily at 09:00 UTC.

### 6.4 Birthdate correction & GDPR hooks

- **Birthdate edited** (child-update endpoint in `routers/children.py`): recompute the open round's `seals_on = next_birthday(new_birthdate, today)`. Sealed/skipped rounds are never retro-adjusted. If the new date collides with `uq_prediction_rounds_child_date` (a past round already used it — only possible when the correction crosses an already-sealed boundary), keep the open round's old `seals_on` and log for admin; accepted micro-edge.
- **`rerender_round_cloud(db, round_id)`** — admin-only, for the GDPR erasure runbook: after an author's text is deleted from a sealed round, recompute `cloud_words` from surviving predictions and `put_object` the new SVG **over the same `storage_key`** (refs unchanged; S3 and local both overwrite in place). Zero-predictions-left flips the round to `skipped` and deletes the media. Exposed as a management command like `reconcile_contribution`.

---

## 7. API contract (frozen)

New router `apps/api/app/routers/predictions.py`, mounted in `app/main.py` like the others. Schemas in `schemas.py`. Every game read runs the lazy pair first: `seal_due_prediction_rounds(db, child=child)` (commit + deliver as in `list_capsules` → `release_due_capsules`) then `ensure_open_round(db, child)`.

| Method + path | Guard | Notes |
|---|---|---|
| `GET /children/{child_id}/predictions` | `get_child_with_access` — **supporters allowed** (the `create_contribution` precedent, contributions.py) | The game surface: open round + cloud + list. Supporter serialization strips every birthdate-derived field (§7.2). |
| `PUT /children/{child_id}/predictions/mine` | same — supporters allowed | Upsert: create my prediction or replace it in place (`updated_at` bumps). 2–120 chars after trim, plain text. Emits `prediction_added` **only on first create** (never on edit). 409 with friendly copy when no round is open (game complete: "Emma's book of predictions is complete"). |
| `DELETE /children/{child_id}/predictions/mine` | same — supporters allowed | Author self-delete (hard delete), open round only. 204. |
| `DELETE /predictions/{prediction_id}` | member of the child's family AND (author OR `membership.role ∈ {parent, guardian}` — i.e. `require_guardian_role`, deps.py:76, **not** `GUARDIAN_ROLES` which includes grandparents/relatives) | Moderation path. Silent (no notification to the author — spec Out of scope). 404 when the id/family doesn't match (no existence leak). |
| `GET /children/{child_id}/predictions/rounds` | member + `require_not_supporter` | Sealed years for the locked-entries UI. No counts, no content. |
| `GET /children/{child_id}/predictions/book` | member + `require_not_supporter` | The released Book of Predictions. Empty `chapters` until the 18th birthday. |

Write-path race rule: every mutation loads the round `WITH` a status re-check in its own transaction (`round.status == open` verified after any lazy seal ran); a round sealing mid-request turns the write into the friendly 409 ("These predictions are already sealed"). The upsert handles the double-tap race via `begin_nested()` + IntegrityError on `uq_predictions_one_per_author` → update-in-place, exactly one `prediction_added` event.

### 7.1 Schemas

```python
class CloudWordOut(BaseModel):
    word: str
    weight: int

class PredictionOut(BaseModel):
    id: uuid.UUID
    body: str
    author_name: str
    is_mine: bool
    can_delete: bool          # mine, or viewer is parent/guardian
    created_at: datetime

class OpenRoundOut(BaseModel):
    id: uuid.UUID
    year: int                              # seals_on.year
    seals_on: date | None                  # ALWAYS None for supporters
    cloud: list[CloudWordOut]              # server-tokenized; identical for every viewer
    predictions: list[PredictionOut]       # newest first — the list panel
    my_prediction_id: uuid.UUID | None

class PredictionGameOut(BaseModel):
    child_first_name: str
    round: OpenRoundOut | None             # None: game complete (family) or nothing to show (supporter)
    completed: bool                        # true only for family once released; ALWAYS false for supporters

class PredictionUpsertIn(BaseModel):
    body: str = Field(min_length=2, max_length=120)   # server trims first, then validates

class SealedRoundOut(BaseModel):
    id: uuid.UUID
    year: int
    sealed_at: datetime
    opens_on: date                         # the 18th birthday (family-facing; fine)

class BookPredictionOut(BaseModel):
    body: str
    author_name: str                       # erased users → "A family member"
    created_at: datetime

class BookChapterOut(BaseModel):
    round_id: uuid.UUID
    year: int
    age: int                               # ordinal birthday it sealed on
    cloud_media_id: uuid.UUID | None
    media_content_type: str | None         # "image/svg+xml"
    predictions: list[BookPredictionOut]

class PredictionBookOut(BaseModel):
    child_first_name: str
    chapters: list[BookChapterOut]         # chronological; skipped years silently absent
```

### 7.2 Supporter serialization rules (server-enforced, not client-trimmed)

- `seals_on` is set to `None` before serialization when `is_supporter(membership.role)` — the family banner date never reaches a supporter payload.
- Supporters get `completed=False` always and `round=None` when nothing is open — indistinguishable from "feature idle", no state-change history, no timestamps of transitions (their `OpenRoundOut` has `created_at` per prediction only, which they can already see in the list).
- `/rounds` and `/book` are `require_not_supporter` (403 with the standing "shared with family members only" copy).
- Everything else in the open-round payload (cloud, list, author names, dates added) is identical for family and supporters — spec acceptance Flow A.

### 7.3 What each page fetches

- **Child vault page (family):** `GET /children/{id}/predictions` + `GET .../predictions/rounds` (locked-years strip) — added to the existing non-supporter `Promise.all` (page.tsx:69-74). After release: the card links to the book.
- **Child vault page (supporter):** `GET /children/{id}/predictions` only.
- **Book page:** `GET /children/{id}/predictions/book`.

---

## 8. Feed, access & notifications

### 8.1 Feed events

| Moment | Event | Actor | Payload (never any prediction text) |
|---|---|---|---|
| First submit by a user in a round | `prediction_added` | the author | `{child_id, child_name, year}` |
| Round seals (non-empty) | `predictions_sealed` | `child.created_by` (system) | `{child_id, child_name, year, prediction_count}` |
| 18th birthday | `predictions_released` (exactly one) | `child.created_by` (system) | `{child_id, child_name, years}` |

Edits, self-deletes, moderation deletes, skipped rounds, and the backfill emit **nothing** (deliberate — spec §10). No testnet `_TESTNET_ACTIONS` mapping (out of scope). Because payloads carry no text, moderation/erasure never requires feed scrubbing.

### 8.2 Supporter feed visibility (`apps/api/app/services/access.py`)

The spec grants supporters the **open-round surface**; a `prediction_added` event exposes exactly that surface (actor display name + child first name — both already on the supporter's open-round list) and drives the engagement loop the feature exists for. The seal/release events are family-only fanfare and stay invisible (spec §7: supporters get no state-change signals).

```python
# Plain event types every member INCLUDING supporters may see (no vault-item
# indirection): open-round prediction activity only. Seal/release events stay
# family-only — supporters never see round state changes.
SUPPORTER_PLAIN_TYPES = {FeedEventType.prediction_added}
```

Both `event_visible_to_supporter` and `filter_events_for_supporter` check it alongside `SUPPORTER_ROSTER_TYPES`. Residual inference (a supporter noticing `prediction_added` events stop after a seal) is the spec's accepted-for-MVP polling risk.

### 8.3 Notifications — zero new kinds; the seal task calls `notify()` itself

`create_capsule`'s notification fires in the request handler; there is no hook that fires when a capsule is *created programmatically* — so the seal task is the call site (§6.2 steps 3–4). Exact invocations:

```python
# Seal (non-empty rounds only) — audience per the capsule_sealed taxonomy row:
# family members, supporters excluded; no exclude_user_id (no human sealer).
batch = notify(
    db,
    kind=NotificationKind.capsule_sealed,
    recipients=family_recipients(db, child.family_id),
    title=f"{count} predictions for {child.first_name} are sealed",      # ≤50 chars for realistic names; _clip backstops
    body=f"Locked until {child.first_name} turns 18 — and a new round just opened. What do you predict?",
    url=f"/family/{child.family_id}/child/{child.id}",
    family_id=child.family_id,
    email_builder=...,   # brand-voice equivalent; gated by email_capsule_sealed prefs
)

# Finale — audience per the capsule_released taxonomy row: parents/guardians.
batch = notify(
    db,
    kind=NotificationKind.capsule_released,
    recipients=family_recipients(db, child.family_id, roles=[FamilyRole.parent, FamilyRole.guardian]),
    title=f"{child.first_name}'s Book of Predictions just opened",
    body="Years of the family imagining the future — open it together.",
    url=f"/family/{child.family_id}/child/{child.id}/predictions",
    family_id=child.family_id,
    email_builder=...,
)
```

Both ride the existing preference columns (`*_capsule_sealed`, `*_capsule_released`); bell rows are staged in the seal transaction; **delivery is post-commit** via the returned batches (§6.2/§6.3) — a lost commit race never double-sends. All copy through brand-guardian (F5); no crypto terminology anywhere, including inside the SVG.

---

## 9. Web integration (`apps/web`)

### 9.1 API client — `src/lib/api.ts`

Types mirroring §7.1 (`PredictionGameOut`, `PredictionOut`, `CloudWordOut`, `SealedRoundOut`, `PredictionBookOut`) and functions: `getPredictionGame(childId)`, `savePrediction(childId, body)` (PUT), `deleteMyPrediction(childId)`, `deletePrediction(predictionId)`, `listSealedPredictionRounds(childId)`, `getPredictionBook(childId)`. `mediaUrl(...)` already serves the book images.

### 9.2 Components — `src/components/predictions.tsx`

- **`WordCloud`** — client-side renderer for the **open** round (always current; re-renders on every submit without waiting for any image): flex-wrapped `<span>`s from the API's `{word, weight}` payload in delivered order, `fontSize = 14 + 18 * (w - min) / (max - min)` px, the three brand text colors cycling by index. Not the SVG algorithm — the client stays dumb; the server-rendered SVG exists only for sealed years.
- **`PredictionComposer`** — follows the feed.tsx comment-composer pattern (`submitComment`, feed.tsx:217-231: local `body`/`busy`/`ApiError` state): one input, live `{n}/120` counter, submit button reading "Add your prediction" or "Save your prediction" (edit mode pre-fills from the viewer's list entry via `my_prediction_id`); "Remove" with one confirm on the viewer's own row. ~2 taps + typing.
- **`PredictionsCard`** — the child-page card: mini `WordCloud`, composer, list panel (author name, body, `timeAgo`; "Remove" affordance on every row for parents/guardians via `can_delete`), seal banner — family: "Seals on {name}'s birthday — {formatted seals_on}"; supporter (`seals_on === null`): "Seals on {name}'s next birthday". Renders nothing when `round === null && !completed`; renders a warm "The book is open" link card when `completed`.
- **`SealedPredictionYears`** — family-only strip of locked entries from `/rounds`: "{year} · sealed · opens on {name}'s 18th birthday". No counts, no peek affordance for anyone.

### 9.3 Pages & placement

- **Child vault page** (`src/app/family/[id]/child/[childId]/page.tsx`): family branch — `PredictionsCard` directly after the fund/badges grid (the yearly ritual deserves the fold), `SealedPredictionYears` rendered adjacent to `CapsulesSection` (the "locked things for later" neighborhood). Supporter branch — `PredictionsCard` after `SupporterFundCard` (their scoped surface; the card itself omits dates because the API already did).
- **Book page** — `src/app/family/[id]/child/[childId]/predictions/page.tsx` (client component, `useParams()` — Next 15 pin): chronological chapters, each an `<img src={mediaUrl(cloud_media_id)}>` (SVG content type renders natively in `<img>`; `ZoomableImage` for consistency) above the full attributed list. Warm framing: "Years of the family imagining who you'd become." Supporters never reach it (API 403 → the page shows the standing family-only message; no link is rendered for them anyway).

### 9.4 Feed renderers (`src/components/feed.tsx`)

- `prediction_added`: "{actor} added a prediction for {child_name} — what do you predict?" → links to the child page.
- `predictions_sealed`: system-voice (ignore `actor` in copy; use `payload.count`/`child_name`): "{count} predictions for {child_name} are sealed until the 18th birthday — a new round just opened." Name-based, no pronouns (brand pass, F5). → links to the child page.
- `predictions_released`: "Years of predictions for {child_name} just opened ♥" → links to the book.

---

## 10. Failure & edge handling

| Case | Behavior |
|---|---|
| Sweep + lazy read race on the same birthday | CAS status UPDATE (§6.2.1): loser's `rowcount=0`, no second image/event/batch. Clock skew between the two paths is bounded by design: both compare the same UTC date; the lazy path can only seal *earlier in the same UTC day* than the 09:00 sweep — never a different round (§13.3). |
| Prediction submitted during the seal transaction | The write's own transaction re-checks `status='open'`; it either commits before the CAS (sealed with the old round) or fails the re-check and lands in the new round after retry-read. Never lost. |
| Double-tap submit | `uq_predictions_one_per_author` + savepoint → update-in-place; exactly one `prediction_added`. |
| Empty round on birthday | `skipped`: no image, no event, no notification; next round opens in the same transaction. |
| Child joined at 17 | Final seal path releases the just-sealed round immediately (§6.2.4) — one-chapter book, image rendered, opens same day. |
| Platform dark across a birthday | Next sweep or first lazy read seals late (sealed_at > seals_on); intermediate missed years seal as `skipped` in the catch-up loop. Predictions kept accumulating in the overdue round until then — acceptable: the seal moment is "first trigger on/after the birthday". |
| SVG render throws mid-seal | The whole per-round transaction rolls back (round stays `open`); the next trigger retries. `put_object` succeeded but commit failed ⇒ an orphaned storage object under a UUID key — harmless, invisible (no MediaObject row), same failure class as abandoned client uploads. |
| Media fetch of a sealed cloud | 404 for everyone including parents and `uploaded_by` (§5.3). Released: family 200, supporter 404 (existing child-media branch). |
| Author leaves / supporter removed | Prediction stands with display-name attribution; access ends with membership (all endpoints re-check active membership per request). |
| GDPR erasure of an author | Anonymized attribution via user row; on a text-deletion request the admin runbook deletes the row (open or sealed) and runs `rerender_round_cloud` (§6.4). |
| Child/family deletion | App-level cascade: predictions → rounds → cloud media rows + storage objects, sealed or not (child erasure beats the capsule). Wire into the deletion paths when they exist — tracked in the data-model delta (§12). |
| Birthdate corrected mid-round | Open round's `seals_on` recomputed; unique-collision micro-edge logged and skipped (§6.4). |
| Child ≥ 18 at profile creation | `ensure_open_round` returns None; no rounds, no card, ever. |
| No birthdate | Structurally impossible today (`children.birthdate` is NOT NULL, models.py:283). If birthdate ever becomes optional, `ensure_open_round`'s guard is the single gate to extend — noted so the spec's "invisible without birthdate" rule has a home. |

---

## 11. Compliance & principles checklist

1. **Zero crypto surface** — no `anchor_ref`, no chain touch; no Web3 terminology in any string, email, feed copy, or inside the SVG (wordmark + family words only).
2. **Children are profiles, not accounts** — no child-facing surface; the book is delivered to the family; no new consent type (family-authored text about the child rides `profile_creation`, same as memories); moderation is the parent/guardian control surface; access is scoped by family membership + supporter rules through the standing `get_child_with_access` gate.
3. **Private by design** — everything family-scoped; supporters get the narrowest slice (open round only, no birthdate-derived fields ever serialized to them, sealed/released invisible, feed shows them only `prediction_added`); nothing public or cross-family.
4. **Sealed means sealed** — no API path (list, media, feed payload, notification body) carries sealed text, weights, counts, or the image to any non-admin caller; parents included. The admin GDPR runbook is the sole sanctioned exception.
5. **60-second flows** — child page → card → type → submit: 2 taps + typing.
6. **Serverless / Lambda-shaped** — all side effects inside a request or the existing daily maintenance invocation; the seal task is a plain function of `(db, today)`; no workers, no new schedule, no state outside Postgres/S3.
7. **Free feature** — no entitlement checks, no `require_capability`, no Premium adjacency.
8. **Cost** — no new infra, no new env vars; one small SVG (~10–40 KB) per child per year in S3. ≈ $0.

---

## 12. Implementation plan

Contract-first: §7 is frozen — frontend builds against it immediately (everything runs on the local backend; no Stripe, no cloud dependency). Companion doc deltas land with B1: `docs/data-model.md` gains the two tables + access rules + deletion-cascade note; `docs/architecture.md` gains the server-generated-media capability (`put_object`) and the seal-task/maintenance wiring.

### (a) Backend (`backend-engineer`)

1. **B1 — Schema + models + migration + helpers.** `PredictionRoundStatus`, `PredictionRound`, `Prediction`, three `FeedEventType` values (models.py); `services/birthdays.py` extraction + capsules.py import swap; migration `e91c4a7d3b06` with `down_revision = "b8f2c1a9d4e7"` (current HEAD — verified: nothing lists it as a down_revision) and the backfill (§1.5); doc deltas. Tests: helper math (Feb-29, next-birthday-on-birthday), backfill-equivalent `ensure_open_round` behavior.
2. **B2 — Tokenizer + SVG + storage.** `tokenize`/`cloud_words`/`render_cloud_svg` (§3–4); `MediaStorage.put_object` on both impls + `store_generated_media` (§5.1–5.2). Tests: determinism (identical input+seed ⇒ identical bytes), per-prediction dedupe, stopword/name drops, empty-cloud fallback, 1-vs-60+ words, 120-char token clamp, XML escaping of hostile input (`<script>`, quotes).
3. **B3 — Lifecycle service.** `ensure_open_round`, `seal_due_prediction_rounds` (CAS, skip-if-empty, finale, catch-up loop), `rerender_round_cloud`, maintenance wiring + counts (update `tests/test_maintenance.py` exact-dict assertions), notification copy + email builders. Tests: birthday-today seeding (conftest `add_child` birthdate `2018-05-01`, then `TestingSession` sets the open round's `seals_on = date.today()` — no freezegun in this codebase, seed explicit dates); sweep idempotency (run twice ⇒ second run all-zero counts, one media row, one feed event, one bell batch); empty-round skip; 18th-birthday finale (set birthdate so `age_on == 18` today: final seal + all released + no new round + exactly one `predictions_released` + one `capsule_released` batch + subsequent PUT ⇒ friendly 409); joined-at-17 one-chapter release; catch-up loop after a dark year.
4. **B4 — Router + guards.** `routers/predictions.py` + schemas + `main.py` mount; `download_media` sealed-round guard (§5.3); `access.py` `SUPPORTER_PLAIN_TYPES` (§8.2); `create_child` hook. Tests: full supporter matrix (submit/edit/delete own = 200; `seals_on` null; `/rounds`,`/book` = 403; moderation of others = 403; sealed cloud media = 404; released media = 404; feed shows `prediction_added` only); parent moderation delete; one-per-author upsert + double-tap; 2/120 trim validation; non-member 404; write-after-seal 409; lazy seal on GET; `prediction_added` fires once (create) and never (edit).

Dependencies: B1 → B2/B3/B4; B2 → B3; B3 → B4's lazy paths (B4's pure CRUD can start against B1). B2 and B4-CRUD parallelize.

### (b) Frontend (`frontend-engineer`) — parallel after the contract; real data after B4

1. **F1** — `api.ts` types + functions (§9.1).
2. **F2** — `WordCloud` + `PredictionComposer` + `PredictionsCard`; child-page wiring, both branches (§9.3).
3. **F3** — `SealedPredictionYears` + placement by `CapsulesSection`.
4. **F4** — Book page + feed renderers for the three event types.
5. **F5** — Copy pass through brand-guardian: card, banners, composer, 409 messages, notification/email copy, SVG title/seal-line, feed strings. No pronouns anywhere (no gender data); no Premium adjacency; no crypto terms.

### (c) Rollout

1. **R1** — `uv run alembic upgrade head` locally; verify backfill on the dev DB; `uv run pytest` + `npm run build` green.
2. **R2** — Deploy API (migration runs via the `migrate` management command per `docs/deploy.md`), then web. No CDK change, no env change. Post-deploy: confirm the next 09:00 UTC maintenance log line includes the new counts.

Definition of done: every acceptance criterion in `docs/specs/future-predictions.md` §3–§7 passes; a supporter payload never contains `seals_on`/`sealed_at`/`opens_on`; a parent cannot fetch a sealed cloud image by media id.

---

## 13. Risks & trade-offs

1. **SVG vs PNG.** SVG: zero dependencies (pyproject has no image libs; Lambda bundle is `--only-binary :all:` cross-compiled — Pillow would add ~3 MB and a C-extension risk surface), crisp at any size, tiny (~10–40 KB), byte-deterministic. Cons: (a) not pre-rasterized for external sharing/download-as-photo — acceptable, sharing is out of scope and the book is an in-app surface; (b) *rasterization* varies by viewer fonts even though bytes don't — the acceptance criterion is bytes-stable layout, which holds; (c) SVG is an active format — mitigated because content is 100% server-composed with `xml.sax.saxutils.escape` on all user-derived words, no scripts/handlers/external refs, and it is only ever loaded via `<img>` (which executes nothing). A future "print the book" upsell would add server-side rasterization then, not now.
2. **`S3MediaStorage.put_object` is the first server-side write.** Risk is low: IAM `grantPut` already exists for the presign flow, and the method is 3 lines. The failure mode (put succeeds, DB commit fails) leaves an unreferenced UUID object — same orphan class the presign flow already tolerates.
3. **UTC birthday semantics.** `seals_on` is the UTC date matching the birthday month/day; sealing happens at the first trigger on/after it (lazy read any time after 00:00 UTC, else the 09:00 UTC sweep). A family in UTC−10 may see the seal land the evening *before* their local birthday; UTC+13, the morning after. Chosen deliberately: it matches capsule `release_date` semantics exactly, families have no timezone field, and the banner says "Seals on Emma's birthday" without a time. Revisit only if a family-timezone column ever exists platform-wide.
4. **Lazy-vs-sweep skew.** Both paths share one function and one UTC-date comparison, so skew only affects *time of day*, never *which* round seals; the CAS guard makes the overlap harmless. The catch-up loop bounds multi-day outages.
5. **`predictions_released` is exactly VARCHAR(20).** It fits, but it is the ceiling — any future feed type must be ≤ 20 chars or widen the column. Flagged in models.py comment.
6. **Supporter inference channel.** A supporter polling `GET /predictions` daily can infer the birthday week from the open round's reset (their `prediction_added` feed items also stop). Spec-accepted MVP risk; we minimize it by serializing no transition timestamps to supporters at all.
7. **Row-packed cloud, not a spiral.** The deterministic row layout is aesthetically simpler than classic word-cloud spirals. Deliberate: a placement algorithm with collision detection needs text metrics we don't have server-side without a font library. Font-size ∝ weight carries the meaning; the seeded shuffle keeps it organic. Upgradable later without schema/API change (re-render only affects future seals — sealed images are immutable artifacts).
8. **Feed-actor convention for system events.** `predictions_sealed`/`predictions_released` borrow `child.created_by` as `actor_user_id` (NOT NULL FK). Web renderers must use system-voice copy and ignore the actor; if more system events accrue, a nullable actor or a platform-actor row is a known refactor.
