"""Account/child/family erasure + DSAR export endpoints (compliance WS5).

Erasure is destructive and irreversible, so every DELETE requires a STEP-UP
re-auth (the caller re-supplies their password) on top of a live session —
a stolen access token alone can never trigger one. Standing is enforced
server-side per runbook §1/§2:

- member-only: any authenticated user, on themselves (DELETE /me).
- child-profile: a parent/guardian of THAT child (a child_relationships edge).
- whole-family: the SOLE active parent (the runbook's option (b); the
  all-active-parent-consent flow, option (a), is not built — a family with more
  than one active parent must reduce to one, or use per-member erasure).

Each erasure auto-generates the §6 erasure-log entry from the transaction (a
structured log line kept OUT of the production DB, per the runbook) and returns
that receipt. Exports are read-only (no step-up) and return a machine-readable
JSON bundle + a manifest of the subject's media the caller may fetch."""

import logging
import uuid

from fastapi import APIRouter, HTTPException, status

from ..deps import (
    CurrentUser,
    DbSession,
    get_active_membership,
    get_child_with_access,
    get_family_or_404,
    require_parent_role,
)
from ..models import Child, ChildRelationship, FamilyMember, FamilyRole, MemberStatus
from ..schemas import StepUpRequest
from ..security import verify_password
from ..services import erasure as erasure_service
from ..services import export as export_service

logger = logging.getLogger("futureroots.erasure")

router = APIRouter(tags=["account"])

_GUARDIAN_TYPES = (FamilyRole.parent, FamilyRole.guardian)


def _require_step_up(user, payload: StepUpRequest) -> None:
    """Re-authentication gate for a destructive action. 403 on a wrong password
    (deliberately not 401 — the session is valid; the step-up is what failed)."""
    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Please re-enter your current password to confirm this.",
        )


def _require_child_guardian(db, child_id: uuid.UUID, user) -> Child:
    """Standing for a child-scoped request (§1): an active family membership AND
    a parent/guardian child_relationships edge to THAT child."""
    child, _ = get_child_with_access(db, child_id, user)  # 404s a non-member
    edge = (
        db.query(ChildRelationship)
        .filter(
            ChildRelationship.child_id == child_id,
            ChildRelationship.user_id == user.id,
            ChildRelationship.relationship_type.in_(_GUARDIAN_TYPES),
        )
        .first()
    )
    if edge is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a parent or guardian of this child can do that.",
        )
    return child


def _require_sole_parent(db, family_id: uuid.UUID) -> None:
    """Standing for a whole-family request (§1, option b)."""
    active_parents = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role == FamilyRole.parent,
        )
        .count()
    )
    if active_parents > 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This family has more than one parent. Every active parent must "
            "agree to erase it — remove the other parents first, or ask them to "
            "leave, then try again.",
        )


# --- DSAR export (read-only) -------------------------------------------------


@router.post("/me/data-export")
def export_my_data(db: DbSession, user: CurrentUser) -> dict:
    """Member-only DSAR export (GDPR Art. 15/20): the caller's own data."""
    return export_service.export_member(db, user)


@router.post("/families/{family_id}/children/{child_id}/data-export")
def export_child_data(
    family_id: uuid.UUID, child_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> dict:
    child = _require_child_guardian(db, child_id, user)
    if child.family_id != family_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")
    return export_service.export_child(db, child, requester_id=user.id)


@router.post("/families/{family_id}/data-export")
def export_family_data(family_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    family = get_family_or_404(db, family_id)
    return export_service.export_family(db, family, requester_id=user.id)


# --- erasure (destructive; step-up required) ---------------------------------


def _finish(db, receipt, effects) -> dict:
    # Commit the DB transaction FIRST, THEN run the collected external side
    # effects (S3 byte deletion, Stripe calls, emails). This ordering is the H1
    # fix: a mid-erase failure rolls back to "nothing happened" and never leaves
    # deleted bytes / phantom Stripe calls behind surviving DB rows.
    db.commit()
    effects.run()
    logger.info("erasure completed: %s", receipt.as_log())
    return receipt.as_log()


@router.delete("/me")
def erase_my_account(payload: StepUpRequest, db: DbSession, user: CurrentUser) -> dict:
    """Member-only erasure of the caller's own account (§3.A)."""
    _require_step_up(user, payload)
    try:
        receipt, effects = erasure_service.erase_member(db, user.id)
    except erasure_service.ErasureBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    return _finish(db, receipt, effects)


@router.delete("/families/{family_id}/children/{child_id}")
def erase_child_profile(
    family_id: uuid.UUID,
    child_id: uuid.UUID,
    payload: StepUpRequest,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    """Child-profile erasure (§3.B). Parent/guardian of that child only."""
    child = _require_child_guardian(db, child_id, user)
    if child.family_id != family_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")
    _require_step_up(user, payload)
    receipt, effects = erasure_service.erase_child(db, child_id)
    return _finish(db, receipt, effects)


@router.delete("/families/{family_id}")
def erase_whole_family(
    family_id: uuid.UUID, payload: StepUpRequest, db: DbSession, user: CurrentUser
) -> dict:
    """Whole-family erasure (§3.C). Sole active parent only."""
    membership = get_active_membership(db, family_id, user)
    require_parent_role(membership)
    _require_sole_parent(db, family_id)
    _require_step_up(user, payload)
    receipt, effects = erasure_service.erase_family(db, family_id)
    return _finish(db, receipt, effects)
