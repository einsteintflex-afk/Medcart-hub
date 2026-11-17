from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEDCART_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./medcart.db"  # use postgresql+psycopg://... in production
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "CHANGE-ME-in-production"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Pricing (minor units = pesewas; GH₵1 = 100 pesewas)
    currency: str = "GHS"
    patient_subscription_pesewas: int = 6000  # GH₵60 / month
    doctor_consultation_pesewas: int = 20000  # GH₵200 / consultation
    # ASSUMPTIONS - not specified in the product brief; confirm with finance before launch.
    pharmacist_consultation_pesewas: int = 0
    professional_subscription_pesewas: int = 10000
    platform_commission_bps: int = 1500  # 15% in basis points

    # Contribution credits (stored as tenths of a unit to avoid float error)
    credit_per_contribution_tenths: int = 8  # 0.8 units
    credit_renewal_threshold_tenths: int = 1200  # 120 units
    min_contribution_chars: int = 400

    # Fincore
    fincore_base_url: str = "https://api.fincore.example"
    fincore_api_key: str = ""
    fincore_webhook_secret: str = ""
    fincore_webhook_tolerance_seconds: int = 300
    fincore_mode: str = "simulator"  # "simulator" (dev/test only) | "live"

    # AI
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"

    # Notifications
    email_backend: str = "console"
    sms_backend: str = "console"

    emergency_numbers: dict[str, str] = {"GH": "112", "NG": "112", "KE": "999", "FR": "15", "ES": "112"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
