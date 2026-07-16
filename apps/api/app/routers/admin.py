"""Admin command center API.

Every route is gated by AdminUser (role == admin on the user record). This
console exposes sensitive data — children's profiles and money — so access is
role-restricted and consequential actions are written to admin_audit_log.

Mounted on both the family site and the testnet harness; each reads its own
database, so on the family site this shows real families and on testnet it
shows testers and their test data.
"""

import csv
import io
import json
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..deps import AdminUser, DbSession
from ..models import (
    AdminAuditLog,
    BugReport,
    Child,
    Contribution,
    ContributionStatus,
    Family,
    FamilyMember,
    FundAccount,
    FundLedgerEntry,
    MemberStatus,
    PremiumGrant,
    Tester,
    User,
    UserRole,
    utcnow,
)
from ..security import create_impersonation_token
from ..services.maintenance import prune_gift_intents as maintenance_prune_gift_intents
from ..services.payments import fund_balance_cents, reconcile_contribution, refund_contribution
from ..services.premium import reconcile_family_premium

router = APIRouter(prefix="/admin", tags=["admin"])


def _json_compact(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _audit(db, admin: User, action: str, target: str | None = None, detail: dict | None = None):
    db.add(
        AdminAuditLog(
            admin_user_id=admin.id, action=action, target=target, detail=detail or {}
        )
    )


# --- schemas ---

class OverviewOut(BaseModel):
    users: int
    admins: int
    families: int
    children: int
    contributors: int  # distinct users who have a succeeded contribution
    contributions: int  # count of succeeded contributions
    contributed_cents: int  # total settled into all fund ledgers
    pending_bugs: int
    recent_signups: list["MiniUser"]
    recent_contributions: list["MiniContribution"]


class MiniUser(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    role: UserRole
    disabled: bool = False
    created_at: datetime


class MiniContribution(BaseModel):
    id: uuid.UUID
    contributor_id: uuid.UUID | None
    contributor_name: str
    child_name: str
    amount_cents: int
    refunded_cents: int
    currency: str
    status: ContributionStatus
    provider_payment_id: str | None  # Stripe PaymentIntent id, for off-site tracing
    created_at: datetime


class AdminUserRow(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    role: UserRole
    disabled: bool
    family_count: int
    child_count: int
    created_at: datetime
    last_login_at: datetime | None


class AdminUserDetail(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    role: UserRole
    disabled: bool
    created_at: datetime
    families: list["FamilyRef"]
    contributions: list[MiniContribution]


class FamilyRef(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class AdminFamilyRow(BaseModel):
    id: uuid.UUID
    name: str
    member_count: int
    child_count: int
    fund_cents: int
    created_at: datetime


class AdminFamilyDetail(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    fund_cents: int
    max_upload_mb: int
    members: list["MemberRef"]
    children: list["ChildRef"]
    contributions: list[MiniContribution]


class MemberRef(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    status: str
    disabled: bool


class ChildRef(BaseModel):
    id: uuid.UUID
    first_name: str
    fund_cents: int
    # Connect account state — the admin console is the ONE surface where the
    # Stripe account id may appear (for off-site tracing in the dashboard).
    fund_account_status: str
    stripe_account_id: str | None


class AdminBugRow(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: str
    reporter: str
    media_id: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None


class RoleUpdate(BaseModel):
    role: UserRole


class AuditRow(BaseModel):
    id: uuid.UUID
    admin_name: str
    admin_email: str
    action: str
    target: str | None
    detail: dict
    created_at: datetime


class ImpersonationOut(BaseModel):
    access_token: str
    expires_in_minutes: int
    display_name: str
    email: str


class Page(BaseModel):
    total: int
    items: list


# --- helpers ---

def _fund_cents_for_child(db, child_id: uuid.UUID) -> int:
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    return fund_balance_cents(db, account.id) if account else 0


def _child_ref(db, child: Child) -> ChildRef:
    account = db.query(FundAccount).filter(FundAccount.child_id == child.id).first()
    return ChildRef(
        id=child.id,
        first_name=child.first_name,
        fund_cents=fund_balance_cents(db, account.id) if account else 0,
        fund_account_status=account.account_status.value if account else "none",
        stripe_account_id=account.stripe_account_id if account else None,
    )


def _mini_contribution(c: Contribution, contributor: User | None, child: Child | None) -> MiniContribution:
    return MiniContribution(
        id=c.id,
        contributor_id=c.contributor_user_id,
        contributor_name=contributor.display_name if contributor else "Unknown",
        child_name=child.first_name if child else "Unknown",
        amount_cents=c.amount_cents,
        refunded_cents=c.refunded_cents,
        currency=c.currency,
        status=c.status,
        provider_payment_id=c.provider_payment_id,
        created_at=c.created_at,
    )


# --- overview ---

@router.get("/overview", response_model=OverviewOut)
def overview(db: DbSession, admin: AdminUser) -> OverviewOut:
    users = db.query(func.count(User.id)).scalar()
    admins = db.query(func.count(User.id)).filter(User.role == UserRole.admin).scalar()
    families = db.query(func.count(Family.id)).scalar()
    children = db.query(func.count(Child.id)).scalar()
    succeeded = db.query(Contribution).filter(
        Contribution.status == ContributionStatus.succeeded
    )
    contributions = succeeded.count()
    contributors = (
        db.query(func.count(func.distinct(Contribution.contributor_user_id)))
        .filter(Contribution.status == ContributionStatus.succeeded)
        .scalar()
    )
    contributed_cents = db.query(
        func.coalesce(func.sum(FundLedgerEntry.amount_cents), 0)
    ).scalar()
    pending_bugs = db.query(func.count(BugReport.id)).filter(
        BugReport.status == "pending"
    ).scalar()

    recent_users = db.query(User).order_by(User.created_at.desc()).limit(8).all()
    recent_rows = (
        db.query(Contribution, User, Child)
        .outerjoin(User, Contribution.contributor_user_id == User.id)
        .outerjoin(Child, Contribution.child_id == Child.id)
        .filter(Contribution.status == ContributionStatus.succeeded)
        .order_by(Contribution.created_at.desc())
        .limit(8)
        .all()
    )
    return OverviewOut(
        users=users,
        admins=admins,
        families=families,
        children=children,
        contributors=contributors,
        contributions=contributions,
        contributed_cents=contributed_cents,
        pending_bugs=pending_bugs,
        recent_signups=[
            MiniUser(
                id=u.id, display_name=u.display_name, email=u.email, role=u.role,
                disabled=u.disabled, created_at=u.created_at,
            )
            for u in recent_users
        ],
        recent_contributions=[_mini_contribution(c, u, ch) for c, u, ch in recent_rows],
    )


# --- users ---

@router.get("/users", response_model=Page)
def list_users(
    db: DbSession,
    admin: AdminUser,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> Page:
    query = db.query(User)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(User.email).like(like) | func.lower(User.display_name).like(like)
        )
    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()
    rows = []
    for u in users:
        fam = db.query(func.count(FamilyMember.id)).filter(
            FamilyMember.user_id == u.id, FamilyMember.status == MemberStatus.active
        ).scalar()
        kids = db.query(func.count(Child.id)).join(
            FamilyMember, FamilyMember.family_id == Child.family_id
        ).filter(
            FamilyMember.user_id == u.id, FamilyMember.status == MemberStatus.active
        ).scalar()
        rows.append(
            AdminUserRow(
                id=u.id, display_name=u.display_name, email=u.email, role=u.role,
                disabled=u.disabled, family_count=fam, child_count=kids,
                created_at=u.created_at, last_login_at=u.last_login_at,
            )
        )
    return Page(total=total, items=rows)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def user_detail(user_id: uuid.UUID, db: DbSession, admin: AdminUser) -> AdminUserDetail:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    memberships = (
        db.query(Family, FamilyMember)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .filter(FamilyMember.user_id == u.id, FamilyMember.status == MemberStatus.active)
        .all()
    )
    contribs = (
        db.query(Contribution, Child)
        .outerjoin(Child, Contribution.child_id == Child.id)
        .filter(Contribution.contributor_user_id == u.id)
        .order_by(Contribution.created_at.desc())
        .limit(50)
        .all()
    )
    return AdminUserDetail(
        id=u.id, display_name=u.display_name, email=u.email, role=u.role,
        disabled=u.disabled, created_at=u.created_at,
        families=[FamilyRef(id=f.id, name=f.name, role=m.role.value) for f, m in memberships],
        contributions=[_mini_contribution(c, u, ch) for c, ch in contribs],
    )


@router.post("/users/{user_id}/impersonate", response_model=ImpersonationOut)
def impersonate(user_id: uuid.UUID, db: DbSession, admin: AdminUser) -> ImpersonationOut:
    """Issue a short-lived token to view the app as a user, for support. Never
    for another admin (avoids privilege games), always audit-logged. The token
    carries an 'imp' claim naming the acting admin."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if u.role == UserRole.admin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't impersonate another admin")
    _audit(db, admin, "impersonate", f"user:{u.id}", {"email": u.email})
    db.commit()
    return ImpersonationOut(
        access_token=create_impersonation_token(u.id, admin.id, minutes=30),
        expires_in_minutes=30,
        display_name=u.display_name,
        email=u.email,
    )


def _audit_query(db, action: str | None, since: str | None, until: str | None):
    query = db.query(AdminAuditLog, User).outerjoin(
        User, AdminAuditLog.admin_user_id == User.id
    )
    if action:
        query = query.filter(AdminAuditLog.action == action)
    if since:
        query = query.filter(AdminAuditLog.created_at >= datetime.fromisoformat(since))
    if until:
        query = query.filter(AdminAuditLog.created_at <= datetime.fromisoformat(until))
    return query


@router.get("/audit/actions", response_model=list[str])
def audit_actions(db: DbSession, admin: AdminUser) -> list[str]:
    """Distinct action names, to populate the filter dropdown."""
    return [a for (a,) in db.query(AdminAuditLog.action).distinct().order_by(AdminAuditLog.action).all()]


@router.get("/audit", response_model=Page)
def audit_log(
    db: DbSession,
    admin: AdminUser,
    action: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> Page:
    query = _audit_query(db, action, since, until)
    total = query.count()
    rows = query.order_by(AdminAuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return Page(
        total=total,
        items=[
            AuditRow(
                id=log.id,
                admin_name=u.display_name if u else "Unknown",
                admin_email=u.email if u else "",
                action=log.action,
                target=log.target,
                detail=log.detail,
                created_at=log.created_at,
            )
            for log, u in rows
        ],
    )


@router.get("/audit.csv")
def export_audit_csv(
    db: DbSession, admin: AdminUser, action: str | None = None,
    since: str | None = None, until: str | None = None,
) -> StreamingResponse:
    rows = _audit_query(db, action, since, until).order_by(AdminAuditLog.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["created_at", "admin", "admin_email", "action", "target", "detail"])
    for log, u in rows:
        w.writerow([
            log.created_at.isoformat(),
            u.display_name if u else "",
            u.email if u else "",
            log.action,
            log.target or "",
            _json_compact(log.detail),
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=futureroots-audit-log.csv"},
    )


@router.post("/users/{user_id}/role", response_model=MiniUser)
def set_user_role(
    user_id: uuid.UUID, payload: RoleUpdate, db: DbSession, admin: AdminUser
) -> MiniUser:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if u.id == admin.id and payload.role != UserRole.admin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You can't remove your own admin access"
        )
    u.role = payload.role
    _audit(db, admin, "role_changed", f"user:{u.id}", {"user": u.email, "new_role": payload.role.value})
    db.commit()
    return MiniUser(
        id=u.id, display_name=u.display_name, email=u.email, role=u.role,
        disabled=u.disabled, created_at=u.created_at,
    )


class StatusUpdate(BaseModel):
    disabled: bool


@router.post("/users/{user_id}/status", response_model=MiniUser)
def set_user_status(
    user_id: uuid.UUID, payload: StatusUpdate, db: DbSession, admin: AdminUser
) -> MiniUser:
    """Enable or disable a user's ability to sign in. A disabled account is
    locked out immediately, even mid-session. Audit-logged; can't disable self."""
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if u.id == admin.id and payload.disabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't disable your own account")
    u.disabled = payload.disabled
    _audit(
        db, admin, "user_disabled" if payload.disabled else "user_enabled",
        f"user:{u.id}", {"email": u.email},
    )
    db.commit()
    return MiniUser(
        id=u.id, display_name=u.display_name, email=u.email, role=u.role,
        disabled=u.disabled, created_at=u.created_at,
    )


# --- families ---

@router.get("/families", response_model=Page)
def list_families(
    db: DbSession,
    admin: AdminUser,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> Page:
    query = db.query(Family)
    if q:
        query = query.filter(func.lower(Family.name).like(f"%{q.lower()}%"))
    total = query.count()
    families = query.order_by(Family.created_at.desc()).offset(offset).limit(limit).all()
    rows = []
    for f in families:
        members = db.query(func.count(FamilyMember.id)).filter(
            FamilyMember.family_id == f.id, FamilyMember.status == MemberStatus.active
        ).scalar()
        kids = db.query(Child).filter(Child.family_id == f.id).all()
        fund = sum(_fund_cents_for_child(db, c.id) for c in kids)
        rows.append(
            AdminFamilyRow(
                id=f.id, name=f.name, member_count=members, child_count=len(kids),
                fund_cents=fund, created_at=f.created_at,
            )
        )
    return Page(total=total, items=rows)


@router.get("/families/{family_id}", response_model=AdminFamilyDetail)
def family_detail(family_id: uuid.UUID, db: DbSession, admin: AdminUser) -> AdminFamilyDetail:
    f = db.get(Family, family_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Family not found")
    members = (
        db.query(FamilyMember, User)
        .join(User, User.id == FamilyMember.user_id)
        .filter(FamilyMember.family_id == f.id)
        .all()
    )
    children = db.query(Child).filter(Child.family_id == f.id).all()
    child_ids = [c.id for c in children]
    contribs = []
    if child_ids:
        contribs = (
            db.query(Contribution, User, Child)
            .outerjoin(User, Contribution.contributor_user_id == User.id)
            .outerjoin(Child, Contribution.child_id == Child.id)
            .filter(Contribution.child_id.in_(child_ids))
            .order_by(Contribution.created_at.desc())
            .limit(50)
            .all()
        )
    return AdminFamilyDetail(
        id=f.id, name=f.name, created_at=f.created_at,
        fund_cents=sum(_fund_cents_for_child(db, c.id) for c in children),
        max_upload_mb=f.max_upload_mb,
        members=[
            MemberRef(
                user_id=u.id, display_name=u.display_name, email=u.email,
                role=m.role.value, status=m.status.value, disabled=u.disabled,
            )
            for m, u in members
        ],
        children=[_child_ref(db, c) for c in children],
        contributions=[_mini_contribution(c, u, ch) for c, u, ch in contribs],
    )


class FamilySettings(BaseModel):
    max_upload_mb: int = Field(ge=1, le=200)


@router.post("/families/{family_id}/settings", response_model=AdminFamilyDetail)
def update_family_settings(
    family_id: uuid.UUID, payload: FamilySettings, db: DbSession, admin: AdminUser
) -> AdminFamilyDetail:
    f = db.get(Family, family_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Family not found")
    f.max_upload_mb = payload.max_upload_mb
    _audit(db, admin, "family_settings", f"family:{f.id}", {"max_upload_mb": payload.max_upload_mb})
    db.commit()
    return family_detail(family_id, db, admin)


# --- contributions ---

def _contribution_query(db, q: str | None, status_filter: str | None):
    query = (
        db.query(Contribution, User, Child)
        .outerjoin(User, Contribution.contributor_user_id == User.id)
        .outerjoin(Child, Contribution.child_id == Child.id)
    )
    if status_filter in {s.value for s in ContributionStatus}:
        query = query.filter(Contribution.status == status_filter)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(User.display_name).like(like) | func.lower(Child.first_name).like(like)
        )
    return query


@router.get("/contributions", response_model=Page)
def list_contributions(
    db: DbSession,
    admin: AdminUser,
    q: str | None = None,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> Page:
    query = _contribution_query(db, q, status)
    total = query.count()
    rows = query.order_by(Contribution.created_at.desc()).offset(offset).limit(limit).all()
    return Page(
        total=total,
        items=[_mini_contribution(c, u, ch) for c, u, ch in rows],
    )


@router.get("/contributions.csv")
def export_contributions_csv(
    db: DbSession, admin: AdminUser, q: str | None = None, status: str | None = None
) -> StreamingResponse:
    """Download contributions as CSV for bookkeeping. The export itself is
    audit-logged, since it takes contributor and money data off-platform."""
    rows = _contribution_query(db, q, status).order_by(Contribution.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        ["created_at", "contributor", "contributor_email", "child", "amount", "fee",
         "refunded", "currency", "status", "stripe_payment_id", "id"]
    )
    for c, u, ch in rows:
        w.writerow([
            c.created_at.isoformat(),
            u.display_name if u else "",
            u.email if u else "",
            ch.first_name if ch else "",
            f"{c.amount_cents / 100:.2f}",
            f"{c.fee_cents / 100:.2f}",
            f"{c.refunded_cents / 100:.2f}",
            c.currency,
            c.status.value,
            c.provider_payment_id or "",
            str(c.id),
        ])
    _audit(db, admin, "contributions_exported", None, {"rows": len(rows)})
    db.commit()
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=futureroots-contributions.csv"},
    )


class RefundRequest(BaseModel):
    # gross cents to refund; omit for the full remaining amount
    amount_cents: int | None = None


@router.post("/contributions/{contribution_id}/refund", response_model=MiniContribution)
def refund(
    contribution_id: uuid.UUID, db: DbSession, admin: AdminUser, payload: RefundRequest | None = None
) -> MiniContribution:
    """Refund a settled contribution, fully or partially: reverses the amount at
    the payment provider and writes a compensating (append-only) ledger entry.
    Audit-logged."""
    c = db.get(Contribution, contribution_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    if c.status != ContributionStatus.succeeded:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a settled contribution can be refunded"
        )
    amount = payload.amount_cents if payload else None
    remaining = c.amount_cents - c.refunded_cents
    if amount is not None and (amount <= 0 or amount > remaining):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Refund must be between 1 and {remaining} cents",
        )
    refunded_now = amount if amount is not None else remaining
    u = db.get(User, c.contributor_user_id)
    ch = db.get(Child, c.child_id)
    if not refund_contribution(db, c, amount):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The refund could not be processed")
    _audit(
        db, admin, "contribution_refunded", f"contribution:{c.id}",
        {
            "amount": f"${refunded_now / 100:,.2f}",
            "contributor": u.email if u else None,
            "child": ch.first_name if ch else None,
            "partial": c.status == ContributionStatus.succeeded,
        },
    )
    db.commit()
    return _mini_contribution(c, u, ch)


@router.post("/contributions/{contribution_id}/reconcile", response_model=MiniContribution)
def reconcile(contribution_id: uuid.UUID, db: DbSession, admin: AdminUser) -> MiniContribution:
    """Resolve a stuck 'pending' contribution against the payment provider's
    live status (a cancelled or failed payment becomes failed; a settled one
    settles). Fixes records left behind by a missed webhook. Audit-logged."""
    c = db.get(Contribution, contribution_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    before = c.status.value
    u = db.get(User, c.contributor_user_id)
    ch = db.get(Child, c.child_id)
    after, settlement = reconcile_contribution(db, c)
    _audit(
        db, admin, "contribution_reconciled", f"contribution:{c.id}",
        {
            "from": before, "to": after,
            "amount": f"${c.amount_cents / 100:,.2f}",
            "contributor": u.email if u else None,
            "child": ch.first_name if ch else None,
        },
    )
    db.commit()
    if settlement is not None:
        # Celebration emails only after the ledger write is committed.
        settlement.send_emails()
    return _mini_contribution(c, u, ch)


# --- premium (support paths) ---

@router.post("/families/{family_id}/premium/reconcile")
def reconcile_premium(family_id: uuid.UUID, db: DbSession, admin: AdminUser) -> dict:
    """Re-sync a family's subscription mirror from live Stripe state (fixes
    drift from a missed webhook). Precedent: contribution reconcile."""
    f = db.get(Family, family_id)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Family not found")
    result = reconcile_family_premium(db, family_id)
    _audit(db, admin, "premium_reconciled", f"family:{family_id}", {"result": result})
    db.commit()
    return {"status": result}


@router.post("/premium-grants/{grant_id}/void")
def void_premium_grant(grant_id: uuid.UUID, db: DbSession, admin: AdminUser) -> dict:
    """Support path for a refunded/charged-back gift (refund happens in the
    Stripe dashboard first). The one permitted mutation on the append-only
    premium_grants table: voided grants are ignored by the entitlement
    derivation but never deleted. Audit-logged."""
    grant = db.get(PremiumGrant, grant_id)
    if grant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    if grant.voided_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This grant is already voided")
    grant.voided_at = utcnow()
    grant.voided_by_user_id = admin.id
    # The gift message is free text that may name a child; a voided grant is
    # refunded/reversed and no longer displayed, so it shouldn't retain PII.
    # Clearing it is the only mutation permitted here beyond the void stamp —
    # the append-only discipline otherwise holds.
    grant.message = None
    _audit(
        db, admin, "premium_grant_voided", f"premium_grant:{grant.id}",
        {"family_id": str(grant.family_id), "amount_cents": grant.amount_cents},
    )
    db.commit()
    return {"id": str(grant.id), "voided_at": grant.voided_at.isoformat()}


@router.post("/premium/prune-gift-intents")
def prune_gift_intents(db: DbSession, admin: AdminUser) -> dict:
    """Delete gift-intent staging rows older than 30 days (abandoned checkouts
    leave harmless orphans; settled gifts have already copied the message onto
    the grant). Same sweep the daily maintenance command runs — this endpoint
    stays as the manual/on-demand trigger."""
    pruned = maintenance_prune_gift_intents(db)
    _audit(db, admin, "premium_gift_intents_pruned", None, {"pruned": pruned})
    db.commit()
    return {"pruned": pruned}


# --- bug reports ---

def _bug_reporter(tester: Tester | None, reporter: User | None) -> str:
    if tester is not None:
        return tester.x_username or tester.display_name or tester.wallet_address[:10]
    if reporter is not None:
        return f"{reporter.display_name} ({reporter.email})"
    return "Unknown"


@router.get("/bugs", response_model=list[AdminBugRow])
def list_bugs(
    db: DbSession, admin: AdminUser, status_filter: str | None = Query(default=None, alias="status")
) -> list[AdminBugRow]:
    # reports come from testers (testnet) OR main-site users; left-join both
    query = (
        db.query(BugReport, Tester, User)
        .outerjoin(Tester, Tester.id == BugReport.tester_id)
        .outerjoin(User, User.id == BugReport.reporter_user_id)
    )
    if status_filter in ("pending", "verified", "rejected"):
        query = query.filter(BugReport.status == status_filter)
    rows = query.order_by(BugReport.created_at.desc()).limit(200).all()
    return [
        AdminBugRow(
            id=r.id, title=r.title, body=r.body, status=r.status,
            reporter=_bug_reporter(t, ru),
            media_id=r.media_id, created_at=r.created_at, reviewed_at=r.reviewed_at,
        )
        for r, t, ru in rows
    ]


@router.post("/bugs/{bug_id}/{decision}", response_model=AdminBugRow)
def decide_bug(
    bug_id: uuid.UUID, decision: str, db: DbSession, admin: AdminUser
) -> AdminBugRow:
    """Verify or reject a bug report from the console. Verifying awards the
    reporter (idempotent via points_awarded); the action is audit-logged."""
    from ..testnet.service import award  # no-op off testnet, but bugs are testnet-only

    if decision not in ("verify", "reject"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    report = db.get(BugReport, bug_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bug report not found")
    tester = db.get(Tester, report.tester_id) if report.tester_id else None
    reporter = db.get(User, report.reporter_user_id) if report.reporter_user_id else None
    report.reviewed_at = utcnow()
    if decision == "verify":
        report.status = "verified"
        # points are a testnet concept; only a tester-reported bug awards them
        if tester is not None and not report.points_awarded:
            award(db, tester.user_id, "bug_verified")
            report.points_awarded = True
    else:
        report.status = "rejected"
    _audit(
        db, admin, f"bug_{decision}", f"bug:{report.id}",
        {"title": report.title, "reporter": _bug_reporter(tester, reporter)},
    )
    db.commit()
    db.refresh(report)
    return AdminBugRow(
        id=report.id, title=report.title, body=report.body, status=report.status,
        reporter=_bug_reporter(tester, reporter),
        media_id=report.media_id, created_at=report.created_at, reviewed_at=report.reviewed_at,
    )
