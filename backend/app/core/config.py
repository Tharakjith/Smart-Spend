from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"), extra="ignore")

    environment: str = "development"  # development | test | production
    app_name: str = "SmartSpend"
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    database_url: str = "postgresql+psycopg://smartspend:smartspend@localhost:5432/smartspend"

    # Secrets. Defaults are only acceptable outside production (enforced in validate_for_production).
    secret_key: str = "dev-insecure-secret-change-me-not-for-production"
    encryption_key: str = ""  # Fernet key for MFA secrets; derived from secret_key when empty (dev only)

    access_token_minutes: int = 15
    refresh_token_days: int = 14
    require_email_verification: bool = True
    cookie_secure: bool = False

    # Celery / Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = True

    # Storage
    storage_backend: str = "local"  # local | s3
    storage_dir: Path = BACKEND_DIR / "var" / "storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_sse: str = "AES256"  # server-side encryption for S3; "" for MinIO without a KMS (use encrypted volumes)
    download_link_seconds: int = 300

    # Uploads
    max_upload_bytes: int = 15 * 1024 * 1024
    malware_scanner: str = "none"  # none | clamav
    clamav_host: str = "localhost"
    clamav_port: int = 3310

    # OCR
    ocr_provider: str = "auto"  # auto | tesseract | rapidocr | none (see app/modules/documents/ocr.py)
    tesseract_cmd: str = ""

    # Optional AI (off by default; never the sole basis of a merge)
    ai_provider: str = "none"  # none | anthropic
    ai_allow_document_sharing: bool = False
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"

    # Email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "SmartSpend <no-reply@smartspend.local>"

    rate_limit_auth_per_minute: int = 10
    demo_mode: bool = False

    log_level: str = "INFO"
    extra: dict = Field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_for_production(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key.startswith("dev-") or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
        if not self.encryption_key:
            problems.append("ENCRYPTION_KEY must be set (Fernet key)")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production (HTTPS)")
        if self.demo_mode:
            problems.append("DEMO_MODE must be false in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_for_production()
    return s
