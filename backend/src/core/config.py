from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "VasoolKaro API"
    environment: str = "development"  # development | production

    # Database
    database_url: str = "postgresql+psycopg://vasoolkaro:vasoolkaro@localhost:5432/vasoolkaro"

    # Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30
    password_reset_ttl_seconds: int = 3600

    # Internal service token for /internal endpoints (worker dispatch)
    internal_service_token: str = "dev-internal-token"

    # Push (Web Push); delivery is a no-op unless keys are configured
    push_vapid_public_key: str | None = None
    push_vapid_private_key: str | None = None
    push_vapid_subject: str = "mailto:ops@vasoolkaro.example"

    # Email; sending is a no-op unless SMTP is configured
    email_smtp_url: str | None = None
    email_from: str = "no-reply@vasoolkaro.example"

    # Abuse controls
    receipt_submit_rate_limit: int = 12
    receipt_submit_window_seconds: int = 3600
    login_rate_limit: int = 10
    login_window_seconds: int = 900
    referral_invite_cap: int = 20
    referral_bonus_cents: int = 500
    payout_minimum_cents: int = 500

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Avatars
    avatar_max_bytes: int = 2 * 1024 * 1024
    avatar_dir: str = "data/avatars"


@lru_cache
def get_settings() -> Settings:
    return Settings()
