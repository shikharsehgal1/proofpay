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
    app_base_url: str = "https://proofpay-web.fly.dev"
    api_base_url: str = "https://proofpay-api.fly.dev"
    secret_key: str = "dev-only-change-me"
    token_encryption_key: str = ""
    cors_origins: str = "https://proofpay-web.fly.dev,http://localhost:3000"

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
    x_oauth_callback_url: str = "https://proofpay-web.fly.dev/api/auth/x/callback"
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

    # ─── Grok Reply App Bot (dedicated X account — not creator OAuth) ───
    reply_app_bot_enabled: bool = False
    reply_app_bot_x_user_id: str = ""
    reply_app_bot_x_username: str = ""
    reply_app_bot_access_token: str = ""
    reply_app_bot_refresh_token: str = ""
    reply_app_attach_preview_image: bool = True
    reply_app_max_jobs_per_hour: int = 30
    reply_app_reply_template: str = "Built you a quick app for this → {url}"
    # Opportunity scanner
    reply_app_scan_enabled: bool = True
    reply_app_scan_auto_reply: bool = False  # drafts only until explicitly enabled
    reply_app_scan_min_score: float = 0.72
    reply_app_scan_max_tweets: int = 40
    reply_app_scan_hours: int = 24
    # Comma-separated usernames (no @). Starter watchlist for high-signal builder/product tweets.
    reply_app_scan_accounts: str = (
        "paulg,levelsio,swyx,jason,naval,pmarca,dhh,marc_louvion,"
        "steipete,dannyroberts,t3dotgg,shadcn,vercel,linear"
    )

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

    @property
    def reply_app_bot_configured(self) -> bool:
        return bool(
            self.reply_app_bot_enabled
            and self.reply_app_bot_access_token
            and self.reply_app_bot_x_user_id
        )

    @property
    def reply_app_scan_account_list(self) -> List[str]:
        return [
            a.strip().lstrip("@")
            for a in self.reply_app_scan_accounts.split(",")
            if a.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
