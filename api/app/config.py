"""Settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    windy_pro_jwks_url: str = "https://windypro.thewindstorm.uk/.well-known/jwks.json"
    eternitas_jwks_url: str = "https://eternitas.thewindstorm.uk/.well-known/eternitas-keys"

    # R2 Storage
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "windy-cloud-storage"
    r2_endpoint: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///data/windy_cloud.db"

    # Compute
    runpod_api_key: str = ""
    runpod_endpoint_id: str = ""
    stt_markup: float = 3.0
    stt_free_minutes: int = 10

    # AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Server
    host: str = "0.0.0.0"
    port: int = 8200
    log_level: str = "info"
    cors_origins: str = "https://windypro.thewindstorm.uk,http://localhost:3000"

    # Quotas
    default_storage_quota: int = 524_288_000  # 500MB
    max_upload_size: int = 1_073_741_824  # 1GB

    # Mock providers (for testing/dev without real cloud credentials)
    use_mock_providers: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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
