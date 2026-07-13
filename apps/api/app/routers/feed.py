import uuid

from fastapi import APIRouter, Query

from ..deps import CurrentUser, DbSession, get_active_membership
from ..models import FeedEvent, FamilyRole, ReactionTargetType
from ..schemas import FeedEventOut
from ..services.access import filter_events_for_supporter
from ..services.social import comment_counts, reaction_summaries

router = APIRouter(tags=["feed"])


@router.get("/families/{family_id}/feed", response_model=list[FeedEventOut])
def family_feed(
    family_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, le=100),
) -> list[FeedEventOut]:
    membership = get_active_membership(db, family_id, user)
    events = (
        db.query(FeedEvent)
        .filter(FeedEvent.family_id == family_id)
        .order_by(FeedEvent.created_at.desc(), FeedEvent.id.desc())
        .limit(limit)
        .all()
    )
    if membership.role == FamilyRole.supporter:
        events = filter_events_for_supporter(db, events)

    # Batch the at-a-glance tallies so the feed is never N+1.
    event_ids = [e.id for e in events]
    reactions = reaction_summaries(db, ReactionTargetType.feed_event, event_ids, user.id)
    counts = comment_counts(db, event_ids)

    return [
        FeedEventOut(
            id=e.id,
            type=e.type,
            child_id=e.child_id,
            actor_name=e.actor.display_name,
            payload=e.payload,
            created_at=e.created_at,
            reactions=reactions.get(e.id, []),
            comment_count=counts.get(e.id, 0),
        )
        for e in events
    ]
