"""Per-member email fan-out, gated by each recipient's notification switches.

A missing NotificationPreference row means the product defaults below (new
member + milestone on; memory + legacy off). notify_members is the one place
domain code fans an email out to a family, so the gating stays consistent.
"""

from sqlalchemy.orm import Session

from ..models import FamilyMember, FamilyRole, MemberStatus, NotificationPreference, User
from .email import get_email_sender

# Defaults for a user who has never touched their preferences. Mirrors the
# column defaults on NotificationPreference (which only apply on flush).
DEFAULT_PREFS = {
    "email_new_member": True,
    "email_milestone": True,
    "email_memory": False,
    "email_legacy": False,
}


def notify_members(
    db: Session,
    family_id,
    pref_attr: str,
    *,
    subject: str,
    body: str,
    html: str | None = None,
    exclude_user_id=None,
) -> None:
    """Email every active member of the family who has `pref_attr` enabled.

    Supporters are deliberately never emailed: they are non-family adults with a
    deliberately narrow, in-app-only view (shared memories/milestones). Every
    fan-out here carries family content they must not receive out of band.
    """
    query = (
        db.query(User, NotificationPreference)
        .join(FamilyMember, FamilyMember.user_id == User.id)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.status == MemberStatus.active,
            FamilyMember.role != FamilyRole.supporter,
        )
    )
    if exclude_user_id is not None:
        query = query.filter(User.id != exclude_user_id)

    sender = get_email_sender()
    for user, pref in query.all():
        enabled = getattr(pref, pref_attr) if pref is not None else DEFAULT_PREFS[pref_attr]
        if enabled:
            sender.send(to=user.email, subject=subject, body=body, html=html)
