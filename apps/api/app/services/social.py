"""Reaction and comment aggregation.

Batch helpers so the feed and comment lists can show at-a-glance reaction
tallies and comment counts without per-row (N+1) queries.
"""

import uuid

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import Comment, Reaction, ReactionTargetType
from ..schemas import ReactionSummary

# The allowed emoji palette; also fixes the display order of a summary.
REACTION_PALETTE = ["❤️", "\U0001f44d", "\U0001f389", "\U0001f602", "\U0001f970", "\U0001f622"]
_PALETTE_ORDER = {emoji: i for i, emoji in enumerate(REACTION_PALETTE)}


def reaction_summaries(
    db: Session,
    target_type: ReactionTargetType,
    target_ids: list[uuid.UUID],
    viewer_id: uuid.UUID,
) -> dict[uuid.UUID, list[ReactionSummary]]:
    """Per-target emoji tallies, one query for the whole batch."""
    if not target_ids:
        return {}
    rows = (
        db.query(
            Reaction.target_id,
            Reaction.emoji,
            func.count().label("total"),
            func.max(case((Reaction.user_id == viewer_id, 1), else_=0)).label("mine"),
        )
        .filter(
            Reaction.target_type == target_type,
            Reaction.target_id.in_(target_ids),
        )
        .group_by(Reaction.target_id, Reaction.emoji)
        .all()
    )
    grouped: dict[uuid.UUID, list[tuple[str, int, bool]]] = {}
    for target_id, emoji, total, mine in rows:
        grouped.setdefault(target_id, []).append((emoji, int(total), bool(mine)))

    out: dict[uuid.UUID, list[ReactionSummary]] = {}
    for target_id, items in grouped.items():
        items.sort(key=lambda t: _PALETTE_ORDER.get(t[0], 99))
        out[target_id] = [
            ReactionSummary(emoji=e, count=c, reacted=r) for e, c, r in items
        ]
    return out


def reaction_summary(
    db: Session,
    target_type: ReactionTargetType,
    target_id: uuid.UUID,
    viewer_id: uuid.UUID,
) -> list[ReactionSummary]:
    return reaction_summaries(db, target_type, [target_id], viewer_id).get(target_id, [])


def comment_counts(db: Session, feed_event_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Live (non-deleted) comment count per feed event, one query."""
    if not feed_event_ids:
        return {}
    rows = (
        db.query(Comment.feed_event_id, func.count())
        .filter(
            Comment.feed_event_id.in_(feed_event_ids),
            Comment.deleted_at.is_(None),
        )
        .group_by(Comment.feed_event_id)
        .all()
    )
    return {feed_event_id: int(count) for feed_event_id, count in rows}
