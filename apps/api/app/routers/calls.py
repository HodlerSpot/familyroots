"""Family Video Call — a family-only "living room" over Agora RTC.

At most one active call per family at a time (DB-guarded by the unique
active_family_id). Presence is heartbeat-driven: a participant is "present"
while their last_seen_at is within agora_presence_ttl_seconds. Stale
participants are reaped on every read/write, and the call auto-ends when the
last person drops.

Deliberate design choices, per spec:
- Supporters are excluded (family-only). Every endpoint gates with
  require_not_supporter.
- No A/V is recorded or stored, and calls emit NO feed events.
- The client never picks the channel or its Agora uid — the server assigns
  both. The App Certificate never leaves the server (see services/agora).
"""

import secrets
import uuid
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..deps import CurrentUser, DbSession, get_active_membership, require_not_supporter
from ..models import (
    CallChildPresence,
    CallParticipant,
    CallStatus,
    Child,
    FamilyCall,
    PlannedCall,
    User,
    utcnow,
)
from ..schemas import (
    CallJoinOut,
    CallChildPresenceOut,
    CallParticipantOut,
    CallStateOut,
    CallTokenOut,
    ChildrenPresenceSet,
    PlannedCallOut,
    PlannedCallSet,
)
from ..services.agora.tokens import mint_rtc_token
from ..services.entitlements import Capability, require_capability
from ..services.maintenance import call_is_abandoned
from ..services.notify import (
    EmailPayload,
    NotificationKind,
    family_recipients,
    notify,
)
from ..services.email_templates import render_email
from ..testnet.service import award

router = APIRouter(prefix="/families/{family_id}/call", tags=["call"])

MAX_UID_RETRIES = 10


# --- time helpers (SQLite drops tz in tests; normalize to aware UTC) ---

def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _presence_cutoff(now=None):
    now = now or utcnow()
    return now - timedelta(seconds=settings.agora_presence_ttl_seconds)


def _is_present(p: CallParticipant, cutoff) -> bool:
    return p.left_at is None and _aware(p.last_seen_at) >= cutoff


# --- call lookup / lifecycle ---

def _active_call(db, family_id: uuid.UUID) -> FamilyCall | None:
    call = (
        db.query(FamilyCall)
        .filter(FamilyCall.family_id == family_id, FamilyCall.status == CallStatus.active)
        .first()
    )
    if call is not None and call_is_abandoned(db, call):
        # Elapsed-time cap: no heartbeat for CALL_ABANDONED_AFTER means the
        # call was abandoned (nobody polled it, so the lazy reap never ran).
        # Persist the end the moment anyone observes the call; the daily
        # maintenance command applies the same cap to calls nobody observes.
        _end_call(db, call)
        db.commit()
        return None
    return call


def _end_call(db, call: FamilyCall) -> None:
    """Idempotent: only flips a still-active call to ended, releasing the
    one-active-call slot (active_family_id -> NULL)."""
    db.query(FamilyCall).filter(
        FamilyCall.id == call.id, FamilyCall.status == CallStatus.active
    ).update(
        {
            FamilyCall.status: CallStatus.ended,
            FamilyCall.active_family_id: None,
            FamilyCall.ended_at: utcnow(),
        },
        synchronize_session=False,
    )
    # Nothing about a child's presence outlives the call: clear every attested
    # child on this call, regardless of who marked them (data minimization).
    db.query(CallChildPresence).filter(CallChildPresence.call_id == call.id).delete(
        synchronize_session=False
    )


def _reap(db, call: FamilyCall) -> None:
    """Stamp left_at on stale participants, drop the child-presence rows they
    marked, and auto-end the call once nobody is present (or it's a very old,
    empty call). Flushes so callers can re-read a fresh active-call state."""
    now = utcnow()
    cutoff = _presence_cutoff(now)
    live = (
        db.query(CallParticipant)
        .filter(CallParticipant.call_id == call.id, CallParticipant.left_at.is_(None))
        .all()
    )
    stale_user_ids: list[uuid.UUID] = []
    present_count = 0
    for p in live:
        if _aware(p.last_seen_at) < cutoff:
            p.left_at = now
            stale_user_ids.append(p.user_id)
        else:
            present_count += 1
    if stale_user_ids:
        db.query(CallChildPresence).filter(
            CallChildPresence.call_id == call.id,
            CallChildPresence.marked_by.in_(stale_user_ids),
        ).delete(synchronize_session=False)
    db.flush()
    # Nobody present -> end. (Abandoned calls nobody reads at all are capped
    # by _active_call's elapsed-time check and the daily maintenance sweep.)
    if present_count == 0:
        _end_call(db, call)


# --- participants ---

def _assign_uid(db, call: FamilyCall) -> int:
    """A random 31-bit Agora uid, unique within the call (retry on clash)."""
    for _ in range(MAX_UID_RETRIES):
        uid = secrets.randbelow(2**31 - 1) + 1
        clash = (
            db.query(CallParticipant)
            .filter(CallParticipant.call_id == call.id, CallParticipant.agora_uid == uid)
            .first()
        )
        if clash is None:
            return uid
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, "Couldn't join the call. Please try again"
    )


def _present_participant(db, call: FamilyCall | None, user: User) -> CallParticipant | None:
    if call is None:
        return None
    p = (
        db.query(CallParticipant)
        .filter(CallParticipant.call_id == call.id, CallParticipant.user_id == user.id)
        .first()
    )
    if p is None or not _is_present(p, _presence_cutoff()):
        return None
    return p


def _join_or_create(db, family_id: uuid.UUID, user: User) -> tuple[FamilyCall, bool]:
    """Reap the current call first, then reuse the live one or start a fresh
    one. The unique active-call constraint resolves any create race: the loser
    rolls back and re-reads the winner."""
    call = _active_call(db, family_id)
    if call is not None:
        _reap(db, call)
        call = _active_call(db, family_id)
    if call is not None:
        return call, False

    call = FamilyCall(
        family_id=family_id,
        active_family_id=family_id,
        channel_name="fr-" + secrets.token_hex(16),
        started_by=user.id,
    )
    db.add(call)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        call = _active_call(db, family_id)
        if call is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Couldn't join the call. Please try again"
            )
        return call, False
    return call, True


def _upsert_participant(db, call: FamilyCall, user: User) -> CallParticipant:
    now = utcnow()
    p = (
        db.query(CallParticipant)
        .filter(CallParticipant.call_id == call.id, CallParticipant.user_id == user.id)
        .first()
    )
    if p is None:
        p = CallParticipant(
            call_id=call.id,
            user_id=user.id,
            agora_uid=_assign_uid(db, call),  # stable for the life of the call
            joined_at=now,
            last_seen_at=now,
        )
        db.add(p)
    else:
        p.left_at = None  # rejoining
        p.last_seen_at = now
    db.flush()
    return p


# --- serialization ---

def _planned_out(db, family_id: uuid.UUID) -> PlannedCallOut | None:
    planned = (
        db.query(PlannedCall).filter(PlannedCall.family_id == family_id).first()
    )
    if planned is None:
        return None
    setter = db.get(User, planned.set_by)
    return PlannedCallOut(
        id=planned.id,
        scheduled_for=planned.scheduled_for,
        note=planned.note,
        set_by=planned.set_by,
        set_by_name=setter.display_name if setter else "",
        updated_at=planned.updated_at,
    )


def _call_state(db, family_id: uuid.UUID, user: User, call: FamilyCall | None) -> CallStateOut:
    planned = _planned_out(db, family_id)
    if call is None or call.status != CallStatus.active:
        return CallStateOut(active=False, planned_call=planned)

    cutoff = _presence_cutoff()
    participants = [
        CallParticipantOut(
            user_id=p.user_id,
            display_name=p.user.display_name,
            agora_uid=p.agora_uid,
            avatar_media_id=p.user.avatar_media_id,
            is_you=(p.user_id == user.id),
        )
        for p in db.query(CallParticipant).filter(CallParticipant.call_id == call.id).all()
        if _is_present(p, cutoff)
    ]

    children_present: list[CallChildPresenceOut] = []
    for cp in db.query(CallChildPresence).filter(CallChildPresence.call_id == call.id).all():
        child = db.get(Child, cp.child_id)
        if child is None:
            continue
        children_present.append(
            CallChildPresenceOut(
                child_id=cp.child_id,
                first_name=child.first_name,
                avatar_media_id=child.avatar_media_id,
                marked_by=cp.marked_by,
            )
        )

    return CallStateOut(
        active=True,
        call_id=call.id,
        channel_name=call.channel_name,
        started_at=call.started_at,
        participants=participants,
        children_present=children_present,
        planned_call=planned,
    )


def _gate(db, family_id: uuid.UUID, user: User) -> None:
    """Family-only: an active member who isn't a supporter."""
    membership = get_active_membership(db, family_id, user)
    require_not_supporter(membership)


def _gate_premium(db, family_id: uuid.UUID, user: User) -> None:
    """Family Video Call is a Premium capability. Applied to join/token/
    heartbeat/children/planned-set — but deliberately NOT to call_state,
    get_planned, clear_planned, or leave_call: reads and a graceful exit must
    always work, so a family downgraded mid-call can see state and leave
    cleanly (the gated token refresh ends their media within the token TTL,
    and heartbeat gating expires their presence)."""
    _gate(db, family_id, user)
    require_capability(db, family_id, Capability.family_video_call)


def _notify_call_started(db, family_id: uuid.UUID, starter: User):
    """Stage the call_live notification for the family (excl. the starter,
    supporters excluded). Bell + push always/by-pref; email is opt-in and
    honest that it may already be over (copy deck §2.2)."""
    recipients = family_recipients(db, family_id, exclude_user_id=starter.id)
    family_url = f"/family/{family_id}"

    def email_builder(user: User) -> EmailPayload:
        return EmailPayload(
            subject=f"{starter.display_name} started a family call",
            body=(
                f"Hi {user.display_name},\n\n"
                f"{starter.display_name} started a family video call a little while "
                f"ago. By the time you read this, it may already be over, but if the "
                f"family's still gathered, there's room for you too.\n\n"
                f"Either way, it's always lovely when everyone finds a moment to "
                f"connect.\n\n"
                f"Join if it's still going: {settings.web_base_url}{family_url}\n\n"
                f"With warmth,\nThe FutureRoots team"
            ),
            html=render_email(
                preheader="The family gathered on a call. It might still be going.",
                greeting=f"Hi {user.display_name},",
                paragraphs=[
                    f"{starter.display_name} started a family video call a little "
                    f"while ago. By the time you read this, it may already be over, "
                    f"but if the family's still gathered, there's room for you too.",
                    "Either way, it's always lovely when everyone finds a moment to "
                    "connect.",
                ],
                cta_label="Join if it's still going",
                cta_url=f"{settings.web_base_url}{family_url}",
            ),
        )

    return notify(
        db,
        kind=NotificationKind.call_live,
        recipients=recipients,
        title=f"{starter.display_name} started a family call",
        body="Tap in now. The family's together and would love to see you.",
        url=family_url,
        family_id=family_id,
        email_builder=email_builder,
    )


# --- endpoints ---

@router.post("/join", response_model=CallJoinOut)
def join_call(
    family_id: uuid.UUID, db: DbSession, user: CurrentUser, response: Response
) -> CallJoinOut:
    """Join the family's single active call, creating it if none is live."""
    _gate_premium(db, family_id, user)
    call, created = _join_or_create(db, family_id, user)
    participant = _upsert_participant(db, call, user)
    # Token is minted only after authz + participant assignment.
    token, expires_at = mint_rtc_token(
        call.channel_name, participant.agora_uid, settings.agora_call_token_ttl_seconds
    )
    # A brand-new call rings the family (bell + push + opt-in email). Calls
    # deliberately emit NO feed event; this notification is the only signal.
    batch = _notify_call_started(db, family_id, user) if created else None
    # Testnet points (no-op in the family product): a call is only a genuine
    # multi-actor test once at least two people are present together, so the
    # award fires only when this join brings the live count to >= 2.
    cutoff = _presence_cutoff()
    present_count = sum(
        1
        for p in db.query(CallParticipant).filter(CallParticipant.call_id == call.id).all()
        if _is_present(p, cutoff)
    )
    if present_count >= 2:
        award(db, user.id, "call_joined")
    db.commit()
    if batch is not None:
        batch.deliver(db)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return CallJoinOut(
        app_id=settings.agora_app_id,
        channel_name=call.channel_name,
        token=token,
        agora_uid=participant.agora_uid,
        expires_at=expires_at,
        call=_call_state(db, family_id, user, call),
    )


@router.get("", response_model=CallStateOut)
def call_state(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallStateOut:
    """Current call state — never returns a token or the certificate."""
    _gate(db, family_id, user)
    call = _active_call(db, family_id)
    if call is not None:
        _reap(db, call)
        db.commit()
        call = _active_call(db, family_id)
    return _call_state(db, family_id, user, call)


@router.post("/heartbeat", response_model=CallStateOut)
def heartbeat(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallStateOut:
    """Keep the caller marked present. 409 if they aren't in the call."""
    _gate_premium(db, family_id, user)
    call = _active_call(db, family_id)
    participant = _present_participant(db, call, user)
    if participant is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You're not in this call")
    participant.last_seen_at = utcnow()
    db.flush()
    _reap(db, call)
    db.commit()
    return _call_state(db, family_id, user, _active_call(db, family_id))


@router.post("/leave", response_model=CallStateOut)
def leave_call(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallStateOut:
    """Leave the call; if the room empties, the call ends."""
    _gate(db, family_id, user)
    call = _active_call(db, family_id)
    if call is not None:
        p = (
            db.query(CallParticipant)
            .filter(
                CallParticipant.call_id == call.id,
                CallParticipant.user_id == user.id,
                CallParticipant.left_at.is_(None),
            )
            .first()
        )
        if p is not None:
            p.left_at = utcnow()
            # Drop the children this member had flagged present.
            db.query(CallChildPresence).filter(
                CallChildPresence.call_id == call.id,
                CallChildPresence.marked_by == user.id,
            ).delete(synchronize_session=False)
        db.flush()
        _reap(db, call)
        db.commit()
        call = _active_call(db, family_id)
    return _call_state(db, family_id, user, call)


@router.put("/children", response_model=CallStateOut)
def set_children_present(
    family_id: uuid.UUID, payload: ChildrenPresenceSet, db: DbSession, user: CurrentUser
) -> CallStateOut:
    """Replace the set of children flagged as present on the active call."""
    _gate_premium(db, family_id, user)
    call = _active_call(db, family_id)
    if call is not None:
        _reap(db, call)
        db.flush()
        call = _active_call(db, family_id)
    if call is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "There's no active call to update")
    # Only someone actually in the call may attest who's in the room with them.
    # (This also stops a non-participant from leaving orphaned presence rows.)
    if _present_participant(db, call, user) is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Join the call first to say who's here"
        )

    child_ids = list(dict.fromkeys(payload.child_ids))  # de-dupe, keep order
    for cid in child_ids:
        child = db.get(Child, cid)
        # Reject cross-family children (IDOR); never leak existence -> 404.
        if child is None or child.family_id != family_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")

    db.query(CallChildPresence).filter(CallChildPresence.call_id == call.id).delete(
        synchronize_session=False
    )
    for cid in child_ids:
        db.add(CallChildPresence(call_id=call.id, child_id=cid, marked_by=user.id))
    db.commit()
    return _call_state(db, family_id, user, _active_call(db, family_id))


@router.post("/token", response_model=CallTokenOut)
def refresh_token(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CallTokenOut:
    """Re-mint the caller's token (Agora token-expiry renewal). Requires a
    present participant in an active call."""
    _gate_premium(db, family_id, user)
    call = _active_call(db, family_id)
    if call is not None:
        _reap(db, call)
        db.commit()
        call = _active_call(db, family_id)
    participant = _present_participant(db, call, user)
    if participant is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "You're not in this call")
    token, expires_at = mint_rtc_token(
        call.channel_name, participant.agora_uid, settings.agora_call_token_ttl_seconds
    )
    return CallTokenOut(
        app_id=settings.agora_app_id,
        channel_name=call.channel_name,
        token=token,
        agora_uid=participant.agora_uid,
        expires_at=expires_at,
    )


# --- planned call ---

@router.get("/planned", response_model=PlannedCallOut | None)
def get_planned(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> PlannedCallOut | None:
    _gate(db, family_id, user)
    return _planned_out(db, family_id)


@router.put("/planned", response_model=PlannedCallOut)
def set_planned(
    family_id: uuid.UUID, payload: PlannedCallSet, db: DbSession, user: CurrentUser
) -> PlannedCallOut:
    """Upsert the family's single next planned call. Any non-supporter member
    may set it."""
    _gate_premium(db, family_id, user)
    planned = db.query(PlannedCall).filter(PlannedCall.family_id == family_id).first()
    if planned is None:
        planned = PlannedCall(
            family_id=family_id,
            scheduled_for=payload.scheduled_for,
            note=payload.note,
            set_by=user.id,
        )
        db.add(planned)
    else:
        planned.scheduled_for = payload.scheduled_for
        planned.note = payload.note
        planned.set_by = user.id
        planned.updated_at = utcnow()
    db.commit()
    return _planned_out(db, family_id)


@router.delete("/planned", status_code=status.HTTP_204_NO_CONTENT)
def clear_planned(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    _gate(db, family_id, user)
    db.query(PlannedCall).filter(PlannedCall.family_id == family_id).delete(
        synchronize_session=False
    )
    db.commit()
