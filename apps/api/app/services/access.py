"""Supporter visibility rules for the Family Feed.

A supporter (a trusted non-family adult) sees a deliberately narrow slice of
the family: shared memories and milestones, plus who has joined or left —
never contributions, achievements, funds, or capsules. These helpers are the
single source of truth for that rule so the feed, comments, and reactions all
agree.
"""

import uuid

from sqlalchemy.orm import Session

from ..models import FeedEvent, FeedEventType, VaultItem

# Event types that reference a vault item and can be shared with supporters.
SUPPORTER_VAULT_TYPES = {FeedEventType.memory_added, FeedEventType.milestone}

# Roster events every member may see — who joined, who left. Symmetric on
# purpose: a supporter who saw someone arrive shouldn't wonder forever.
SUPPORTER_ROSTER_TYPES = {FeedEventType.member_joined, FeedEventType.member_left}


def _event_vault_item_id(event: FeedEvent) -> uuid.UUID | None:
    raw = event.payload.get("vault_item_id") if event.payload else None
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError):
        return None


def event_visible_to_supporter(db: Session, event: FeedEvent) -> bool:
    """Whether one event should appear for a supporter (single-event check)."""
    if event.type in SUPPORTER_ROSTER_TYPES:
        return True
    if event.type in SUPPORTER_VAULT_TYPES:
        vault_item_id = _event_vault_item_id(event)
        if vault_item_id is None:
            return False
        item = db.get(VaultItem, vault_item_id)
        return bool(item and item.visible_to_supporters and item.deleted_at is None)
    return False


def filter_events_for_supporter(db: Session, events: list[FeedEvent]) -> list[FeedEvent]:
    """Batch version for the feed: one query resolves every referenced vault
    item's visibility (no per-event lookups)."""
    vault_item_ids = [
        vid
        for e in events
        if e.type in SUPPORTER_VAULT_TYPES
        and (vid := _event_vault_item_id(e)) is not None
    ]
    visible: set[uuid.UUID] = set()
    if vault_item_ids:
        rows = (
            db.query(VaultItem.id)
            .filter(
                VaultItem.id.in_(vault_item_ids),
                VaultItem.visible_to_supporters.is_(True),
                VaultItem.deleted_at.is_(None),
            )
            .all()
        )
        visible = {row[0] for row in rows}

    kept: list[FeedEvent] = []
    for e in events:
        if e.type in SUPPORTER_ROSTER_TYPES:
            kept.append(e)
        elif e.type in SUPPORTER_VAULT_TYPES:
            vid = _event_vault_item_id(e)
            if vid is not None and vid in visible:
                kept.append(e)
    return kept
