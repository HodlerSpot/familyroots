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
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
)
from ..security import create_access_token, hash_password, verify_password
from ..services.email import get_email_sender

RESET_TTL_MINUTES = 60

router = APIRouter(prefix="/auth", tags=["auth"])


def _send_welcome_email(user: User) -> None:
    get_email_sender().send(
        to=user.email,
        subject=f"Welcome to FutureRoots, {user.display_name} 🌱",
        body=(
            f"Hi {user.display_name},\n\n"
            f"Welcome to FutureRoots — your family's private space for memories, "
            f"milestones, and building a future together.\n\n"
            f"Here's how families use it:\n\n"
            f"  🏡  Create your family space and add your children — each child gets\n"
            f"      a vault of memories that stays with them for life.\n"
            f"  💌  Invite grandparents and relatives with a simple email link.\n"
            f"  🎉  Share milestones — first steps, recitals, big wins — and the\n"
            f"      whole family celebrates with you.\n"
            f"  🌳  Grow their future fund — family members can add a gift in under\n"
            f"      a minute, right from a milestone email.\n"
            f"  ✉️  Seal time capsules to be opened at just the right moment,\n"
            f"      years from now.\n\n"
            f"Start here: {settings.web_base_url}/family\n\n"
            f"We're glad your family is here.\n\n"
            f"With warmth,\nThe FutureRoots team"
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
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


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
            f"If you didn't ask for this, you can safely ignore this email — "
            f"your password won't change.\n\n"
            f"With warmth,\nThe FutureRoots team"
        ),
    )


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(payload: ResetPasswordRequest, db: DbSession) -> None:
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    reset = db.query(PasswordReset).filter(PasswordReset.token_hash == token_hash).first()
    if reset is None or reset.used_at is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That reset link is no longer valid — request a new one"
        )
    expires_at = reset.expires_at
    if expires_at.tzinfo is None:  # SQLite loses tz info in tests
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < utcnow():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "That reset link has expired — request a new one"
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
