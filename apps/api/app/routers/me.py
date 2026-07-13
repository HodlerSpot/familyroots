"""The signed-in user's own cross-family views: notification switches and a
history of their contributions."""

from fastapi import APIRouter

from ..deps import CurrentUser, DbSession
from ..models import Child, Contribution, Family, NotificationPreference
from ..schemas import MyContributionOut, NotificationPrefs
from ..services.notifications import DEFAULT_PREFS

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/notifications", response_model=NotificationPrefs)
def get_notification_prefs(db: DbSession, user: CurrentUser) -> NotificationPrefs:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    if pref is None:
        return NotificationPrefs(**DEFAULT_PREFS)
    return NotificationPrefs.model_validate(pref, from_attributes=True)


@router.put("/notifications", response_model=NotificationPrefs)
def set_notification_prefs(
    payload: NotificationPrefs, db: DbSession, user: CurrentUser
) -> NotificationPrefs:
    pref = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    if pref is None:
        pref = NotificationPreference(user_id=user.id)
        db.add(pref)
    pref.email_new_member = payload.email_new_member
    pref.email_milestone = payload.email_milestone
    pref.email_memory = payload.email_memory
    pref.email_legacy = payload.email_legacy
    db.commit()
    return NotificationPrefs.model_validate(pref, from_attributes=True)


@router.get("/contributions", response_model=list[MyContributionOut])
def my_contributions(db: DbSession, user: CurrentUser) -> list[MyContributionOut]:
    rows = (
        db.query(Contribution, Child, Family)
        .join(Child, Contribution.child_id == Child.id)
        .join(Family, Child.family_id == Family.id)
        .filter(Contribution.contributor_user_id == user.id)
        .order_by(Contribution.created_at.desc(), Contribution.id.desc())
        .all()
    )
    return [
        MyContributionOut(
            id=contribution.id,
            child_name=child.first_name,
            family_name=family.name,
            amount_cents=contribution.amount_cents,
            currency=contribution.currency,
            status=contribution.status,
            refunded_cents=contribution.refunded_cents,
            message=contribution.message,
            created_at=contribution.created_at,
        )
        for contribution, child, family in rows
    ]
