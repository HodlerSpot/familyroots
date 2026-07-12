from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://futureroots:futureroots@localhost:5432/futureroots"
    jwt_secret: str = "dev-only-secret-change-in-production!"
    jwt_ttl_hours: int = 24 * 7
    invite_ttl_days: int = 14
    contribution_fee_bps: int = 250  # platform fee in basis points (2.5%)
    storage_backend: str = "local"  # local | s3
    media_bucket: str = ""
    email_backend: str = "outbox"  # outbox | ses
    ses_from_address: str = "hello@futureroots.example"
    payment_backend: str = "local"  # local | stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    web_base_url: str = "http://localhost:3000"
    cors_extra_origins: str = ""  # comma-separated additional allowed origins
    # Testnet harness (testnet.futureroots.app only). Gates the /testnet
    # endpoints and the points engine; the family product runs with this off.
    testnet_mode: bool = False
    # Shared secret gating the admin-only bug-verification endpoint. When empty,
    # no bug can ever be verified (so no bug_verified points can be awarded).
    testnet_admin_token: str = ""

    model_config = {"env_file": ".env", "env_prefix": "FUTUREROOTS_"}


settings = Settings()
