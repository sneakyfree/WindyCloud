"""Settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    windy_pro_jwks_url: str = "https://windyword.ai/.well-known/jwks.json"
    eternitas_jwks_url: str = "https://eternitas.ai/.well-known/eternitas-keys"

    # R2 Storage
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "windy-cloud-storage"
    r2_endpoint: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///data/windy_cloud.db"

    # Compute — RunPod (Phase 1)
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    stt_markup: float = 3.0
    stt_free_minutes: int = 10

    # Compute — AWS SageMaker (Phase 2)
    sagemaker_endpoint_name: str = ""

    # AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Deploy host (for CI/CD SSH target)
    deploy_host: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8200
    log_level: str = "info"
    dev_mode: bool = False
    cors_origins: str = "https://windyword.ai,https://windycloud.com"

    # Quotas
    default_storage_quota: int = 524_288_000  # 500MB
    max_upload_size: int = 1_073_741_824  # 1GB
    max_servers_per_user: int = 5

    # Sentry
    sentry_dsn: str = ""

    # Pricing page (for upgrade redirects)
    pricing_url: str = "https://windyword.ai/pricing"

    # Mock providers (for testing/dev without real cloud credentials)
    use_mock_providers: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if self.dev_mode:
            origins.append("http://localhost:3000")
            origins.append("http://localhost:8200")
        return origins

    @property
    def r2_configured(self) -> bool:
        return bool(self.r2_account_id and self.r2_access_key_id)

    @property
    def r2_endpoint_url(self) -> str:
        if self.r2_endpoint:
            return self.r2_endpoint
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
