"""Future Predictions API — the yearly family word-cloud game.

Every game read runs the lazy pair first (`seal_due_prediction_rounds` then
`ensure_open_round`), matching how capsule reads self-heal. The open round is
visible to family members AND active supporters (the `create_contribution`
precedent — `get_child_with_access`, no `require_not_supporter`); supporters
never receive any birthdate-derived field (`seals_on` is stripped to None), and
sealed/released rounds are family-only (`/rounds`, `/book`).
"""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func

from ..deps import (
    CurrentUser,
    DbSession,
    get_child_with_access,
    is_supporter,
    require_not_supporter,
)
from ..models import (
    Child,
    FamilyMember,
    FamilyRole,
    FeedEventType,
    MediaObject,
    Prediction,
    PredictionRound,
    PredictionRoundStatus,
)
from ..schemas import (
    BookChapterOut,
    BookPredictionOut,
    CloudWordOut,
    OpenRoundOut,
    PredictionBookOut,
    PredictionCreate,
    PredictionGameOut,
    PredictionOut,
    SealedRoundOut,
)
from ..services.birthdays import age_on, birthday_at_age
from ..services.feed import emit
from ..services.predictions import (
    MAX_PREDICTIONS_PER_ROUND,
    cloud_words,
    ensure_open_round,
    seal_due_prediction_rounds,
)

router = APIRouter(tags=["predictions"])

_MODERATOR_ROLES = (FamilyRole.parent, FamilyRole.guardian)


def _run_due_seals(db, child: Child) -> None:
    """Lazy seal on the game read path (mirrors list_capsules → release_due_capsules):
    seal any due rounds, commit, then deliver notifications post-commit."""
    counts, batches = seal_due_prediction_rounds(db, child=child)
    db.commit()
    for batch in batches:
        batch.deliver(db)


def _prediction_out(pred: Prediction, *, viewer_id: uuid.UUID, viewer_role: FamilyRole) -> PredictionOut:
    is_mine = pred.author_user_id == viewer_id
    return PredictionOut(
        id=pred.id,
        body=pred.body,
        author_name=pred.author.display_name,
        is_mine=is_mine,
        can_delete=is_mine or viewer_role in _MODERATOR_ROLES,
        created_at=pred.created_at,
    )


def _open_round_out(
    db, round: PredictionRound, child: Child, user, membership: FamilyMember
) -> OpenRoundOut:
    preds = (
        db.query(Prediction)
        .filter(Prediction.round_id == round.id)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .all()
    )
    words = cloud_words([p.body for p in preds], child_first_name=child.first_name)
    supporter = is_supporter(membership.role)
    return OpenRoundOut(
        id=round.id,
        # A supporter must never receive the birthdate-derived seal date. `year`
        # is `seals_on.year` (the NEXT birthday), which alone reveals whether the
        # birthday has already passed this year — so it is withheld too.
        year=None if supporter else round.seals_on.year,
        seals_on=None if supporter else round.seals_on,
        cloud=[CloudWordOut(word=w.word, weight=w.weight) for w in words],
        predictions=[
            _prediction_out(p, viewer_id=user.id, viewer_role=membership.role) for p in preds
        ],
        my_prediction_ids=[p.id for p in preds if p.author_user_id == user.id],
        max_per_member=MAX_PREDICTIONS_PER_ROUND,
    )


@router.get("/children/{child_id}/predictions", response_model=PredictionGameOut)
def get_prediction_game(child_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PredictionGameOut:
    """The game surface: the open round + live cloud + attributed list.
    Supporters allowed (open-round only)."""
    child, membership = get_child_with_access(db, child_id, user)
    _run_due_seals(db, child)
    round = ensure_open_round(db, child)
    db.commit()

    supporter = is_supporter(membership.role)
    round_out = _open_round_out(db, round, child, user, membership) if round is not None else None
    # completed is a family-only signal (the book is open); supporters always
    # get completed=False + round=None (indistinguishable from "feature idle").
    completed = (not supporter) and round is None and _has_released(db, child_id)
    return PredictionGameOut(
        child_first_name=child.first_name, round=round_out, completed=completed
    )


@router.post(
    "/children/{child_id}/predictions",
    response_model=PredictionOut,
    status_code=status.HTTP_201_CREATED,
)
def add_prediction(
    child_id: uuid.UUID, payload: PredictionCreate, db: DbSession, user: CurrentUser
) -> PredictionOut:
    """Add one prediction to the open round. Up to three per author per round;
    the 4th is rejected. Supporters allowed. Emits `prediction_added` only on
    the author's FIRST prediction in the round (never on later adds/edits)."""
    child, membership = get_child_with_access(db, child_id, user)
    _run_due_seals(db, child)
    round = ensure_open_round(db, child)
    db.commit()
    if round is None:
        # A round is always open for an under-18 child, so `round is None` means
        # the child has turned 18. Don't confirm that age fact to a supporter —
        # give them a neutral "not open" message instead of "the book is complete".
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Predictions aren't open right now."
            if is_supporter(membership.role)
            else f"{child.first_name}'s Book of Predictions is complete.",
        )
    # Race guard: a round sealing mid-request turns the write into a friendly 409.
    if round.status != PredictionRoundStatus.open:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "These predictions are already sealed."
        )

    # The cap, enforced in-transaction (there is no unique constraint). A rare
    # concurrent double-submit racing to a 4th row is an accepted minor
    # over-count at this scale.
    existing = (
        db.query(func.count(Prediction.id))
        .filter(
            Prediction.round_id == round.id,
            Prediction.author_user_id == user.id,
        )
        .scalar()
        or 0
    )
    if existing >= MAX_PREDICTIONS_PER_ROUND:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You've added all {MAX_PREDICTIONS_PER_ROUND} of your predictions for this year.",
        )

    pred = Prediction(round_id=round.id, author_user_id=user.id, body=payload.body)
    db.add(pred)
    db.flush()
    if existing == 0:
        # First prediction by this author in this round — the one feed event.
        emit(
            db,
            family_id=child.family_id,
            actor_user_id=user.id,
            type=FeedEventType.prediction_added,
            child_id=child.id,
            # No `year`/date in the payload: `prediction_added` is shown to
            # supporters (SUPPORTER_PLAIN_TYPES), and the seal year leaks the
            # birthdate-derived date. The renderer only needs the child.
            payload={
                "child_id": str(child.id),
                "child_name": child.first_name,
            },
        )
    db.commit()
    return _prediction_out(pred, viewer_id=user.id, viewer_role=membership.role)


@router.patch("/predictions/{prediction_id}", response_model=PredictionOut)
def edit_prediction(
    prediction_id: uuid.UUID, payload: PredictionCreate, db: DbSession, user: CurrentUser
) -> PredictionOut:
    """Authors edit their own prediction while the round is open. No feed event
    (edits are not feed-worthy)."""
    pred, round, _child, membership = _load_prediction(db, prediction_id, user)
    if pred.author_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own prediction.")
    if round.status != PredictionRoundStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "These predictions are already sealed.")
    pred.body = payload.body
    db.commit()
    return _prediction_out(pred, viewer_id=user.id, viewer_role=membership.role)


@router.delete("/predictions/{prediction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prediction(prediction_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    """Authors delete their own; parents/guardians may delete anyone's (silent
    moderation). Open round only — nothing is mutable after seal."""
    pred, round, _child, membership = _load_prediction(db, prediction_id, user)
    is_author = pred.author_user_id == user.id
    if not (is_author or membership.role in _MODERATOR_ROLES):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only remove your own prediction.")
    if round.status != PredictionRoundStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "These predictions are already sealed.")
    db.delete(pred)
    db.commit()


def _load_prediction(
    db, prediction_id: uuid.UUID, user
) -> tuple[Prediction, PredictionRound, Child, FamilyMember]:
    pred = db.get(Prediction, prediction_id)
    if pred is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prediction not found")
    round = db.get(PredictionRound, pred.round_id)
    # get_child_with_access 404s a non-member — no existence leak.
    child, membership = get_child_with_access(db, round.child_id, user)
    return pred, round, child, membership


def _has_released(db, child_id: uuid.UUID) -> bool:
    return (
        db.query(PredictionRound.id)
        .filter(
            PredictionRound.child_id == child_id,
            PredictionRound.status == PredictionRoundStatus.released,
        )
        .first()
        is not None
    )


@router.get("/children/{child_id}/predictions/rounds", response_model=list[SealedRoundOut])
def list_sealed_rounds(
    child_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[SealedRoundOut]:
    """Family-only strip of locked years: '{year} · sealed · opens on the 18th
    birthday'. No counts, no content, no peek."""
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    _run_due_seals(db, child)
    ensure_open_round(db, child)
    db.commit()
    opens_on = birthday_at_age(child.birthdate, 18)
    rounds = (
        db.query(PredictionRound)
        .filter(
            PredictionRound.child_id == child_id,
            PredictionRound.status == PredictionRoundStatus.sealed,
        )
        .order_by(PredictionRound.seals_on)
        .all()
    )
    return [
        SealedRoundOut(id=r.id, year=r.seals_on.year, sealed_at=r.sealed_at, opens_on=opens_on)
        for r in rounds
    ]


@router.get("/children/{child_id}/predictions/book", response_model=PredictionBookOut)
def get_prediction_book(
    child_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> PredictionBookOut:
    """The released Book of Predictions (family-only). Empty chapters until the
    18th birthday; skipped years are silently absent."""
    child, membership = get_child_with_access(db, child_id, user)
    require_not_supporter(membership)
    _run_due_seals(db, child)
    ensure_open_round(db, child)
    db.commit()
    rounds = (
        db.query(PredictionRound)
        .filter(
            PredictionRound.child_id == child_id,
            PredictionRound.status == PredictionRoundStatus.released,
        )
        .order_by(PredictionRound.seals_on)
        .all()
    )
    chapters: list[BookChapterOut] = []
    for r in rounds:
        preds = (
            db.query(Prediction)
            .filter(Prediction.round_id == r.id)
            .order_by(Prediction.created_at, Prediction.id)
            .all()
        )
        media = db.get(MediaObject, r.cloud_media_id) if r.cloud_media_id else None
        chapters.append(
            BookChapterOut(
                round_id=r.id,
                year=r.seals_on.year,
                age=age_on(child.birthdate, r.seals_on),
                cloud_media_id=r.cloud_media_id,
                media_content_type=media.content_type if media else None,
                predictions=[
                    BookPredictionOut(
                        body=p.body, author_name=p.author.display_name, created_at=p.created_at
                    )
                    for p in preds
                ],
            )
        )
    return PredictionBookOut(child_first_name=child.first_name, chapters=chapters)
