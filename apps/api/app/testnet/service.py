"""Testnet points engine — the single scoring path (docs/testnet.md).

Economy discipline mirrors the money rules:
- point events are append-only; totals are always derived (SUM)
- awards fire only from server-verified actions, inside the same transaction
  as the action itself (award never commits; it rides the caller's commit)
- every action has a cap, enforced by counting events, never stored counters
- the whole module is a no-op unless settings.testnet_mode is on
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PointEvent, Tester, utcnow


@dataclass(frozen=True)
class Quest:
    action: str
    label: str  # warm, family-brand quest name (user-facing)
    hint: str  # how to earn it (user-facing)
    points: int
    daily_cap: int  # per UTC day
    once: bool = False  # once ever, not once per day


# The catalog weights the north-star grandparent journey heaviest:
# invite a grandparent (150) -> they accept (125) -> they contribute (200).
# Repeatable low-effort actions score low. See docs/testnet.md.
QUESTS: tuple[Quest, ...] = (
    Quest("connect_wallet", "Join the testing crew", "Connect your wallet and sign in for the first time", 25, 1, once=True),
    Quest("set_display_name", "Pick your tester name", "Choose a display name in the quests panel", 10, 1, once=True),
    Quest("connect_x", "Bring your crew", "Connect your X account", 100, 1, once=True),
    Quest("create_family", "Plant your family tree", "Create a family space", 75, 2),
    Quest("add_child", "Start a child's vault", "Add a child profile to your family", 60, 3),
    Quest("invite_grandparent", "Invite a grandparent", "Send a family invitation with the grandparent role", 150, 5),
    Quest("invite_family", "Welcome more family", "Invite a relative or guardian to your family", 60, 5),
    Quest("invite_extended", "Bring in the extended family", "Invite an aunt, uncle, or cousin", 60, 5),
    Quest("invite_accepted", "Join a family", "Accept an invitation from another tester", 125, 3),
    Quest("milestone", "Share a milestone", "Post a milestone to a child's vault", 50, 5),
    Quest("fund_activated", "Open a future fund", "Set up a child's Future Fund so it's ready for gifts", 90, 3),
    Quest("contribution", "Grow a future fund", "Complete a contribution from start to finish", 200, 5),
    Quest("memory_added", "Tuck away a memory", "Add a photo, message, or memory to a vault", 30, 10),
    Quest("create_goal", "Set a goal", "Create a goal for a child", 40, 5),
    Quest("achievement", "Celebrate an achievement", "Mark a child's goal complete", 50, 5),
    Quest("prediction_added", "Make a prediction", "Add a prediction to a child's Book of Predictions", 40, 5),
    Quest("predictions_sealed", "Seal a year of predictions", "A birthday seals a round of predictions you helped fill", 60, 3),
    Quest("predictions_released", "Open the Book of Predictions", "A child's 18th birthday opens the predictions you sealed", 75, 3),
    Quest("capsule_created", "Seal a time capsule", "Seal a letter or recording for the future", 60, 3),
    Quest("capsule_released", "Open a time capsule", "A capsule you sealed gets released", 75, 3),
    Quest("legacy_added", "Add to the family archive", "Add a story, recipe, or document to the legacy archive", 30, 8),
    Quest("call_joined", "Gather on a family call", "Join a family video call while someone else is there too", 70, 3),
    Quest("premium_activated", "Unlock Premium", "Start a family Premium membership", 60, 2),
    Quest("bug_verified", "Squash a real bug", "Report a bug our team confirms is real", 250, 5),
)

QUESTS_BY_ACTION: dict[str, Quest] = {q.action: q for q in QUESTS}


def day_start_utc() -> datetime:
    return utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


def short_wallet(address: str) -> str:
    """ASCII-safe shortened wallet, e.g. 0xab12cd...89ef."""
    return f"{address[:6]}...{address[-4:]}"


def get_tester_for_user(db: Session, user_id: uuid.UUID) -> Tester | None:
    return db.query(Tester).filter(Tester.user_id == user_id).first()


def award(db: Session, user_id: uuid.UUID, action: str) -> None:
    """Record points for a server-verified action.

    Safe to call from any router or service: it is a no-op when testnet mode
    is off, when the acting user is not a wallet-linked tester, when the
    action is unknown, or when the action's cap is already reached. Never
    commits — points land only if the caller's transaction commits.
    """
    if not settings.testnet_mode:
        return
    quest = QUESTS_BY_ACTION.get(action)
    if quest is None:
        return
    tester = get_tester_for_user(db, user_id)
    if tester is None:
        return

    counted = db.query(func.count(PointEvent.id)).filter(
        PointEvent.tester_id == tester.id,
        PointEvent.action == action,
    )
    if not quest.once:
        counted = counted.filter(PointEvent.created_at >= day_start_utc())
    if counted.scalar() >= quest.daily_cap:
        return

    db.add(PointEvent(tester_id=tester.id, action=action, points=quest.points))
