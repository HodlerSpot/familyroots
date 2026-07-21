"""Future Predictions — tokenizer, sealed-image renderer, and round lifecycle.

One tokenizer (`cloud_words`) feeds BOTH the live-cloud JSON (client-rendered
for the open round) and the sealed keepsake PNG (`render_cloud_png`, rendered
server-side at seal). The lifecycle functions (`ensure_open_round`,
`seal_due_prediction_rounds`) are the only writers of `prediction_rounds`
status transitions.

Sealing mirrors the capsule release discipline: a compare-and-swap status
UPDATE (`... WHERE status='open'`) is the exactly-once guard, and the caller
COMMITS, then calls `batch.deliver(db)` for each returned batch (post-commit
delivery, so a lost commit race never double-sends). Empty rounds are `skipped`
(no image, no fanfare). On the 18th birthday the final round seals and every
sealed round of the child releases together as the Book of Predictions.
"""

import functools
import io
import random
import string
import uuid
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Child,
    FamilyRole,
    FeedEventType,
    MediaObject,
    MediaStatus,
    Prediction,
    PredictionRound,
    PredictionRoundStatus,
    User,
    utcnow,
)
from .birthdays import age_on, birthday_at_age, next_birthday
from .email_templates import render_email
from .feed import emit
from .notify import (
    EmailPayload,
    NotificationBatch,
    NotificationKind,
    family_recipients,
    notify,
)
from .storage import get_storage

# Up to three predictions per member per round (each a distinct prediction for
# weighting). Enforced by the create endpoint's in-transaction count check.
MAX_PREDICTIONS_PER_ROUND = 3

CLOUD_WORD_LIMIT = 60

# Small built-in English stopword list: articles/pronouns/auxiliaries/
# prepositions + future-tense fillers. Multilingual lists are deferred.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "if", "then", "so", "as", "of",
        "at", "by", "for", "with", "about", "into", "onto", "to", "from", "in",
        "on", "up", "out", "off", "over", "under", "again", "once", "is", "am",
        "are", "was", "were", "be", "been", "being", "have", "has", "had",
        "do", "does", "did", "doing", "will", "would", "shall", "should",
        "can", "could", "may", "might", "must", "gonna", "going", "get", "got",
        "he", "she", "it", "they", "them", "he'll", "she'll", "they'll",
        "we'll", "i'll", "you'll", "it'll", "won't", "wont", "we", "you", "i",
        "me", "my", "mine", "your", "yours", "his", "her", "hers", "its",
        "our", "ours", "their", "theirs", "this", "that", "these", "those",
        "who", "whom", "whose", "which", "what", "when", "where", "why", "how",
        "all", "any", "both", "each", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "than", "too",
        "very", "just", "one", "day", "someday", "one's", "become", "becomes",
        "grow", "grows", "always", "really", "definitely", "probably",
        "maybe", "think", "thinks", "guess", "bet", "hope", "hopes", "there",
        "here", "also", "still", "even", "ever", "never", "much", "many",
        "lot", "lots",
    }
)

# --- tokenizer / weighting ---------------------------------------------------

_KEEP = {"'", "’", "-"}  # apostrophes + hyphen are word-internal
_PUNCT = (set(string.punctuation) | {"“", "”", "‘", "…", "–", "—"}) - _KEEP
_TRANS: dict[int, int | str | None] = {ord(c): " " for c in _PUNCT}
_TRANS[ord("’")] = ord("'")  # normalize curly apostrophe to straight


@dataclass(frozen=True)
class CloudWord:
    word: str
    weight: int


def tokenize(body: str) -> set[str]:
    """The normalized DISTINCT words of one prediction. The set() is the
    per-prediction dedupe: repeating a word inside your own prediction never
    inflates its weight. Lowercase, punctuation -> space (apostrophes/hyphens
    kept word-internal), strip stray apostrophes/hyphens, drop <2-char tokens."""
    lowered = body.lower().translate(_TRANS)
    words: set[str] = set()
    for raw in lowered.split():
        tok = raw.strip("'-")
        if len(tok) >= 2:
            words.add(tok)
    return words


def cloud_words(
    bodies: list[str], *, child_first_name: str, limit: int = CLOUD_WORD_LIMIT
) -> list[CloudWord]:
    """Weight = number of distinct predictions whose token set contains the
    word. Drops STOPWORDS and the child's first name. Fallback: if the filtered
    cloud is empty but bodies is not, recount with stopwords INCLUDED (the
    child's name stays excluded). Deterministic order: weight desc, then
    alphabetical. At most `limit` words."""
    name = child_first_name.casefold().strip()

    def counted(drop_stopwords: bool) -> dict[str, int]:
        counts: dict[str, int] = {}
        for body in bodies:
            for word in tokenize(body):
                if word == name:
                    continue
                if drop_stopwords and word in STOPWORDS:
                    continue
                counts[word] = counts.get(word, 0) + 1
        return counts

    counts = counted(True)
    if not counts and bodies:
        counts = counted(False)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [CloudWord(word=word, weight=weight) for word, weight in ordered[:limit]]


# --- sealed keepsake PNG (deterministic; seeded by round id) -----------------

CANVAS_W, CANVAS_H = 1200, 900
_BG = (250, 250, 249)          # stone-50
_TITLE_COLOR = (6, 95, 70)     # emerald-800
_FOOTER_COLOR = (87, 83, 78)   # stone-600
_PALETTE = [(6, 95, 70), (180, 83, 9), (68, 64, 60)]  # emerald-800, amber-700, stone-700
_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "DejaVuSans.ttf"

_SIZE_MIN, _SIZE_MAX = 30, 96
_BAND_LEFT, _BAND_RIGHT = 60, CANVAS_W - 60
_BAND_TOP, _BAND_BOTTOM = 150, CANVAS_H - 90
_BAND_W = _BAND_RIGHT - _BAND_LEFT
_BAND_H = _BAND_BOTTOM - _BAND_TOP
_GAP = 22


@functools.lru_cache(maxsize=None)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_FONT_PATH), size)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _size_for(weight: int, w_min: int, w_max: int) -> int:
    if w_max == w_min:
        return (_SIZE_MIN + _SIZE_MAX) // 2
    return _SIZE_MIN + round((_SIZE_MAX - _SIZE_MIN) * (weight - w_min) / (w_max - w_min))


def _pack(items: list[tuple[str, int, float]]) -> list[list[tuple[str, int, float]]]:
    """Greedy row packing in the given (deterministic) order."""
    rows: list[list[tuple[str, int, float]]] = []
    cur: list[tuple[str, int, float]] = []
    cur_w = 0.0
    for word, size, width in items:
        add = width if not cur else _GAP + width
        if cur and cur_w + add > _BAND_W:
            rows.append(cur)
            cur = []
            cur_w = 0.0
            add = width
        cur.append((word, size, width))
        cur_w += add
    if cur:
        rows.append(cur)
    return rows


def _layout(words: list[CloudWord]) -> list[list[tuple[str, int, float]]]:
    weights = [w.weight for w in words]
    w_min, w_max = min(weights), max(weights)
    items: list[tuple[str, int, float]] = []
    for cw in words:
        size = _size_for(cw.weight, w_min, w_max)
        # Clamp so even the longest single word fits the band width.
        while size > _SIZE_MIN and _font(size).getlength(cw.word) > _BAND_W:
            size -= 2
        items.append((cw.word, size, _font(size).getlength(cw.word)))

    def total_h(rows: list[list[tuple[str, int, float]]]) -> float:
        return sum(1.28 * max(s for _, s, _ in row) for row in rows)

    # Deterministic degrade: drop the lowest-weight (last) word until it fits.
    while len(items) > 1 and total_h(_pack(items)) > _BAND_H:
        items.pop()
    return _pack(items)


def _draw_centered(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, color, y: int
) -> None:
    width = font.getlength(text)
    draw.text((int((CANVAS_W - width) / 2), y), text, font=font, fill=color)


def render_cloud_png(
    round: PredictionRound,
    words: list[CloudWord],
    *,
    child_first_name: str,
    ordinal_age: int,
    year: int,
    prediction_count: int,
) -> bytes:
    """Render the sealed word cloud to a fixed-size RGB PNG. DETERMINISTIC:
    layout order is `cloud_words`' deterministic output and all randomness
    (within-row shuffle + per-word color) is seeded by `str(round.id)`, so the
    same round id and words produce byte-identical bytes. Contains only: the
    cloud, the child's first name as a title, a seal-line footer, and the
    FutureRoots wordmark — never author names, never a birthdate."""
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), _BG)
    draw = ImageDraw.Draw(img)
    rng = random.Random(str(round.id))

    _draw_centered(draw, f"The family's predictions for {child_first_name}", _font(44), _TITLE_COLOR, 60)

    if words:
        rows = _layout(words)
        row_heights = [1.28 * max(s for _, s, _ in row) for row in rows]
        total = sum(row_heights)
        y = _BAND_TOP + max(0.0, (_BAND_H - total) / 2)
        for row, rh in zip(rows, row_heights):
            shuffled = list(row)
            rng.shuffle(shuffled)
            row_w = sum(w for _, _, w in shuffled) + _GAP * (len(shuffled) - 1)
            x = _BAND_LEFT + max(0.0, (_BAND_W - row_w) / 2)
            for word, size, width in shuffled:
                color = _PALETTE[rng.randrange(len(_PALETTE))]
                ty = y + (rh - size) / 2 - 0.15 * size
                draw.text((int(x), int(ty)), word, font=_font(size), fill=color)
                x += width + _GAP
            y += rh

    plural = "s" if prediction_count != 1 else ""
    seal_line = (
        f"Sealed on {child_first_name}'s {_ordinal(ordinal_age)} birthday"
        f" - {year} - {prediction_count} prediction{plural}"
    )
    draw.text((60, CANVAS_H - 55), seal_line, font=_font(24), fill=_FOOTER_COLOR)
    wordmark = "FutureRoots"
    wm_font = _font(22)
    draw.text((CANVAS_W - 60 - wm_font.getlength(wordmark), CANVAS_H - 55), wordmark, font=wm_font, fill=_TITLE_COLOR)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- server-generated media --------------------------------------------------


def store_generated_media(
    db: Session, *, child: Child, data: bytes, content_type: str = "image/png"
) -> MediaObject:
    """Create a child-scoped MediaObject for system-generated bytes and write
    them to storage. `uploaded_by = child.created_by` is provenance only — read
    access to this media is governed by the owning round's STATUS, never by
    uploaded_by (see routers/vault.download_media)."""
    storage_key = str(uuid.uuid4())
    size = get_storage().put_object(storage_key, data, content_type)
    media = MediaObject(
        child_id=child.id,
        storage_key=storage_key,
        content_type=content_type,
        byte_size=size,
        uploaded_by=child.created_by,
        status=MediaStatus.uploaded,
    )
    db.add(media)
    db.flush()
    return media


# --- round lifecycle ---------------------------------------------------------


def ensure_open_round(db: Session, child: Child) -> PredictionRound | None:
    """Idempotent, self-healing: open round 1 (or the next round) for a child
    under 18 whose game is not complete. Returns the open round, or None when
    the child is 18+ or the book has already been released. A concurrent
    double-open loses on uq_prediction_rounds_one_open and re-reads."""
    today = utcnow().date()
    if age_on(child.birthdate, today) >= 18:
        return None
    if _has_released_rounds(db, child.id):
        return None
    existing = (
        db.query(PredictionRound)
        .filter(
            PredictionRound.child_id == child.id,
            PredictionRound.status == PredictionRoundStatus.open,
        )
        .first()
    )
    if existing is not None:
        return existing

    round = PredictionRound(
        child_id=child.id,
        opened_at=utcnow(),
        seals_on=next_birthday(child.birthdate, today),
        status=PredictionRoundStatus.open,
    )
    db.add(round)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # A concurrent path won the open; return whatever is open now.
        return (
            db.query(PredictionRound)
            .filter(
                PredictionRound.child_id == child.id,
                PredictionRound.status == PredictionRoundStatus.open,
            )
            .first()
        )
    return round


def _has_released_rounds(db: Session, child_id: uuid.UUID) -> bool:
    return (
        db.query(PredictionRound.id)
        .filter(
            PredictionRound.child_id == child_id,
            PredictionRound.status == PredictionRoundStatus.released,
        )
        .first()
        is not None
    )


def _open_next_round(db: Session, child: Child, sealed_seals_on) -> None:
    sealed_age = age_on(child.birthdate, sealed_seals_on)
    round = PredictionRound(
        child_id=child.id,
        opened_at=utcnow(),
        seals_on=birthday_at_age(child.birthdate, sealed_age + 1),
        status=PredictionRoundStatus.open,
    )
    db.add(round)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        # A concurrent path already opened the next round (unique on
        # child+seals_on / one-open) — harmless.
        pass


def seal_due_prediction_rounds(
    db: Session, *, child: Child | None = None
) -> tuple[dict[str, int], list[NotificationBatch]]:
    """Seal every open round with seals_on <= today — for one child (lazy read
    path) or globally (sweep). Idempotent and race-safe (compare-and-swap on
    status). Returns (counts, batches); THE CALLER COMMITS, then calls
    batch.deliver(db) for each batch."""
    today = utcnow().date()
    counts = {
        "prediction_rounds_sealed": 0,
        "prediction_rounds_skipped": 0,
        "prediction_rounds_released": 0,
    }
    batches: list[NotificationBatch] = []
    while True:
        query = db.query(PredictionRound).filter(
            PredictionRound.status == PredictionRoundStatus.open,
            PredictionRound.seals_on <= today,
        )
        if child is not None:
            query = query.filter(PredictionRound.child_id == child.id)
        round = query.order_by(PredictionRound.seals_on, PredictionRound.id).first()
        if round is None:
            return counts, batches
        # Catch-up loop: sealing may open a next round that is ALSO due (dark
        # platform); the re-query above picks it up until seals_on > today.
        _seal_one_round(db, round, counts, batches)


def _seal_one_round(
    db: Session,
    round: PredictionRound,
    counts: dict[str, int],
    batches: list[NotificationBatch],
) -> None:
    child = db.get(Child, round.child_id)
    preds = (
        db.query(Prediction)
        .filter(Prediction.round_id == round.id)
        .order_by(Prediction.created_at, Prediction.id)
        .all()
    )
    is_empty = len(preds) == 0
    new_status = PredictionRoundStatus.skipped if is_empty else PredictionRoundStatus.sealed
    now = utcnow()

    # Exactly-once compare-and-swap: a concurrent sweep/lazy racer gets
    # rowcount=0 and does nothing further. The row's own status is the ledger.
    claimed = (
        db.query(PredictionRound)
        .filter(
            PredictionRound.id == round.id,
            PredictionRound.status == PredictionRoundStatus.open,
        )
        .update(
            {PredictionRound.status: new_status, PredictionRound.sealed_at: now},
            synchronize_session=False,
        )
    )
    if not claimed:
        return
    db.expire(round)  # sync the ORM object with the claimed row

    is_final = round.seals_on >= birthday_at_age(child.birthdate, 18)

    if not is_empty:
        counts["prediction_rounds_sealed"] += 1
        words = cloud_words([p.body for p in preds], child_first_name=child.first_name)
        png = render_cloud_png(
            round,
            words,
            child_first_name=child.first_name,
            ordinal_age=age_on(child.birthdate, round.seals_on),
            year=round.seals_on.year,
            prediction_count=len(preds),
        )
        media = store_generated_media(db, child=child, data=png, content_type="image/png")
        round.cloud_media_id = media.id
        # On the FINAL birthday the seal is folded into the grand opening: no
        # "a new round opened" seal fanfare — only the release event/batch fire
        # (spec Flow D: exactly one predictions_released). The image is still
        # rendered for the book.
        if not is_final:
            emit(
                db,
                family_id=child.family_id,
                actor_user_id=child.created_by,
                type=FeedEventType.predictions_sealed,
                child_id=child.id,
                payload={
                    "child_id": str(child.id),
                    "child_name": child.first_name,
                    "year": round.seals_on.year,
                    "prediction_count": len(preds),
                },
            )
            batches.append(_seal_notification(db, child, len(preds)))
    else:
        counts["prediction_rounds_skipped"] += 1

    if is_final:
        released = (
            db.query(PredictionRound)
            .filter(
                PredictionRound.child_id == child.id,
                PredictionRound.status == PredictionRoundStatus.sealed,
            )
            .all()
        )
        for r in released:
            r.status = PredictionRoundStatus.released
            r.released_at = now
        if released:
            counts["prediction_rounds_released"] += len(released)
            emit(
                db,
                family_id=child.family_id,
                actor_user_id=child.created_by,
                type=FeedEventType.predictions_released,
                child_id=child.id,
                payload={
                    "child_id": str(child.id),
                    "child_name": child.first_name,
                    "years": len(released),
                },
            )
            batches.append(_release_notification(db, child, len(released)))
        # The game is complete — no new round opens ever again.
    else:
        _open_next_round(db, child, round.seals_on)


def _seal_notification(db: Session, child: Child, count: int) -> NotificationBatch:
    """capsule_sealed (existing kind): family members, supporters excluded, no
    human sealer to exclude. Copy doubles as the new-round invitation."""
    url = f"/family/{child.family_id}/child/{child.id}"
    email_url = f"{settings.web_base_url}{url}"

    def email_builder(recipient: User) -> EmailPayload:
        return EmailPayload(
            subject=f"{count} predictions for {child.first_name} are sealed",
            body=(
                f"Hi {recipient.display_name},\n\n"
                f"This year's predictions for {child.first_name} are sealed away, "
                f"safe until {child.first_name} turns 18. A fresh round just "
                f"opened — what do you predict this year?\n\n"
                f"Add your prediction: {email_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=(
                    f"This year's predictions for {child.first_name} are sealed "
                    f"until the 18th birthday — a new round is open."
                ),
                greeting=f"Hi {recipient.display_name},",
                paragraphs=[
                    f"This year's predictions for {child.first_name} are sealed "
                    f"away, safe until {child.first_name} turns 18.",
                    "A fresh round just opened — what do you predict this year?",
                ],
                cta_label="Add your prediction",
                cta_url=email_url,
            ),
        )

    return notify(
        db,
        kind=NotificationKind.capsule_sealed,
        recipients=family_recipients(db, child.family_id),
        title=f"{count} predictions for {child.first_name} are sealed",
        body=(
            f"Locked until {child.first_name} turns 18 — and a new round just "
            f"opened. What do you predict?"
        ),
        url=url,
        family_id=child.family_id,
        email_builder=email_builder,
    )


def _release_notification(db: Session, child: Child, years: int) -> NotificationBatch:
    """capsule_released (existing kind): parents/guardians per the standing
    taxonomy; the rest of the family catches it on the feed."""
    url = f"/family/{child.family_id}/child/{child.id}/predictions"
    email_url = f"{settings.web_base_url}{url}"

    def email_builder(recipient: User) -> EmailPayload:
        return EmailPayload(
            subject=f"{child.first_name}'s Book of Predictions just opened",
            body=(
                f"Hi {recipient.display_name},\n\n"
                f"Years of the family imagining who {child.first_name} would "
                f"become are finally open. Read them together.\n\n"
                f"Open the book: {email_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=(
                    f"Years of predictions for {child.first_name} are finally open."
                ),
                greeting=f"Hi {recipient.display_name},",
                paragraphs=[
                    f"Years of the family imagining who {child.first_name} would "
                    f"become are finally open.",
                    "Open it together.",
                ],
                cta_label="Open the book",
                cta_url=email_url,
            ),
        )

    return notify(
        db,
        kind=NotificationKind.capsule_released,
        recipients=family_recipients(
            db, child.family_id, roles=[FamilyRole.parent, FamilyRole.guardian]
        ),
        title=f"{child.first_name}'s Book of Predictions just opened",
        body="Years of the family imagining the future — open it together.",
        url=url,
        family_id=child.family_id,
        email_builder=email_builder,
    )
