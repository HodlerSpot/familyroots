from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://futureroots:futureroots@localhost:5432/futureroots"
    jwt_secret: str = "dev-only-secret-change-in-production!"
    jwt_ttl_hours: int = 24 * 7
    invite_ttl_days: int = 14
    contribution_fee_bps: int = 250  # platform fee in basis points (2.5%)
    web_base_url: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "env_prefix": "FUTUREROOTS_"}


settings = Settings()
