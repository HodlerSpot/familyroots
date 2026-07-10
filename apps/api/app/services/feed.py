"""Feed event emission.

Every meaningful domain action emits a feed event — the Family Feed is the
heartbeat of the product. Central helper so event shape stays consistent.
"""

import uuid

from sqlalchemy.orm import Session

from ..models import FeedEvent, FeedEventType


def emit(
    db: Session,
    *,
    family_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    type: FeedEventType,
    child_id: uuid.UUID | None = None,
    payload: dict | None = None,
) -> FeedEvent:
    event = FeedEvent(
        family_id=family_id,
        child_id=child_id,
        type=type,
        actor_user_id=actor_user_id,
        payload=payload or {},
    )
    db.add(event)
    return event
