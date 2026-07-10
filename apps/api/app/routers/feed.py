import uuid

from fastapi import APIRouter, Query

from ..deps import CurrentUser, DbSession, get_active_membership
from ..models import FeedEvent
from ..schemas import FeedEventOut

router = APIRouter(tags=["feed"])


@router.get("/families/{family_id}/feed", response_model=list[FeedEventOut])
def family_feed(
    family_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, le=100),
) -> list[FeedEventOut]:
    get_active_membership(db, family_id, user)
    events = (
        db.query(FeedEvent)
        .filter(FeedEvent.family_id == family_id)
        .order_by(FeedEvent.created_at.desc(), FeedEvent.id.desc())
        .limit(limit)
        .all()
    )
    return [
        FeedEventOut(
            id=e.id,
            type=e.type,
            child_id=e.child_id,
            actor_name=e.actor.display_name,
            payload=e.payload,
            created_at=e.created_at,
        )
        for e in events
    ]
