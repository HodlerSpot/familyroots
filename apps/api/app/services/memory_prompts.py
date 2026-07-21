"""Memory Request — the monthly "add a memory" ritual.

Once per calendar (UTC) month each active, non-supporter family member is
gently nudged to add a memory for the family's rotating **child of the
month**. Anyone who has already added a memory this month is skipped (the goal
is anti-nag, not per-child bookkeeping).

Two surfaces, one deterministic rule:
- the **card** is computed on read (`routers/families.memory_prompt`);
- the **notification** (bell + push + email) is sent by the daily maintenance
  sweep via ``run_memory_prompts`` below.

``run_memory_prompts`` is system-initiated but follows the FundNudge idiom
exactly: claim a ``memory_prompts`` row (the unique constraint makes it
race-safe and exactly-once per member/family/month), stage a ``notify`` batch,
commit, then deliver post-commit. Safe to run daily — idempotent, and it also
catches members who joined mid-month.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Child, Family, MemoryPrompt, User, VaultItem, utcnow
from .email_templates import render_email
from .notify import (
    EmailPayload,
    NotificationKind,
    Recipient,
    family_recipients,
    notify,
)

logger = logging.getLogger(__name__)


def period_for(now: datetime) -> str:
    """The UTC calendar-month key, "YYYY-MM"."""
    return f"{now.year:04d}-{now.month:02d}"


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """[start, end) of the UTC calendar month containing ``now``."""
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def active_children(db: Session, family_id: uuid.UUID) -> list[Child]:
    """A family's children in a stable order (created_at, id). There is no
    child archive concept, so every child is 'active'."""
    return (
        db.query(Child)
        .filter(Child.family_id == family_id)
        .order_by(Child.created_at, Child.id)
        .all()
    )


def child_of_the_month(children: list[Child], now: datetime) -> Child | None:
    """Deterministic rotation, no state: the card and the sweep always agree.
    A 1-child family always gets that child; 0 children → None."""
    if not children:
        return None
    idx = (now.year * 12 + (now.month - 1)) % len(children)
    return children[idx]


def has_added_memory_this_month(
    db: Session, family_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> bool:
    """True when the user has any non-deleted VaultItem on a child of this
    family created in the current UTC month — the anti-nag satisfy check."""
    start, end = _month_bounds(now)
    return (
        db.query(VaultItem.id)
        .join(Child, Child.id == VaultItem.child_id)
        .filter(
            Child.family_id == family_id,
            VaultItem.created_by == user_id,
            VaultItem.deleted_at.is_(None),
            VaultItem.created_at >= start,
            VaultItem.created_at < end,
        )
        .first()
        is not None
    )


def _claim(
    db: Session,
    *,
    user_id: uuid.UUID,
    family_id: uuid.UUID,
    child_id: uuid.UUID,
    period: str,
) -> bool:
    """Claim the once-per-month throttle row for a member. Returns True if this
    call won the claim, False if a row already exists (or a concurrent run won
    the race). Mirrors the FundNudge unique-constraint + IntegrityError-rescue;
    the claim is flushed BEFORE anything else is staged, so a lost race rolls
    back only the claim."""
    db.add(
        MemoryPrompt(
            user_id=user_id,
            family_id=family_id,
            child_id=child_id,
            period=period,
        )
    )
    try:
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _stage_prompt(
    db: Session, recipient: Recipient, family_id: uuid.UUID, child: Child
):
    """Stage the memory_request notification for one member (bell always; push
    and email pref-gated). No feed event — a personal reminder is not a family
    occurrence."""
    child_url = f"/family/{family_id}/child/{child.id}"

    def email_builder(user: User) -> EmailPayload:
        greeting = f"Hi {user.display_name},"
        return EmailPayload(
            subject=f"Share a memory for {child.first_name} this month",
            body=(
                f"{greeting}\n\n"
                f"This month, {child.first_name} is your family's memory keeper. "
                f"Is there a moment, a photo, or a few words you'd like to add to "
                f"{child.first_name}'s vault?\n\n"
                f"Even something small becomes part of the story {child.first_name} "
                f"will treasure one day.\n\n"
                f"Add a memory for {child.first_name}: "
                f"{settings.web_base_url}{child_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader=f"Add a memory for {child.first_name} this month.",
                greeting=greeting,
                paragraphs=[
                    f"This month, {child.first_name} is your family's memory "
                    f"keeper. Is there a moment, a photo, or a few words you'd "
                    f"like to add to {child.first_name}'s vault?",
                    f"Even something small becomes part of the story "
                    f"{child.first_name} will treasure one day.",
                ],
                cta_label=f"Add a memory for {child.first_name}",
                cta_url=f"{settings.web_base_url}{child_url}",
            ),
        )

    return notify(
        db,
        kind=NotificationKind.memory_request,
        recipients=[recipient],
        title=f"Share a memory for {child.first_name}",
        body=f"It's {child.first_name}'s month. Add a memory to their vault?",
        url=child_url,
        family_id=family_id,
        email_builder=email_builder,
    )


def run_memory_prompts(db: Session) -> int:
    """The monthly sweep step. For every family with children, resolve the
    child of the month and prompt each active, non-supporter member who hasn't
    already been prompted this month and hasn't already added a memory this
    month. Returns the number of prompts sent (bell rows written)."""
    now = utcnow()
    period = period_for(now)
    sent = 0

    families = db.query(Family).all()
    for family in families:
        children = active_children(db, family.id)
        child = child_of_the_month(children, now)
        if child is None:
            continue
        for recipient in family_recipients(db, family.id):  # supporters excluded
            user, _pref = recipient
            if has_added_memory_this_month(db, family.id, user.id, now):
                continue
            if not _claim(
                db,
                user_id=user.id,
                family_id=family.id,
                child_id=child.id,
                period=period,
            ):
                continue  # already prompted this member this month
            # The claim is durable before any interrupting channel leaves
            # (send-after-commit, same discipline as contribution settlement).
            batch = _stage_prompt(db, recipient, family.id, child)
            db.commit()
            batch.deliver(db)
            sent += 1

    return sent
