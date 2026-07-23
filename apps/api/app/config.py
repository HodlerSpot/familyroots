import json
import os
import threading
import time
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings

_ENV_PREFIX = "FUTUREROOTS_"


def _testnet_mode_enabled() -> bool:
    return os.environ.get(f"{_ENV_PREFIX}TESTNET_MODE", "").strip().lower() in {"1", "true", "yes"}


class ManagedDbSecret:
    """Cached accessor for the RDS-managed master-user secret.

    In AWS the RDS instance's master password is generated and rotated by RDS
    itself (``manageMasterUserPassword`` in the CDK stack); the secret's JSON
    contains only ``username`` and ``password`` — host and dbname come from
    plain env vars. Because RDS can rotate the password at any time, code that
    opens NEW database connections must be able to pick up fresh values:

    - ``get()`` serves a cached ``(username, password)`` pair for up to
      ``ttl_seconds`` (default 5 min) and refetches after that, so a warm
      Lambda converges on a rotated password without a cold start.
    - ``get(force_refresh=True)`` bypasses the cache — used by ``app.db`` when
      a new connection fails to authenticate, i.e. the cached password just
      rotated out from under us mid-TTL.
    """

    def __init__(self, secret_arn: str, ttl_seconds: float = 300.0) -> None:
        self._secret_arn = secret_arn
        self._ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        self._cached: tuple[str, str] | None = None
        self._fetched_at = 0.0

    def get(self, *, force_refresh: bool = False) -> tuple[str, str]:
        """Return ``(username, password)``, fetching from Secrets Manager as needed."""
        with self._lock:
            if (
                not force_refresh
                and self._cached is not None
                and time.monotonic() - self._fetched_at < self._ttl_seconds
            ):
                return self._cached
            # boto3 is imported lazily: a dependency of the Lambda bundle, not
            # of local dev or the test suite (tests install a fake module).
            import boto3

            try:
                response = boto3.client("secretsmanager").get_secret_value(
                    SecretId=self._secret_arn
                )
                values = json.loads(response["SecretString"])
                credentials = (values["username"], values["password"])
            except Exception as exc:
                raise RuntimeError(
                    f"Could not load DB credentials from Secrets Manager "
                    f"({self._secret_arn!r}): {exc}"
                ) from exc
            self._cached = credentials
            self._fetched_at = time.monotonic()
            return self._cached


# Populated at import time when FUTUREROOTS_DB_SECRET_ARN is set (i.e. in
# AWS, unless an explicit FUTUREROOTS_DATABASE_URL overrides it). app.db uses
# it to refresh credentials for new connections after a password rotation.
db_secret: ManagedDbSecret | None = None


def _compose_database_url_from_db_secret() -> None:
    """Build FUTUREROOTS_DATABASE_URL from the RDS-managed master-user secret.

    The Lambda env carries ``FUTUREROOTS_DB_SECRET_ARN`` (the secret RDS owns,
    JSON with ``username``/``password`` only) and ``FUTUREROOTS_DB_HOST`` (the
    instance endpoint hostname — not a secret). This composes the SQLAlchemy
    URL from those parts, against the ``futureroots_testnet`` database when
    testnet mode is on and ``futureroots`` otherwise.

    Precedence: an explicitly set ``FUTUREROOTS_DATABASE_URL`` env var still
    wins (and disables the rotation hook — the operator pinned a URL). This
    runs BEFORE the consolidated-secret overlay, so the composed URL also wins
    over any ``FUTUREROOTS_DATABASE_URL`` key left in the ``futureroots/api``
    blob (that key is retired; the overlay only injects missing defaults).
    No ARN set (local dev, tests) is a complete no-op.
    """
    global db_secret
    secret_arn = os.environ.get(f"{_ENV_PREFIX}DB_SECRET_ARN")
    if not secret_arn:
        return
    if os.environ.get(f"{_ENV_PREFIX}DATABASE_URL"):
        return
    host = os.environ.get(f"{_ENV_PREFIX}DB_HOST")
    if not host:
        raise RuntimeError(
            f"{_ENV_PREFIX}DB_SECRET_ARN is set but {_ENV_PREFIX}DB_HOST is not - "
            "the stack must pass the RDS endpoint hostname alongside the secret ARN"
        )
    db_secret = ManagedDbSecret(secret_arn)
    username, password = db_secret.get()
    dbname = "futureroots_testnet" if _testnet_mode_enabled() else "futureroots"
    # RDS-generated passwords can contain URL-reserved characters — always
    # percent-encode the userinfo. (alembic/env.py additionally escapes `%`
    # for ConfigParser when it re-uses this URL.)
    os.environ[f"{_ENV_PREFIX}DATABASE_URL"] = (
        f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:5432/{dbname}"
    )


def _load_secrets_overlay() -> None:
    """Overlay sensitive settings from AWS Secrets Manager onto the process env.

    In AWS the Lambda env carries only ``FUTUREROOTS_SECRETS_ARN``; the actual
    app-level secrets (JWT secret, Stripe keys, Agora certificate) live in ONE
    consolidated Secrets Manager secret whose SecretString is a JSON object
    keyed by env-var name (``{"FUTUREROOTS_JWT_SECRET": "...", ...}``).
    Database credentials are NOT in this blob anymore — they come from the
    RDS-managed secret (``_compose_database_url_from_db_secret`` above, which
    runs first so a stale ``FUTUREROOTS_DATABASE_URL`` key left in the blob
    can never override the composed URL).

    Values are injected as *defaults*: an env var that is already set
    explicitly always wins, and local dev (no ARN set) is a complete no-op.
    Runs once at module import — i.e. once per Lambda cold start — and the
    values live in ``os.environ`` for the life of the process, so warm
    invocations never refetch.
    """
    secret_id = os.environ.get(f"{_ENV_PREFIX}SECRETS_ARN")
    if not secret_id:
        return
    # boto3 is imported lazily: it is a dependency of the Lambda bundle (and of
    # the s3/ses backends) but not of local dev or the test suite.
    import boto3

    try:
        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
        values = json.loads(response["SecretString"])
    except Exception as exc:
        # Fail fast and loud: booting with placeholder dev secrets in an
        # environment that expects real ones would be far worse than a crash.
        raise RuntimeError(
            f"Could not load application secrets from Secrets Manager ({secret_id!r}): {exc}"
        ) from exc
    if not isinstance(values, dict):
        raise RuntimeError(
            f"Secret {secret_id!r} must be a JSON object mapping env-var names to values"
        )
    # Transitional (retired key): older blobs carried
    # FUTUREROOTS_TESTNET_DATABASE_URL for the testnet Lambda. Keep mapping it
    # as a *default* so a blob that still has it doesn't point testnet at the
    # prod database; the RDS-secret composition above already set DATABASE_URL
    # in AWS, so this is inert there.
    if _testnet_mode_enabled():
        testnet_url = values.get(f"{_ENV_PREFIX}TESTNET_DATABASE_URL")
        if testnet_url:
            values = {**values, f"{_ENV_PREFIX}DATABASE_URL": testnet_url}
    for key, value in values.items():
        if key.startswith(_ENV_PREFIX) and isinstance(value, str) and key not in os.environ:
            os.environ[key] = value


# Order matters: the DB-secret composition sets FUTUREROOTS_DATABASE_URL
# first, so the overlay (defaults only) can never clobber it with a stale
# blob key.
_compose_database_url_from_db_secret()
_load_secrets_overlay()


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://futureroots:futureroots@localhost:5432/futureroots"
    jwt_secret: str = "dev-only-secret-change-in-production!"
    # Session TTLs. A normal session lasts session_ttl_minutes (the web client
    # slides this window by silently refreshing on API activity, so active users
    # never expire mid-task); ticking "Stay logged in" at login instead issues a
    # remember_me_ttl_days token not subject to the idle timeout. Both are
    # env-overridable (FUTUREROOTS_SESSION_TTL_MINUTES / _REMEMBER_ME_TTL_DAYS).
    session_ttl_minutes: int = 30
    remember_me_ttl_days: int = 30
    # Legacy: the old fixed session lifetime. No longer used for session
    # issuance (replaced by session_ttl_minutes / remember_me_ttl_days above);
    # retained so an existing FUTUREROOTS_JWT_TTL_HOURS override can't break
    # boot. The impersonation token has always used its own minutes= path.
    jwt_ttl_hours: int = 24 * 7
    # TTL of the media-only token that rides in <img>/<video> query strings.
    # Long enough that the web client's refresh-on-any-API-call keeps a normal
    # session seamless; short enough that a URL leaked via proxy logs, browser
    # history, or a Referer header goes dead within the hour.
    media_token_ttl_minutes: int = 60
    invite_ttl_days: int = 14
    # Application fee = Stripe's US-card baseline (2.9% + 30¢). The platform
    # nets ~0: it keeps this fee and pays Stripe's actual processing fee out of
    # it, absorbing the small variance on international/Amex cards.
    contribution_fee_bps: int = 290
    contribution_fee_fixed_cents: int = 30
    storage_backend: str = "local"  # local | s3
    media_bucket: str = ""
    email_backend: str = "outbox"  # outbox | ses
    ses_from_address: str = "hello@futureroots.example"
    payment_backend: str = "local"  # local | stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Second endpoint secret: Connect events (account.updated) for Express
    # accounts arrive only on a connected-accounts webhook with its own secret.
    stripe_connect_webhook_secret: str = ""
    # Premium (family subscription). Prices are Stripe Price ids — amounts live
    # in Stripe, never as floats in code. Empty ids ⇒ premium checkout 503s in
    # stripe mode ("Premium isn't set up yet") so the feature stays dark, never
    # broken.
    stripe_price_monthly: str = ""      # $9.99/mo recurring
    stripe_price_annual: str = ""       # $99/yr recurring
    stripe_price_gift_year: str = ""    # $99 one-time (12-month gift)
    premium_grant_days: int = 365
    premium_gift_amount_cents: int = 9900   # local-backend simulation + display only
    web_base_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""  # comma-separated additional allowed origins
    # Custom URL scheme the native app registers (iOS/Android). Hosted
    # Stripe/Connect flows can't redirect to a custom scheme directly — Stripe
    # requires https return URLs — so when a request comes from the mobile app
    # (X-Client-Platform: ios/android) the return URL points at the https
    # /m/return bridge page on web_base_url, which deep-links back in via this
    # scheme. Web (header absent or "web") keeps its normal hosted pages.
    mobile_deep_link_scheme: str = "futureroots"
    # Testnet harness (testnet.futureroots.app only). Gates the /testnet
    # endpoints and the points engine; the family product runs with this off.
    testnet_mode: bool = False
    # Shared secret gating the admin-only bug-verification endpoint. When empty,
    # no bug can ever be verified (so no bug_verified points can be awarded).
    testnet_admin_token: str = ""
    # X (Twitter) OAuth 2.0 confidential-client credentials for the optional
    # tester "Connect X" quest. When x_client_id is empty, the connect flow is
    # unavailable (the start endpoint 503s and the UI hides the button). The
    # main session sets these in the testnet Lambda env.
    x_client_id: str = ""
    x_client_secret: str = ""
    # Family Video Call (Agora RTC). The App ID is public (shipped to clients);
    # the App Certificate is a SECRET set only in the API env and used solely to
    # sign RTC tokens server-side — it must never reach a client or a log. When
    # the certificate is empty, token minting 503s ("Video calling isn't set up
    # yet") so the feature simply stays dark rather than handing out bad tokens.
    agora_app_id: str = "c58c8181f4204f07bc1a36d93cae5514"
    agora_app_certificate: str = ""
    # Short TTL so a removed/demoted member's token can't rejoin the live
    # channel for long; the client's token-privilege-will-expire refresh loop
    # re-checks membership + presence and re-mints while they're still allowed.
    agora_call_token_ttl_seconds: int = 300
    agora_presence_ttl_seconds: int = 30
    # Web Push (VAPID). The private key is a SECRET (in the futureroots/api
    # blob); the public key is shipped to browsers (served via
    # GET /me/notifications, so no Amplify env/rebuild is needed) and the
    # subject is a contact mailto:/URL Push services may use to reach us. When
    # the private key is empty the whole push feature stays dark: subscribe
    # 503s, dispatch sends no push, and the settings card hides the enrollment.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:hello@futureroots.app"
    # Native push (iOS/Android via Expo). The dispatcher POSTs to a HARDCODED
    # Expo host, so there is no user-controlled URL and nothing to configure to
    # send. This optional access token is a SECRET (in the futureroots/api blob)
    # used only if the Expo project enforces authenticated sends; when empty,
    # sends go out unauthenticated (Expo's default). Native push is
    # feature-dark whenever no device has enrolled a token — no key gates it.
    expo_access_token: str = ""

    model_config = {"env_file": ".env", "env_prefix": "FUTUREROOTS_"}


settings = Settings()
