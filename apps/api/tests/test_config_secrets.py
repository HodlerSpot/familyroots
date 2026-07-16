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

from app.config import _load_secrets_overlay

ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:futureroots/api"


@pytest.fixture(autouse=True)
def _restore_futureroots_env():
    """Snapshot/restore FUTUREROOTS_* env vars — the overlay writes to
    os.environ directly, which monkeypatch.setenv alone would not undo."""
    saved = {k: v for k, v in os.environ.items() if k.startswith("FUTUREROOTS_")}
    yield
    for key in [k for k in os.environ if k.startswith("FUTUREROOTS_")]:
        del os.environ[key]
    os.environ.update(saved)


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
