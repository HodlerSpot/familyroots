"""Testnet endpoints: wallet sign-in, quest board, leaderboard, profile.

The wall (docs/testnet.md): main.py mounts this router only when
settings.testnet_mode is on, AND every route carries require_testnet, which
404s at request time when the flag is off. Outside testnet deployments these
endpoints are indistinguishable from routes that were never built.

Wallet auth is Sign-In-With-Ethereum style on Base Sepolia: signature-only
login, no transactions, no funds. The verify step returns a normal platform
JWT, so the entire existing product API works for testers unchanged.
"""

import base64
import hashlib
import json
import re
import secrets
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from typing import Annotated, Literal

from ..config import settings
from ..deps import CurrentUser, DbSession, bearer_scheme
from ..models import (
    BugReport,
    MediaObject,
    MediaStatus,
    PointEvent,
    Tester,
    User,
    WalletNonce,
    XAuthState,
    utcnow,
)
from ..schemas import MediaCreate, MediaUploadTicket, TokenResponse
from ..security import create_access_token, decode_access_token, hash_password
from ..services.storage import get_storage
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


MAX_PENDING_BUGS = 20  # a tester can't sit on more than this many unreviewed reports

# --- X (Twitter) OAuth 2.0 (Authorization Code + PKCE, confidential client) ---

X_AUTHORIZE_URL = "https://twitter.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.twitter.com/2/oauth2/token"  # noqa: S105 (URL, not a secret)
X_ME_URL = "https://api.twitter.com/2/users/me?user.fields=profile_image_url"
X_SCOPES = "users.read tweet.read"
X_STATE_TTL_MINUTES = 10


def _x_redirect_uri() -> str:
    return f"{settings.web_base_url}/x/callback"


def _pkce_challenge(verifier: str) -> str:
    """S256 code challenge: base64url(sha256(verifier)), padding stripped."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _x_token_exchange(code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for an access token at X's token endpoint.

    Confidential client: HTTP Basic auth with client_id:client_secret. Patched
    out in tests so no real network call happens."""
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _x_redirect_uri(),
            "code_verifier": code_verifier,
        }
    ).encode("ascii")
    basic = base64.b64encode(
        f"{settings.x_client_id}:{settings.x_client_secret}".encode()
    ).decode("ascii")
    req = urllib.request.Request(X_TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Authorization", f"Basic {basic}")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https host)
        return json.loads(resp.read().decode("utf-8"))


def _x_fetch_me(access_token: str) -> dict:
    """Fetch the connected user's X profile. Returns the `data` object with
    id, username, and profile_image_url. Patched out in tests."""
    req = urllib.request.Request(X_ME_URL, method="GET")
    req.add_header("Authorization", f"Bearer {access_token}")
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed https host)
        data = json.loads(resp.read().decode("utf-8"))
    return data["data"]


def require_testnet() -> None:
    """The wall: outside testnet mode, these endpoints do not exist."""
    if not settings.testnet_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


def require_admin(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    """Gate the human-only bug-verification endpoint on a shared secret.

    Constant-time compare. If no token is configured, verification is
    impossible by design (so bug_verified points can never be awarded without
    an operator explicitly setting FUTUREROOTS_TESTNET_ADMIN_TOKEN)."""
    expected = settings.testnet_admin_token
    if (
        not expected
        or not x_admin_token
        or not secrets.compare_digest(x_admin_token, expected)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin token required")


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
    x_username: str | None = None
    # The X profile picture when connected; null means the frontend renders a
    # deterministic identicon seeded on the wallet address.
    avatar_url: str | None = None


class LeaderboardEntry(BaseModel):
    rank: int
    display_name: str
    points: int
    is_me: bool
    # Full lowercase wallet address (public on testnet) — the identicon seed
    # used when avatar_url is null.
    wallet: str
    avatar_url: str | None = None


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


class XStartOut(BaseModel):
    authorize_url: str


class XCallbackRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=64)


class XProfileOut(BaseModel):
    wallet_address: str
    display_name: str | None
    x_username: str | None
    x_avatar_url: str | None


class BugSubmit(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)
    media_id: uuid.UUID | None = None

    @field_validator("title", "body")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please add a little more detail")
        return value


class BugReportOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: str
    media_id: uuid.UUID | None
    image_url: str | None
    created_at: datetime
    reviewed_at: datetime | None

    @staticmethod
    def of(report: BugReport) -> "BugReportOut":
        return BugReportOut(
            id=report.id,
            title=report.title,
            body=report.body,
            status=report.status,
            media_id=report.media_id,
            # client appends ?token=; download_media authorizes the uploader
            image_url=f"/media/{report.media_id}" if report.media_id else None,
            created_at=report.created_at,
            reviewed_at=report.reviewed_at,
        )


class VerifyDecision(BaseModel):
    decision: Literal["verified", "rejected"]


class AdminBugOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: str
    reporter: str  # X handle, display name, or shortened wallet
    wallet_address: str
    image_media_id: uuid.UUID | None
    created_at: datetime


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
        x_username=tester.x_username,
        avatar_url=tester.x_avatar_url,
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
            display_name=(
                tester.x_username
                or tester.display_name
                or short_wallet(tester.wallet_address)
            ),
            points=points,
            is_me=me is not None and tester.id == me.id,
            wallet=tester.wallet_address,
            avatar_url=tester.x_avatar_url,
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


# --- X (Twitter) connection (optional avatar + handle) ---
#
# OAuth 2.0 Authorization Code + PKCE, confidential client. Connecting X is
# itself the connect_x quest. The identicon stays the default; a connected X
# account simply replaces it with the tester's real avatar and @handle.


@router.post("/auth/x/start", response_model=XStartOut)
def x_start(db: DbSession, user: CurrentUser) -> XStartOut:
    """Begin the X connect handshake: store PKCE state, return the authorize URL.

    503 when X isn't configured so the UI can hide/disable the button."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )
    if not settings.x_client_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "X connection isn't set up yet"
        )

    state = secrets.token_urlsafe(32)  # <= 64 chars
    code_verifier = secrets.token_urlsafe(64)  # <= 128 chars, RFC 7636 range
    db.add(
        XAuthState(tester_id=tester.id, state=state, code_verifier=code_verifier)
    )
    db.commit()

    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": settings.x_client_id,
            "redirect_uri": _x_redirect_uri(),
            "scope": X_SCOPES,
            "state": state,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
    )
    return XStartOut(authorize_url=f"{X_AUTHORIZE_URL}?{query}")


@router.post("/auth/x/callback", response_model=XProfileOut)
def x_callback(
    payload: XCallbackRequest, db: DbSession, user: CurrentUser
) -> XProfileOut:
    """Complete the X connect handshake: consume the PKCE state, exchange the
    code, fetch the profile, and link X to this tester (awarding connect_x)."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )

    row = (
        db.query(XAuthState)
        .filter(
            XAuthState.tester_id == tester.id, XAuthState.state == payload.state
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That X sign-in didn't match. Please start again",
        )

    created_at = row.created_at
    if created_at.tzinfo is None:  # SQLite loses tz info in tests
        created_at = created_at.replace(tzinfo=timezone.utc)
    expired = created_at < utcnow() - timedelta(minutes=X_STATE_TTL_MINUTES)
    code_verifier = row.code_verifier
    db.delete(row)  # single use, whether it succeeds or not
    if expired:
        db.commit()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "That X sign-in expired. Please start again",
        )

    try:
        token_data = _x_token_exchange(payload.code, code_verifier)
        access_token = token_data["access_token"]
        me = _x_fetch_me(access_token)
        x_user_id = str(me["id"])
        username = str(me["username"])
        avatar = me.get("profile_image_url")
    except Exception:
        db.commit()  # release the consumed state; the tester can retry cleanly
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't reach X just now. Please try again",
        )

    # One X account per tester.
    clash = (
        db.query(Tester)
        .filter(Tester.x_user_id == x_user_id, Tester.id != tester.id)
        .first()
    )
    if clash is not None:
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That X account is already linked to another tester",
        )

    tester.x_user_id = x_user_id
    tester.x_username = f"@{username}"
    # Ask X for a larger image than the default "_normal" (48px) thumbnail.
    tester.x_avatar_url = avatar.replace("_normal", "_400x400") if avatar else None
    award(db, user.id, "connect_x")
    db.commit()
    return XProfileOut(
        wallet_address=tester.wallet_address,
        display_name=tester.display_name,
        x_username=tester.x_username,
        x_avatar_url=tester.x_avatar_url,
    )


@router.post("/auth/x/disconnect", response_model=XProfileOut)
def x_disconnect(db: DbSession, user: CurrentUser) -> XProfileOut:
    """Unlink X. The connect_x points stay earned (and won't re-award on a
    future reconnect, since the quest is once-ever); this just clears the
    handle and picture so the tester falls back to their identicon."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )
    tester.x_user_id = None
    tester.x_username = None
    tester.x_avatar_url = None
    db.commit()
    return XProfileOut(
        wallet_address=tester.wallet_address,
        display_name=tester.display_name,
        x_username=None,
        x_avatar_url=None,
    )


# --- bug reports ---
#
# The anti-gaming rule that matters most here: submitting a bug scores nothing.
# A tester can file reports freely, but the 250-point bug_verified award fires
# only when a human reviewer hits the admin verify endpoint below. Submission
# is never a scoring path.


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.post(
    "/bugs/media", response_model=MediaUploadTicket, status_code=status.HTTP_201_CREATED
)
def create_bug_media(
    payload: MediaCreate, db: DbSession, user: CurrentUser
) -> MediaUploadTicket:
    """Start a screenshot upload for a bug report. Reuses the shared media
    pipeline: client PUTs to upload_url, then POSTs /media/{id}/complete."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )
    if payload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Please attach an image (PNG, JPEG, WebP, or GIF)"
        )
    media = MediaObject(
        tester_id=tester.id,
        storage_key=str(uuid.uuid4()),
        content_type=payload.content_type,
        uploaded_by=user.id,
    )
    db.add(media)
    db.commit()
    return MediaUploadTicket(media_id=media.id, upload_url=get_storage().upload_target(media))


@router.post("/bugs", response_model=BugReportOut, status_code=status.HTTP_201_CREATED)
def submit_bug(payload: BugSubmit, db: DbSession, user: CurrentUser) -> BugReportOut:
    """File a bug report. Creates a pending report for the caller's tester and
    awards no points — verification (a human action) is the only scoring path."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )

    pending = (
        db.query(func.count(BugReport.id))
        .filter(BugReport.tester_id == tester.id, BugReport.status == "pending")
        .scalar()
    )
    if pending >= MAX_PENDING_BUGS:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You have plenty of reports awaiting review already. Thanks for the help",
        )

    if payload.media_id is not None:
        media = db.get(MediaObject, payload.media_id)
        if (
            media is None
            or media.uploaded_by != user.id
            or media.tester_id != tester.id
            or media.status != MediaStatus.uploaded
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That screenshot isn't ready yet"
            )

    report = BugReport(
        tester_id=tester.id, title=payload.title, body=payload.body, media_id=payload.media_id
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return BugReportOut.of(report)


@router.get("/bugs", response_model=list[BugReportOut])
def my_bugs(db: DbSession, user: CurrentUser) -> list[BugReportOut]:
    """The caller's own bug reports, newest first, with their review status."""
    tester = get_tester_for_user(db, user.id)
    if tester is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Connect a wallet to join the testing crew"
        )
    reports = (
        db.query(BugReport)
        .filter(BugReport.tester_id == tester.id)
        .order_by(BugReport.created_at.desc())
        .all()
    )
    return [BugReportOut.of(r) for r in reports]


@router.get("/bugs/pending", response_model=list[AdminBugOut])
def list_pending_bugs(
    db: DbSession,
    _admin: Annotated[None, Depends(require_admin)],
) -> list[AdminBugOut]:
    """Admin review queue: every pending bug report with who filed it, so an
    operator can read them and grab the id to verify. Admin-token gated."""
    rows = (
        db.query(BugReport, Tester)
        .join(Tester, Tester.id == BugReport.tester_id)
        .filter(BugReport.status == "pending")
        .order_by(BugReport.created_at.asc())
        .all()
    )
    return [
        AdminBugOut(
            id=report.id,
            title=report.title,
            body=report.body,
            status=report.status,
            reporter=(
                tester.x_username
                or tester.display_name
                or short_wallet(tester.wallet_address)
            ),
            wallet_address=tester.wallet_address,
            image_media_id=report.media_id,
            created_at=report.created_at,
        )
        for report, tester in rows
    ]


@router.post("/bugs/{bug_id}/verify", response_model=BugReportOut)
def verify_bug(
    bug_id: uuid.UUID,
    payload: VerifyDecision,
    db: DbSession,
    _admin: Annotated[None, Depends(require_admin)],
) -> BugReportOut:
    """Human review of a bug report — the ONLY path that awards bug_verified.

    On "verified": mark the report verified and, if it has not already scored,
    award the reporting tester 250 points (subject to award()'s own daily cap).
    points_awarded is the per-report idempotency guard, so re-verifying can
    never double-award. On "rejected": mark rejected; no points, ever."""
    report = db.query(BugReport).filter(BugReport.id == bug_id).first()
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bug report not found")

    report.reviewed_at = utcnow()
    if payload.decision == "verified":
        report.status = "verified"
        if not report.points_awarded:
            tester = db.query(Tester).filter(Tester.id == report.tester_id).first()
            if tester is not None:
                award(db, tester.user_id, "bug_verified")
            report.points_awarded = True
    else:  # "rejected"
        report.status = "rejected"

    db.commit()
    db.refresh(report)
    return BugReportOut.of(report)
