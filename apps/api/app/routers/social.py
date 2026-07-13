"""Reactions and comments on Family Moments (feed events).

Everyone in a family can react and comment; a supporter may only touch the
moments the feed would show them (section E visibility rules). Access always
resolves back to the underlying feed event, so the same rule governs both.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, DbSession, get_active_membership, is_supporter
from ..models import (
    Comment,
    FamilyMember,
    FamilyRole,
    FeedEvent,
    Reaction,
    ReactionTargetType,
    utcnow,
)
from ..schemas import (
    CommentCreate,
    CommentOut,
    ReactionSummaryOut,
    ReactionToggle,
)
from ..services.access import event_visible_to_supporter
from ..services.social import REACTION_PALETTE, reaction_summaries, reaction_summary

router = APIRouter(tags=["social"])


def _resolve_event(db, user, feed_event_id: uuid.UUID) -> tuple[FeedEvent, FamilyMember]:
    """Load a feed event the caller is allowed to see, or 404.

    404 (not 403) throughout so a supporter can never probe the existence of a
    moment that isn't shared with them."""
    event = db.get(FeedEvent, feed_event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Moment not found")
    membership = get_active_membership(db, event.family_id, user)
    if is_supporter(membership.role) and not event_visible_to_supporter(db, event):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Moment not found")
    return event, membership


def _comment_or_404(db, comment_id: uuid.UUID) -> Comment:
    comment = db.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    return comment


def _feed_event_for_target(
    db, target_type: ReactionTargetType, target_id: uuid.UUID
) -> uuid.UUID:
    """The feed event a reaction target belongs to (for the access check)."""
    if target_type == ReactionTargetType.comment:
        return _comment_or_404(db, target_id).feed_event_id
    return target_id


def _comment_out(comment: Comment, *, is_parent: bool, viewer_id, reactions) -> CommentOut:
    return CommentOut(
        id=comment.id,
        author_name=comment.author.display_name,
        author_user_id=comment.user_id,
        body=comment.body,
        created_at=comment.created_at,
        reactions=reactions,
        can_delete=(comment.user_id == viewer_id) or is_parent,
    )


# --- reactions ---

@router.post("/reactions", response_model=ReactionSummaryOut)
def toggle_reaction(
    payload: ReactionToggle, db: DbSession, user: CurrentUser
) -> ReactionSummaryOut:
    if payload.emoji not in REACTION_PALETTE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That reaction isn't available")

    feed_event_id = _feed_event_for_target(db, payload.target_type, payload.target_id)
    _resolve_event(db, user, feed_event_id)

    existing = (
        db.query(Reaction)
        .filter(
            Reaction.target_type == payload.target_type,
            Reaction.target_id == payload.target_id,
            Reaction.user_id == user.id,
            Reaction.emoji == payload.emoji,
        )
        .first()
    )
    if existing is not None:
        db.delete(existing)
    else:
        db.add(
            Reaction(
                target_type=payload.target_type,
                target_id=payload.target_id,
                user_id=user.id,
                emoji=payload.emoji,
            )
        )
    db.commit()
    return ReactionSummaryOut(
        reactions=reaction_summary(db, payload.target_type, payload.target_id, user.id)
    )


@router.get("/reactions", response_model=ReactionSummaryOut)
def get_reactions(
    target_type: ReactionTargetType,
    target_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
) -> ReactionSummaryOut:
    feed_event_id = _feed_event_for_target(db, target_type, target_id)
    _resolve_event(db, user, feed_event_id)
    return ReactionSummaryOut(
        reactions=reaction_summary(db, target_type, target_id, user.id)
    )


# --- comments ---

@router.post("/feed-events/{event_id}/comments", response_model=CommentOut,
             status_code=status.HTTP_201_CREATED)
def add_comment(
    event_id: uuid.UUID, payload: CommentCreate, db: DbSession, user: CurrentUser
) -> CommentOut:
    _, membership = _resolve_event(db, user, event_id)
    comment = Comment(feed_event_id=event_id, user_id=user.id, body=payload.body)
    db.add(comment)
    db.commit()
    return _comment_out(
        comment,
        is_parent=(membership.role == FamilyRole.parent),
        viewer_id=user.id,
        reactions=[],
    )


@router.get("/feed-events/{event_id}/comments", response_model=list[CommentOut])
def list_comments(
    event_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[CommentOut]:
    _, membership = _resolve_event(db, user, event_id)
    comments = (
        db.query(Comment)
        .filter(Comment.feed_event_id == event_id, Comment.deleted_at.is_(None))
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .all()
    )
    reactions = reaction_summaries(
        db, ReactionTargetType.comment, [c.id for c in comments], user.id
    )
    is_parent = membership.role == FamilyRole.parent
    return [
        _comment_out(
            c, is_parent=is_parent, viewer_id=user.id, reactions=reactions.get(c.id, [])
        )
        for c in comments
    ]


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(comment_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    comment = _comment_or_404(db, comment_id)
    _, membership = _resolve_event(db, user, comment.feed_event_id)
    if comment.user_id != user.id and membership.role != FamilyRole.parent:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the author or a parent can remove this"
        )
    comment.deleted_at = utcnow()
    db.commit()
