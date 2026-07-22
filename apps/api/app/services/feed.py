"""Feed event emission.

Every meaningful domain action emits a feed event — the Family Feed is the
heartbeat of the product. Central helper so event shape stays consistent.
"""

import uuid

from sqlalchemy.orm import Session

from ..models import FeedEvent, FeedEventType
from ..testnet.service import award

# Feed events are the natural testnet award hooks: every meaningful action
# already emits one. No-op outside testnet mode (docs/testnet.md).
# capsule_released is emitted with the capsule's creator as actor, so the
# sealer earns the release; member_joined's actor is the accepting invitee.
_TESTNET_ACTIONS = {
    FeedEventType.milestone: "milestone",
    FeedEventType.memory_added: "memory_added",
    FeedEventType.achievement: "achievement",
    FeedEventType.contribution: "contribution",
    FeedEventType.capsule_created: "capsule_created",
    FeedEventType.capsule_released: "capsule_released",
    FeedEventType.member_joined: "invite_accepted",
    # Prod features that shipped after the harness landed (fund/predictions/
    # premium emit their own feed events; the actor is the tester who acted:
    # the fund's setter, the prediction's author, the round's child creator,
    # and the subscription's owner respectively).
    FeedEventType.fund_activated: "fund_activated",
    FeedEventType.prediction_added: "prediction_added",
    FeedEventType.predictions_sealed: "predictions_sealed",
    FeedEventType.predictions_released: "predictions_released",
    FeedEventType.premium_activated: "premium_activated",
}


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
    action = _TESTNET_ACTIONS.get(type)
    if action is not None:
        award(db, actor_user_id, action)
    return event
