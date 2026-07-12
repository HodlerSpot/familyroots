"""Admin command center API.

Every route is gated by AdminUser (role == admin on the user record). This
console exposes sensitive data — children's profiles and money — so access is
role-restricted and consequential actions are written to admin_audit_log.

Mounted on both the family site and the testnet harness; each reads its own
database, so on the family site this shows real families and on testnet it
shows testers and their test data.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
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
    Tester,
    User,
    UserRole,
    utcnow,
)
from ..services.payments import fund_balance_cents

router = APIRouter(prefix="/admin", tags=["admin"])


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
    created_at: datetime


class MiniContribution(BaseModel):
    id: uuid.UUID
    contributor_name: str
    child_name: str
    amount_cents: int
    currency: str
    status: ContributionStatus
    created_at: datetime


class AdminUserRow(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    role: UserRole
    family_count: int
    child_count: int
    created_at: datetime


class AdminUserDetail(BaseModel):
    id: uuid.UUID
    display_name: str
    email: str
    role: UserRole
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
    members: list["MemberRef"]
    children: list["ChildRef"]


class MemberRef(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    status: str


class ChildRef(BaseModel):
    id: uuid.UUID
    first_name: str
    fund_cents: int


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


class Page(BaseModel):
    total: int
    items: list


# --- helpers ---

def _fund_cents_for_child(db, child_id: uuid.UUID) -> int:
    account = db.query(FundAccount).filter(FundAccount.child_id == child_id).first()
    return fund_balance_cents(db, account.id) if account else 0


def _mini_contribution(c: Contribution, contributor: User | None, child: Child | None) -> MiniContribution:
    return MiniContribution(
        id=c.id,
        contributor_name=contributor.display_name if contributor else "Unknown",
        child_name=child.first_name if child else "Unknown",
        amount_cents=c.amount_cents,
        currency=c.currency,
        status=c.status,
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
                created_at=u.created_at,
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
                family_count=fam, child_count=kids, created_at=u.created_at,
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
        created_at=u.created_at,
        families=[FamilyRef(id=f.id, name=f.name, role=m.role.value) for f, m in memberships],
        contributions=[_mini_contribution(c, u, ch) for c, ch in contribs],
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
    _audit(db, admin, "role_changed", f"user:{u.id}", {"role": payload.role.value})
    db.commit()
    return MiniUser(
        id=u.id, display_name=u.display_name, email=u.email, role=u.role,
        created_at=u.created_at,
    )


# --- families ---

@router.get("/families", response_model=Page)
def list_families(
    db: DbSession, admin: AdminUser, limit: int = Query(default=50, le=200), offset: int = 0
) -> Page:
    total = db.query(func.count(Family.id)).scalar()
    families = db.query(Family).order_by(Family.created_at.desc()).offset(offset).limit(limit).all()
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
    return AdminFamilyDetail(
        id=f.id, name=f.name, created_at=f.created_at,
        members=[
            MemberRef(
                user_id=u.id, display_name=u.display_name, email=u.email,
                role=m.role.value, status=m.status.value,
            )
            for m, u in members
        ],
        children=[
            ChildRef(id=c.id, first_name=c.first_name, fund_cents=_fund_cents_for_child(db, c.id))
            for c in children
        ],
    )


# --- contributions ---

@router.get("/contributions", response_model=Page)
def list_contributions(
    db: DbSession, admin: AdminUser, limit: int = Query(default=50, le=200), offset: int = 0
) -> Page:
    total = db.query(func.count(Contribution.id)).scalar()
    rows = (
        db.query(Contribution, User, Child)
        .outerjoin(User, Contribution.contributor_user_id == User.id)
        .outerjoin(Child, Contribution.child_id == Child.id)
        .order_by(Contribution.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return Page(
        total=total,
        items=[_mini_contribution(c, u, ch) for c, u, ch in rows],
    )


# --- bug reports ---

@router.get("/bugs", response_model=list[AdminBugRow])
def list_bugs(
    db: DbSession, admin: AdminUser, status_filter: str | None = Query(default=None, alias="status")
) -> list[AdminBugRow]:
    query = db.query(BugReport, Tester).join(Tester, Tester.id == BugReport.tester_id)
    if status_filter in ("pending", "verified", "rejected"):
        query = query.filter(BugReport.status == status_filter)
    rows = query.order_by(BugReport.created_at.desc()).limit(200).all()
    return [
        AdminBugRow(
            id=r.id, title=r.title, body=r.body, status=r.status,
            reporter=(t.x_username or t.display_name or t.wallet_address[:10]),
            media_id=r.media_id, created_at=r.created_at, reviewed_at=r.reviewed_at,
        )
        for r, t in rows
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
    row = db.query(BugReport, Tester).join(Tester, Tester.id == BugReport.tester_id).filter(
        BugReport.id == bug_id
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bug report not found")
    report, tester = row
    report.reviewed_at = utcnow()
    if decision == "verify":
        report.status = "verified"
        if not report.points_awarded:
            award(db, tester.user_id, "bug_verified")
            report.points_awarded = True
    else:
        report.status = "rejected"
    _audit(db, admin, f"bug_{decision}", f"bug:{report.id}", {"title": report.title})
    db.commit()
    db.refresh(report)
    return AdminBugRow(
        id=report.id, title=report.title, body=report.body, status=report.status,
        reporter=(tester.x_username or tester.display_name or tester.wallet_address[:10]),
        media_id=report.media_id, created_at=report.created_at, reviewed_at=report.reviewed_at,
    )
