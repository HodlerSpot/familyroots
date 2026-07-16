from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# --- RDS-managed password rotation resilience (AWS only) ---------------------
# The master password is generated and rotated by RDS/Secrets Manager, so a
# warm Lambda's cached credentials can go stale mid-process. Established
# connections survive a rotation, but every NEW connection the pool opens must
# authenticate with the CURRENT password. The `do_connect` hook below therefore
# injects credentials from the cached secret accessor (5-min TTL) on every
# connection attempt, and on an authentication failure force-refreshes the
# secret and retries exactly once — covering the window where the password
# rotated within the TTL. Any other connect error (network, DNS, DB down)
# propagates untouched. Locally (no FUTUREROOTS_DB_SECRET_ARN) none of this is
# registered and the URL's inline credentials are used as-is.

# invalid_authorization_specification / invalid_password — what Postgres
# reports when the password is wrong (28P01) or auth is otherwise refused.
_AUTH_FAILURE_SQLSTATES = {"28000", "28P01"}


def _is_auth_failure(exc: BaseException) -> bool:
    """Does this DBAPI connect error mean 'bad credentials' (vs. DB unreachable)?"""
    if getattr(exc, "sqlstate", None) in _AUTH_FAILURE_SQLSTATES:
        return True
    # psycopg doesn't always attach a SQLSTATE to connection-phase errors;
    # fall back on the server's message text.
    return "password authentication failed" in str(exc).lower()


def _connect_with_managed_credentials(dialect, cargs, cparams, secret):
    """Open a DBAPI connection using the managed secret, retrying once on auth failure."""
    user, password = secret.get()
    cparams.update(user=user, password=password)
    try:
        return dialect.connect(*cargs, **cparams)
    except Exception as exc:
        if not _is_auth_failure(exc):
            raise
        # The cached password just rotated out from under us: bypass the TTL
        # cache, pull the fresh secret, and try once more.
        user, password = secret.get(force_refresh=True)
        cparams.update(user=user, password=password)
        return dialect.connect(*cargs, **cparams)


if config.db_secret is not None:

    @event.listens_for(engine, "do_connect")
    def _do_connect(dialect, conn_rec, cargs, cparams):
        # Returning a connection tells SQLAlchemy to skip its default connect.
        return _connect_with_managed_credentials(dialect, cargs, cparams, config.db_secret)
