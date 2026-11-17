from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEDCART_", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./medcart.db"  # use postgresql+psycopg://... in production
    redis_url: str = "redis://localhost:6379/0"

    # Security
    cors_origins: list[str] = ["http://localhost:5173"]
    data_encryption_keys: str = ""  # comma-separated Fernet keys, newest first (required in production)
    require_verified_email: bool = True
    rate_limit_enabled: bool = True
    trust_proxy_headers: bool = False  # set true only behind a proxy that sets X-Forwarded-For

    # Storage
    upload_dir: str = "./uploads"
    max_upload_mb: int = 10

    # Realtime calls (WebRTC). Production needs a TURN server for users behind strict NATs/mobile networks.
    stun_urls: list[str] = ["stun:stun.l.google.com:19302"]
    turn_urls: list[str] = []
    turn_username: str = ""
    turn_credential: str = ""
    turn_secret: str = ""  # coturn `static-auth-secret`: enables short-lived per-call TURN credentials

    # Language services (Google Cloud REST; any provider can implement services/language.py::Provider)
    google_api_key: str = ""
    language_provider: str = "none"  # none | google

    timezone: str = "Africa/Accra"  # medication reminder times are interpreted in this zone
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 900

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

    # Paystack (the same secret key authenticates API calls and signs webhooks; never ship it to the frontend)
    paystack_secret_key: str = ""
    payment_mode: str = "simulator"  # "simulator" (dev/test only) | "live"
    payment_callback_url: str = "http://localhost:5173/payment/complete"

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
