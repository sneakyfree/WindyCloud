"""Settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth
    windy_pro_jwks_url: str = "https://windyword.ai/.well-known/jwks.json"
    eternitas_jwks_url: str = "https://eternitas.ai/.well-known/eternitas-keys"

    # Optional audience / issuer validation (Wave 7 G7). Empty = accept
    # any signed token from the JWKS (pre-Wave-7 behaviour). Set these in
    # prod to reject tokens minted for another product/audience even if
    # signed by the same hub — prevents cross-product token confusion.
    windy_cloud_expected_audience: str = ""       # expected `aud` claim
    windy_pro_expected_issuer: str = ""           # expected `iss` for Pro tokens
    eternitas_expected_issuer: str = ""           # expected `iss` for Eternitas tokens

    # Eternitas Trust API (Wave 3/4 — passport trust-tier lookups)
    # Default 8500 per Wave 4 spec. See deploy/docs/env-vars.md for prod.
    eternitas_url: str = "http://localhost:8500"
    eternitas_use_mock: bool = False  # When true, TrustClient skips HTTP
    eternitas_webhook_secret: str = ""  # HMAC for trust.changed inbound
    trust_cache_ttl_seconds: int = 300  # 5 min
    trust_http_timeout_seconds: float = 3.0

    # R2 Storage — no default bucket name so a partial prod config fails
    # at startup (see r2_misconfiguration_reason below) instead of silently
    # pointing at a nonexistent bucket.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
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
    # Pre-Wave-7 this was 500 MB while `tier_quota_free` was 5 GB — two
    # sources of truth for "free tier" that silently disagreed. Now it
    # tracks `tier_quota_free` by default; override only if you actively
    # want the un-provisioned fallback to differ from the free-tier plan.
    default_storage_quota: int = 5_368_709_120  # 5 GB, matches tier_quota_free
    # Per-upload size ceiling. Must sit well under Fargate task memory
    # (CLOUD_DEPLOYMENT.md §5.2 provisions 1024 MB) so a single legit
    # max-sized upload can't OOM a worker. ALB / WAF should enforce the
    # same limit at the edge. Override per-environment via MAX_UPLOAD_SIZE.
    max_upload_size: int = 268_435_456  # 256 MB
    max_servers_per_user: int = 5

    # Tier quotas (bytes) — Wave 2 contract #1. The canonical vocab:
    # free / pro / ultra / max. `PLAN_TIERS` in routes/billing.py reads
    # from these.
    tier_quota_free: int = 5_368_709_120       # 5 GB
    tier_quota_pro: int = 107_374_182_400      # 100 GB
    tier_quota_ultra: int = 1_099_511_627_776  # 1 TB
    tier_quota_max: int = 5_497_558_138_880    # 5 TB

    # Shared secrets for service-to-service calls
    identity_webhook_secret: str = ""  # HMAC secret for /webhooks/identity/created
    service_token: str = ""            # X-Service-Token for internal callers

    # Windy Chat push-gateway (Wave 8 — grandma-ribbon first-backup notification)
    chat_push_gateway_url: str = ""
    chat_push_service_token: str = ""

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
        """True only when *all* the pieces needed to reach R2 are present.

        Bucket must be explicitly set — no default — so a partial config
        doesn't quietly fall back to LocalDiskProvider in production. Use
        `r2_misconfiguration_reason` to surface a specific error.
        """
        return bool(
            self.r2_account_id and self.r2_access_key_id and self.r2_secret_access_key and self.r2_bucket
        )

    @property
    def r2_misconfiguration_reason(self) -> str | None:
        """Return a human-readable reason if R2 is partially configured.

        Returns None when either fully configured or completely unset
        (the latter falls through to LocalDiskProvider for dev). Anything
        in between — e.g. creds set but bucket missing — should block
        startup with the returned string.
        """
        any_r2 = bool(
            self.r2_account_id
            or self.r2_access_key_id
            or self.r2_secret_access_key
            or self.r2_bucket
        )
        if not any_r2:
            return None
        missing = [
            name
            for name, value in {
                "R2_ACCOUNT_ID": self.r2_account_id,
                "R2_ACCESS_KEY_ID": self.r2_access_key_id,
                "R2_SECRET_ACCESS_KEY": self.r2_secret_access_key,
                "R2_BUCKET": self.r2_bucket,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return (
            "R2 is partially configured — set all of these or unset them all "
            f"to fall back to local disk: missing {', '.join(missing)}"
        )

    @property
    def r2_endpoint_url(self) -> str:
        if self.r2_endpoint:
            return self.r2_endpoint
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
