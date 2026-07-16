import hashlib
import secrets
from datetime import timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from ..config import settings
from ..deps import CurrentUser, DbSession
from ..models import PasswordReset, User, utcnow
from ..schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MediaTokenResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from ..security import (
    create_access_token,
    create_media_token,
    hash_password,
    verify_password,
)
from ..services.email import get_email_sender
from ..services.email_templates import render_email

RESET_TTL_MINUTES = 60

router = APIRouter(prefix="/auth", tags=["auth"])


def _send_welcome_email(user: User) -> None:
    get_email_sender().send(
        to=user.email,
        subject=f"Welcome to FutureRoots, {user.display_name} 🌱",
        body=(
            f"Hi {user.display_name},\n\n"
            f"Welcome to FutureRoots, your family's private space for memories, "
            f"milestones, and building a future together.\n\n"
            f"Here's how families use it:\n\n"
            f"  🏡  Create your family space and add your children. Each child gets\n"
            f"      a vault of memories that stays with them for life.\n"
            f"  💌  Invite grandparents and relatives with a simple email link.\n"
            f"  🎉  Share milestones (first steps, recitals, big wins) and the\n"
            f"      whole family celebrates with you.\n"
            f"  🌳  Grow their future fund. Family members can add a gift in under\n"
            f"      a minute, right from a milestone email.\n"
            f"  ✉️  Seal time capsules to be opened at just the right moment,\n"
            f"      years from now.\n\n"
            f"Start here: {settings.web_base_url}/family\n\n"
            f"We're glad your family is here.\n\n"
            f"With warmth,\nThe FutureRoots team"
        ),
        html=render_email(
            preheader="Your family's private space for memories, milestones, and the future.",
            greeting=f"Hi {user.display_name},",
            paragraphs=[
                "Welcome to FutureRoots, your family's private space for memories, "
                "milestones, and building a future together.",
                "Here's how families use it:",
                "🏡 Create your family space and add your children. Each child gets "
                "a vault of memories that stays with them for life.",
                "💌 Invite grandparents and relatives with a simple email link.",
                "🎉 Share milestones (first steps, recitals, big wins) and the "
                "whole family celebrates with you.",
                "🌳 Grow their future fund. Family members can add a gift in under "
                "a minute, right from a milestone email.",
                "✉️ Seal time capsules to be opened at just the right moment, "
                "years from now.",
                "We're glad your family is here.",
            ],
            cta_label="Create your family space",
            cta_url=f"{settings.web_base_url}/family",
        ),
    )


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: DbSession) -> TokenResponse:
    email = payload.email.lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    _send_welcome_email(user)
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been disabled")
    user.last_login_at = utcnow()
    db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/media-token", response_model=MediaTokenResponse)
def issue_media_token(user: CurrentUser) -> MediaTokenResponse:
    """Mint the short-lived, media-only token the web client puts in
    <img>/<video> query strings (tags can't send Authorization headers).
    Issuance requires a live session — the same gate that used to front every
    media fetch — and GET /media/{id} still runs its full per-media
    authorization, so this token never widens access; it only replaces the
    full session JWT in URLs with a narrow, expiring, read-only credential."""
    return MediaTokenResponse(
        media_token=create_media_token(user.id),
        expires_in_seconds=settings.media_token_ttl_minutes * 60,
    )


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> None:
    """Always 204 — never reveals whether an account exists."""
    user = db.query(User).filter(User.email == payload.email.lower()).first()
    if user is None:
        return
    token = secrets.token_urlsafe(32)
    db.add(
        PasswordReset(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=utcnow() + timedelta(minutes=RESET_TTL_MINUTES),
        )
    )
    db.commit()
    get_email_sender().send(
        to=user.email,
        subject="Reset your FutureRoots password",
        body=(
            f"Hi {user.display_name},\n\n"
            f"We received a request to reset your FutureRoots password. "
            f"Choose a new one here:\n\n"
            f"{settings.web_base_url}/reset-password/{token}\n\n"
            f"This link works once and expires in {RESET_TTL_MINUTES} minutes. "
            f"If you didn't ask for this, you can safely ignore this email. "
            f"Your password won't change.\n\n"
            f"With warmth,\nThe FutureRoots team"
        ),
        html=render_email(
            preheader="Choose a new password for your FutureRoots account.",
            greeting=f"Hi {user.display_name},",
            paragraphs=[
                "We received a request to reset your FutureRoots password. "
                "Choose a new one below and you'll be back with your family "
                "in a moment."
            ],
            cta_label="Choose a new password",
            cta_url=f"{settings.web_base_url}/reset-password/{token}",
            footnote=(
                f"This link works once and expires in {RESET_TTL_MINUTES} minutes. "
                f"If you didn't ask for this, you can safely ignore this email. "
                f"Your password won't change."
            ),
        ),
    )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> None:
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    reset = db.query(PasswordReset).filter(PasswordReset.token_hash == token_hash).first()
    if reset is None or reset.used_at is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That reset link is no longer valid. Please request a new one"
        )
    expires_at = reset.expires_at
    if expires_at.tzinfo is None:  # SQLite loses tz info in tests
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < utcnow():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That reset link has expired. Please request a new one"
        )
    reset.user.password_hash = hash_password(payload.new_password)
    reset.used_at = utcnow()
    db.commit()


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: ChangePasswordRequest, db: DbSession, user: CurrentUser) -> None:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your current password isn't right")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
