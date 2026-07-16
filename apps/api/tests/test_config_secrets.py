"""The Secrets Manager overlay in app.config.

The overlay runs at module import in AWS (FUTUREROOTS_SECRETS_ARN set) and
must be a complete no-op locally. These tests exercise the function directly
with a fake boto3 module — no AWS calls, and no boto3 dependency required
(boto3 lives in the `aws` dependency group, not the test env).
"""

import json
import os
import sys
import types

import pytest

import app.config as config_module
from app.config import (
    ManagedDbSecret,
    _compose_database_url_from_db_secret,
    _load_secrets_overlay,
)

ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:futureroots/api"
DB_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-1a2b3c4d"


@pytest.fixture(autouse=True)
def _restore_futureroots_env():
    """Snapshot/restore FUTUREROOTS_* env vars — the overlay writes to
    os.environ directly, which monkeypatch.setenv alone would not undo."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("FUTUREROOTS_")}
    yield
    for key in [k for k in os.environ if k.startswith("FUTUREROOTS_")]:
        del os.environ[key]
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def _reset_db_secret():
    """The composition sets the module-global accessor; isolate tests."""
    saved = config_module.db_secret
    config_module.db_secret = None
    yield
    config_module.db_secret = saved


def _install_fake_boto3(monkeypatch, *, secret_string=None, error=None, calls=None):
    class FakeClient:
        def get_secret_value(self, SecretId):
            if calls is not None:
                calls.append(SecretId)
            if error is not None:
                raise error
            return {"SecretString": secret_string, "ARN": SecretId}

    fake = types.ModuleType("boto3")
    fake.client = lambda service: FakeClient()
    monkeypatch.setitem(sys.modules, "boto3", fake)


def _install_fake_boto3_map(monkeypatch, *, responses, calls=None):
    """Fake boto3 serving a different SecretString per SecretId."""

    class FakeClient:
        def get_secret_value(self, SecretId):
            if calls is not None:
                calls.append(SecretId)
            return {"SecretString": responses[SecretId], "ARN": SecretId}

    fake = types.ModuleType("boto3")
    fake.client = lambda service: FakeClient()
    monkeypatch.setitem(sys.modules, "boto3", fake)


def _install_fake_boto3_sequence(monkeypatch, *, secret_strings, calls=None):
    """Fake boto3 serving successive SecretStrings on successive calls."""
    remaining = iter(secret_strings)

    class FakeClient:
        def get_secret_value(self, SecretId):
            if calls is not None:
                calls.append(SecretId)
            return {"SecretString": next(remaining), "ARN": SecretId}

    fake = types.ModuleType("boto3")
    fake.client = lambda service: FakeClient()
    monkeypatch.setitem(sys.modules, "boto3", fake)


def test_no_arn_is_a_complete_noop(monkeypatch):
    monkeypatch.delenv("FUTUREROOTS_SECRETS_ARN", raising=False)
    _install_fake_boto3(monkeypatch, error=AssertionError("must not be called"))
    before = dict(os.environ)
    _load_secrets_overlay()
    assert dict(os.environ) == before


def test_injects_defaults_but_explicit_env_wins(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    monkeypatch.setenv("FUTUREROOTS_JWT_SECRET", "explicit-wins")
    monkeypatch.delenv("FUTUREROOTS_STRIPE_SECRET_KEY", raising=False)
    calls = []
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps(
            {
                "FUTUREROOTS_JWT_SECRET": "from-secret",
                "FUTUREROOTS_STRIPE_SECRET_KEY": "sk_live_from_secret",
                "NOT_PREFIXED": "must-not-be-injected",
            }
        ),
        calls=calls,
    )
    _load_secrets_overlay()
    assert calls == [ARN]
    assert os.environ["FUTUREROOTS_JWT_SECRET"] == "explicit-wins"
    assert os.environ["FUTUREROOTS_STRIPE_SECRET_KEY"] == "sk_live_from_secret"
    assert "NOT_PREFIXED" not in os.environ


def test_testnet_mode_maps_testnet_database_url(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    monkeypatch.setenv("FUTUREROOTS_TESTNET_MODE", "1")
    monkeypatch.delenv("FUTUREROOTS_DATABASE_URL", raising=False)
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps(
            {
                "FUTUREROOTS_DATABASE_URL": "postgresql+psycopg://u:p@h:5432/futureroots",
                "FUTUREROOTS_TESTNET_DATABASE_URL": "postgresql+psycopg://u:p@h:5432/futureroots_testnet",
            }
        ),
    )
    _load_secrets_overlay()
    assert os.environ["FUTUREROOTS_DATABASE_URL"].endswith("/futureroots_testnet")


def test_main_lambda_keeps_prod_database_url(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    monkeypatch.delenv("FUTUREROOTS_TESTNET_MODE", raising=False)
    monkeypatch.delenv("FUTUREROOTS_DATABASE_URL", raising=False)
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps(
            {
                "FUTUREROOTS_DATABASE_URL": "postgresql+psycopg://u:p@h:5432/futureroots",
                "FUTUREROOTS_TESTNET_DATABASE_URL": "postgresql+psycopg://u:p@h:5432/futureroots_testnet",
            }
        ),
    )
    _load_secrets_overlay()
    assert os.environ["FUTUREROOTS_DATABASE_URL"].endswith("/futureroots")


def test_fetch_failure_fails_fast(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    _install_fake_boto3(monkeypatch, error=ConnectionError("no route to secretsmanager"))
    with pytest.raises(RuntimeError, match="Could not load application secrets"):
        _load_secrets_overlay()


def test_non_object_secret_fails_fast(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    _install_fake_boto3(monkeypatch, secret_string=json.dumps(["not", "a", "dict"]))
    with pytest.raises(RuntimeError, match="JSON object"):
        _load_secrets_overlay()


# --- RDS-managed DB secret: URL composition ---------------------------------


def _set_db_secret_env(monkeypatch, *, host="db.internal.example.com"):
    monkeypatch.setenv("FUTUREROOTS_DB_SECRET_ARN", DB_ARN)
    monkeypatch.setenv("FUTUREROOTS_DB_HOST", host)
    monkeypatch.delenv("FUTUREROOTS_DATABASE_URL", raising=False)
    monkeypatch.delenv("FUTUREROOTS_TESTNET_MODE", raising=False)


def test_db_secret_composes_url_with_password_quoting(monkeypatch):
    _set_db_secret_env(monkeypatch)
    # RDS-generated passwords can contain URL-reserved characters.
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps({"username": "futureroots", "password": "p@ss:w/rd%+"}),
    )
    _compose_database_url_from_db_secret()
    assert os.environ["FUTUREROOTS_DATABASE_URL"] == (
        "postgresql+psycopg://futureroots:p%40ss%3Aw%2Frd%25%2B"
        "@db.internal.example.com:5432/futureroots"
    )
    # SQLAlchemy must decode the userinfo back to the raw password.
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["FUTUREROOTS_DATABASE_URL"])
    assert url.password == "p@ss:w/rd%+"
    assert config_module.db_secret is not None


def test_db_secret_testnet_mode_targets_testnet_database(monkeypatch):
    _set_db_secret_env(monkeypatch)
    monkeypatch.setenv("FUTUREROOTS_TESTNET_MODE", "1")
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps({"username": "futureroots", "password": "pw"}),
    )
    _compose_database_url_from_db_secret()
    assert os.environ["FUTUREROOTS_DATABASE_URL"].endswith(":5432/futureroots_testnet")


def test_db_secret_explicit_database_url_wins(monkeypatch):
    _set_db_secret_env(monkeypatch)
    monkeypatch.setenv(
        "FUTUREROOTS_DATABASE_URL", "postgresql+psycopg://explicit:pin@elsewhere:5432/db"
    )
    _install_fake_boto3(monkeypatch, error=AssertionError("must not be called"))
    _compose_database_url_from_db_secret()
    assert (
        os.environ["FUTUREROOTS_DATABASE_URL"]
        == "postgresql+psycopg://explicit:pin@elsewhere:5432/db"
    )
    # The rotation hook must stay disabled too: the operator pinned a URL.
    assert config_module.db_secret is None


def test_no_db_secret_arn_is_a_complete_noop(monkeypatch):
    monkeypatch.delenv("FUTUREROOTS_DB_SECRET_ARN", raising=False)
    _install_fake_boto3(monkeypatch, error=AssertionError("must not be called"))
    before = dict(os.environ)
    _compose_database_url_from_db_secret()
    assert dict(os.environ) == before
    assert config_module.db_secret is None


def test_db_secret_missing_host_fails_fast(monkeypatch):
    monkeypatch.setenv("FUTUREROOTS_DB_SECRET_ARN", DB_ARN)
    monkeypatch.delenv("FUTUREROOTS_DB_HOST", raising=False)
    monkeypatch.delenv("FUTUREROOTS_DATABASE_URL", raising=False)
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps({"username": "futureroots", "password": "pw"}),
    )
    with pytest.raises(RuntimeError, match="DB_HOST"):
        _compose_database_url_from_db_secret()


def test_db_secret_composition_beats_stale_blob_database_url(monkeypatch):
    """A retired FUTUREROOTS_DATABASE_URL key left in the futureroots/api blob
    must never override the URL composed from the RDS-managed secret — the
    composition runs first and the overlay only injects missing defaults."""
    _set_db_secret_env(monkeypatch)
    monkeypatch.setenv("FUTUREROOTS_SECRETS_ARN", ARN)
    monkeypatch.delenv("FUTUREROOTS_JWT_SECRET", raising=False)
    _install_fake_boto3_map(
        monkeypatch,
        responses={
            DB_ARN: json.dumps({"username": "futureroots", "password": "fresh"}),
            ARN: json.dumps(
                {
                    "FUTUREROOTS_DATABASE_URL": "postgresql+psycopg://stale:stale@old-host:5432/futureroots",
                    "FUTUREROOTS_JWT_SECRET": "jwt-from-blob",
                }
            ),
        },
    )
    _compose_database_url_from_db_secret()
    _load_secrets_overlay()
    assert os.environ["FUTUREROOTS_DATABASE_URL"] == (
        "postgresql+psycopg://futureroots:fresh@db.internal.example.com:5432/futureroots"
    )
    assert os.environ["FUTUREROOTS_JWT_SECRET"] == "jwt-from-blob"


# --- RDS-managed DB secret: cached accessor / rotation refresh --------------


def test_managed_db_secret_caches_within_ttl(monkeypatch):
    calls = []
    _install_fake_boto3(
        monkeypatch,
        secret_string=json.dumps({"username": "u", "password": "p1"}),
        calls=calls,
    )
    secret = ManagedDbSecret(DB_ARN, ttl_seconds=300)
    assert secret.get() == ("u", "p1")
    assert secret.get() == ("u", "p1")
    assert calls == [DB_ARN]


def test_managed_db_secret_force_refresh_bypasses_cache(monkeypatch):
    calls = []
    _install_fake_boto3_sequence(
        monkeypatch,
        secret_strings=[
            json.dumps({"username": "u", "password": "before-rotation"}),
            json.dumps({"username": "u", "password": "after-rotation"}),
        ],
        calls=calls,
    )
    secret = ManagedDbSecret(DB_ARN, ttl_seconds=300)
    assert secret.get() == ("u", "before-rotation")
    assert secret.get(force_refresh=True) == ("u", "after-rotation")
    # And the fresh value becomes the cached one.
    assert secret.get() == ("u", "after-rotation")
    assert calls == [DB_ARN, DB_ARN]


def test_managed_db_secret_refetches_after_ttl_expiry(monkeypatch):
    calls = []
    _install_fake_boto3_sequence(
        monkeypatch,
        secret_strings=[
            json.dumps({"username": "u", "password": "p1"}),
            json.dumps({"username": "u", "password": "p2"}),
        ],
        calls=calls,
    )
    # ttl 0: every get() is past the TTL, so it refetches.
    secret = ManagedDbSecret(DB_ARN, ttl_seconds=0)
    assert secret.get() == ("u", "p1")
    assert secret.get() == ("u", "p2")
    assert calls == [DB_ARN, DB_ARN]


def test_managed_db_secret_fetch_failure_raises(monkeypatch):
    _install_fake_boto3(monkeypatch, error=ConnectionError("no route to secretsmanager"))
    secret = ManagedDbSecret(DB_ARN)
    with pytest.raises(RuntimeError, match="DB credentials"):
        secret.get()


# --- app.db: auth-failure retry on new connections after rotation -----------


class _FakeRotatingSecret:
    """get() returns the stale password until force_refresh is requested."""

    def __init__(self):
        self.calls = []

    def get(self, *, force_refresh=False):
        self.calls.append(force_refresh)
        return ("futureroots", "fresh-pw" if force_refresh else "stale-pw")


class _FakeDialect:
    def __init__(self, error_factory):
        self.attempts = []
        self._error_factory = error_factory

    def connect(self, *cargs, **cparams):
        self.attempts.append(dict(cparams))
        if cparams["password"] == "stale-pw":
            raise self._error_factory()
        return "dbapi-connection"


def _auth_error():
    exc = Exception('connection failed: FATAL:  password authentication failed for user "futureroots"')
    exc.sqlstate = "28P01"
    return exc


def test_is_auth_failure_classification():
    from app.db import _is_auth_failure

    assert _is_auth_failure(_auth_error())
    sqlstate_only = Exception("boom")
    sqlstate_only.sqlstate = "28000"
    assert _is_auth_failure(sqlstate_only)
    message_only = Exception("FATAL:  password authentication failed")
    assert _is_auth_failure(message_only)
    assert not _is_auth_failure(Exception("could not connect to server: Connection refused"))


def test_connect_retries_once_with_fresh_password_on_auth_failure():
    from app.db import _connect_with_managed_credentials

    secret = _FakeRotatingSecret()
    dialect = _FakeDialect(_auth_error)
    conn = _connect_with_managed_credentials(dialect, (), {"host": "h", "dbname": "d"}, secret)
    assert conn == "dbapi-connection"
    assert secret.calls == [False, True]
    assert [a["password"] for a in dialect.attempts] == ["stale-pw", "fresh-pw"]


def test_connect_non_auth_error_propagates_without_refetch():
    from app.db import _connect_with_managed_credentials

    secret = _FakeRotatingSecret()
    dialect = _FakeDialect(lambda: ConnectionRefusedError("connection refused"))
    with pytest.raises(ConnectionRefusedError):
        _connect_with_managed_credentials(dialect, (), {"host": "h"}, secret)
    assert secret.calls == [False]
    assert len(dialect.attempts) == 1
