from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://futureroots:futureroots@localhost:5432/futureroots"
    jwt_secret: str = "dev-only-secret-change-in-production!"
    jwt_ttl_hours: int = 24 * 7
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
    web_base_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""  # comma-separated additional allowed origins
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

    model_config = {"env_file": ".env", "env_prefix": "FUTUREROOTS_"}


settings = Settings()
