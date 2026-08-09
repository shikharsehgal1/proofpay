from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env", "../../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ProofPay"
    app_env: str = "development"
    app_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    secret_key: str = "dev-only-change-me"
    token_encryption_key: str = ""
    cors_origins: str = "http://localhost:3000"

    database_url: str = "postgresql+asyncpg://proofpay:proofpay@localhost:5432/proofpay"
    database_url_sync: str = "postgresql://proofpay:proofpay@localhost:5432/proofpay"
    redis_url: str = "redis://localhost:6379/0"

    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    xai_model: str = "grok-4.5"
    xai_imagine_image_model: str = "grok-imagine-image"

    x_client_id: str = ""
    x_client_secret: str = ""
    x_bearer_token: str = ""
    x_api_key: str = ""
    x_api_secret: str = ""
    x_oauth_callback_url: str = "http://localhost:3000/api/auth/x/callback"
    x_oauth_scopes: str = "tweet.read tweet.write users.read offline.access media.write"
    x_webhook_url: str = ""
    x_webhook_crc_secret: str = ""

    github_token: str = ""

    evaluator_image: str = "proofpay-evaluator:latest"
    evaluator_timeout_sec: int = 600
    evaluator_memory_mb: int = 1024
    evaluator_cpus: float = 1.0
    workspaces_dir: str = "./workspaces"
    artifacts_dir: str = "./artifacts"
    evaluator_docker_enabled: bool = True

    grok_cli_path: str = "grok"
    grok_build_enabled: bool = False

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def oauth_scope_list(self) -> List[str]:
        return [s.strip() for s in self.x_oauth_scopes.split() if s.strip()]

    @property
    def xai_configured(self) -> bool:
        return bool(self.xai_api_key)

    @property
    def x_oauth_configured(self) -> bool:
        return bool(self.x_client_id and self.x_client_secret)

    @property
    def x_app_configured(self) -> bool:
        return bool(self.x_bearer_token or (self.x_api_key and self.x_api_secret))


@lru_cache
def get_settings() -> Settings:
    return Settings()
