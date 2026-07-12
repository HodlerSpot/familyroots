"""Testnet endpoints: wallet sign-in, quest board, leaderboard, profile.

The wall (docs/testnet.md): main.py mounts this router only when
settings.testnet_mode is on, AND every route carries require_testnet, which
404s at request time when the flag is off. Outside testnet deployments these
endpoints are indistinguishable from routes that were never built.

Wallet auth is Sign-In-With-Ethereum style on Base Sepolia: signature-only
login, no transactions, no funds. The verify step returns a normal platform
JWT, so the entire existing product API works for testers unchanged.
"""

import re
import secrets
from datetime import timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from typing import Annotated

from ..config import settings
from ..deps import CurrentUser, DbSession, bearer_scheme
from ..models import PointEvent, Tester, User, WalletNonce, utcnow
from ..schemas import TokenResponse
from ..security import create_access_token, decode_access_token, hash_password
from .service import (
    QUESTS,
    award,
    day_start_utc,
    get_tester_for_user,
    short_wallet,
)

NONCE_TTL_MINUTES = 10

SIGN_IN_MESSAGE = (
    "Sign in to FutureRoots Testnet (Base Sepolia)\n\nWallet: {address}\nNonce: {nonce}"
)


def require_testnet() -> None:
    """The wall: outside testnet mode, these endpoints do not exist."""
    if not settings.testnet_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


router = APIRouter(
    prefix="/testnet", tags=["testnet"], dependencies=[Depends(require_testnet)]
)


# --- schemas (testnet-only; kept out of app/schemas.py on purpose) ---


def _validate_address(value: str) -> str:
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise ValueError("That doesn't look like a wallet address")
    return value.lower()


class NonceRequest(BaseModel):
    address: str

    _normalize = field_validator("address")(_validate_address)


class NonceOut(BaseModel):
    nonce: str
    message: str


class VerifyRequest(BaseModel):
    address: str
    signature: str = Field(max_length=200)

    _normalize = field_validator("address")(_validate_address)


class QuestOut(BaseModel):
    action: str
    label: str
    hint: str
    points: int
    daily_cap: int
    once: bool
    times_completed: int
    points_earned: int
    completed_today: int


class QuestBoardOut(BaseModel):
    wallet_address: str
    display_name: str | None
    invite_email: str
    total_points: int
    quests: list[QuestOut]


class LeaderboardEntry(BaseModel):
    rank: int
    display_name: str
    points: int
    is_me: bool


class LeaderboardOut(BaseModel):
    entries: list[LeaderboardEntry]
    my_rank: int | None = None
    my_points: int | None = None


class ProfileUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)

    @field_validator("display_name")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please pick a name with at least one character")
        return value


class ProfileOut(BaseModel):
    wallet_address: str
    display_name: str | None


# --- auth ---


@router.post("/auth/nonce", response_model=NonceOut)
def issue_nonce(payload: NonceRequest, db: DbSession) -> NonceOut:
    """Issue (or refresh) the single-use sign-in nonce for a wallet."""
    nonce = secrets.token_hex(16)
    row = (
        db.query(WalletNonce)
        .filter(WalletNonce.wallet_address == payload.address)
        .first()
    )
    if row is None:
        db.add(WalletNonce(wallet_address=payload.address, nonce=nonce))
    else:
        row.nonce = nonce
        row.issued_at = utcnow()
    db.commit()
    return NonceOut(
        nonce=nonce, message=SIGN_IN_MESSAGE.format(address=payload.address, nonce=nonce)
    )


@router.post("/auth/verify", response_model=TokenResponse)
def verify_signature(payload: VerifyRequest, db: DbSession) -> TokenResponse:
    """Verify a personal_sign of the nonce message; first login creates the
    tester and a linked platform user, and awards connect_wallet once."""
    address = payload.address
    row = (
        db.query(WalletNonce).filter(WalletNonce.wallet_address == address).first()
    )
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Please request a fresh sign-in message and try again",
        )

    issued_at = row.issued_at
    if issued_at.tzinfo is None:  # SQLite loses tz info in tests
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if issued_at < utcnow() - timedelta(minutes=NONCE_TTL_MINUTES):
        db.delete(row)
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "That sign-in message expired. Please request a fresh one",
        )

    message = SIGN_IN_MESSAGE.format(address=address, nonce=row.nonce)
    try:
        recovered = Account.recover_message(
            encode_defunct(text=message), signature=payload.signature
        )
    except Exception:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "We couldn't verify that signature. Please try again",
        )
    if recovered.lower() != address:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "We couldn't verify that signature. Please try again",
        )

    db.delete(row)  # single use: a signature can never be replayed

    tester = db.query(Tester).filter(Tester.wallet_address == address).first()
    if tester is None:
        # First login: a real platform user backs every tester, so the whole
        # product API works with the returned token unchanged. Nobody knows
        # the random password; the wallet signature is the only way in.
        user = User(
            email=f"{address}@wallet.testnet.futureroots.app",
            display_name=f"Tester {short_wallet(address)}",
            password_hash=hash_password(secrets.token_urlsafe(24) + "!Aa1"),
        )
        db.add(user)
        db.flush()
        tester = Tester(wallet_address=address, user_id=user.id)
        db.add(tester)
        db.flush()
        award(db, user.id, "connect_wallet")

    user_id = tester.user_id
    db.commit()
    return TokenResponse(access_token=create_access_token(user_id))


# --- quests ---


@router.get("/quests", response_model=QuestBoardOut)
def quest_board(db: DbSession, user: CurrentUser) -> QuestBoardOut:
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )

    totals = dict()
    for action, count, points in (
        db.query(
            PointEvent.action,
            func.count(PointEvent.id),
            func.coalesce(func.sum(PointEvent.points), 0),
        )
        .filter(PointEvent.tester_id == tester.id)
        .group_by(PointEvent.action)
        .all()
    ):
        totals[action] = (count, points)

    today = dict(
        db.query(PointEvent.action, func.count(PointEvent.id))
        .filter(
            PointEvent.tester_id == tester.id,
            PointEvent.created_at >= day_start_utc(),
        )
        .group_by(PointEvent.action)
        .all()
    )

    quests = [
        QuestOut(
            action=q.action,
            label=q.label,
            hint=q.hint,
            points=q.points,
            daily_cap=q.daily_cap,
            once=q.once,
            times_completed=totals.get(q.action, (0, 0))[0],
            points_earned=totals.get(q.action, (0, 0))[1],
            completed_today=today.get(q.action, 0),
        )
        for q in QUESTS
    ]
    return QuestBoardOut(
        wallet_address=tester.wallet_address,
        display_name=tester.display_name,
        invite_email=user.email,
        total_points=sum(entry[1] for entry in totals.values()),
        quests=quests,
    )


# --- leaderboard ---


def _optional_tester(db: DbSession, credentials=Depends(bearer_scheme)) -> Tester | None:
    """Leaderboard is public on the testnet; auth only adds 'my rank'."""
    if credentials is None:
        return None
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        return None
    return db.query(Tester).filter(Tester.user_id == user_id).first()


@router.get("/leaderboard", response_model=LeaderboardOut)
def leaderboard(
    db: DbSession, me: Annotated[Tester | None, Depends(_optional_tester)]
) -> LeaderboardOut:
    points_col = func.coalesce(func.sum(PointEvent.points), 0).label("points")
    rows = (
        db.query(Tester, points_col)
        .outerjoin(PointEvent, PointEvent.tester_id == Tester.id)
        .group_by(Tester.id)
        .order_by(points_col.desc(), Tester.created_at.asc())
        .limit(50)
        .all()
    )
    entries = [
        LeaderboardEntry(
            rank=i,
            display_name=tester.display_name or short_wallet(tester.wallet_address),
            points=points,
            is_me=me is not None and tester.id == me.id,
        )
        for i, (tester, points) in enumerate(rows, start=1)
    ]

    my_rank = my_points = None
    if me is not None:
        my_points = (
            db.query(func.coalesce(func.sum(PointEvent.points), 0))
            .filter(PointEvent.tester_id == me.id)
            .scalar()
        )
        sums = (
            db.query(
                PointEvent.tester_id,
                func.sum(PointEvent.points).label("points"),
            )
            .group_by(PointEvent.tester_id)
            .subquery()
        )
        higher = (
            db.query(func.count())
            .select_from(sums)
            .filter(sums.c.points > my_points)
            .scalar()
        )
        my_rank = higher + 1

    return LeaderboardOut(entries=entries, my_rank=my_rank, my_points=my_points)


# --- profile ---


@router.post("/profile", response_model=ProfileOut)
def set_profile(payload: ProfileUpdate, db: DbSession, user: CurrentUser) -> ProfileOut:
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )
    tester.display_name = payload.display_name
    award(db, user.id, "set_display_name")
    db.commit()
    return ProfileOut(
        wallet_address=tester.wallet_address, display_name=tester.display_name
    )
