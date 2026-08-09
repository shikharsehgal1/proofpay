from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.schemas import HealthResponse, IntegrationStatus

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health():
    s = get_settings()
    return HealthResponse(
        status="ok",
        app=s.app_name,
        integrations={
            "xai": s.xai_configured,
            "x_oauth": s.x_oauth_configured,
            "github_token": bool(s.github_token),
            "x_money": False,
        },
    )


@router.get("/integrations", response_model=IntegrationStatus)
async def integrations():
    s = get_settings()
    return IntegrationStatus(
        xai={
            "configured": s.xai_configured,
            "base_url": s.xai_base_url,
            "model": s.xai_model,
            "required_env": ["XAI_API_KEY"],
            "obtain": "https://console.x.ai",
            "status": "ready" if s.xai_configured else "ACTION_REQUIRED",
        },
        x_oauth={
            "configured": s.x_oauth_configured,
            "callback": s.x_oauth_callback_url,
            "scopes": s.oauth_scope_list,
            "required_env": ["X_CLIENT_ID", "X_CLIENT_SECRET"],
            "obtain": "https://developer.x.com/en/portal/dashboard",
            "status": "ready" if s.x_oauth_configured else "ACTION_REQUIRED",
        },
        x_webhooks={
            "webhook_url": s.x_webhook_url or None,
            "crc_configured": bool(s.x_webhook_crc_secret or s.x_api_secret or s.x_client_secret),
            "required": "Public HTTPS URL + X Activity / Webhooks registration",
            "status": "ACTION_REQUIRED" if not s.x_webhook_url else "configured_url",
            "note": "Use POST /webhooks/x/poll-conversations for real search-based ingest until webhooks are live",
        },
        github={
            "token_configured": bool(s.github_token),
            "required_env": ["GITHUB_TOKEN (optional)"],
            "note": "Public repos work without token; token raises rate limits",
        },
        evaluator={
            "docker_enabled": s.evaluator_docker_enabled,
            "image": s.evaluator_image,
            "workspaces": s.workspaces_dir,
        },
        x_money={
            "public_api": False,
            "status": "UNAVAILABLE",
            "statement": (
                "X Money is not currently programmatically accessible through a public API "
                "available to this project."
            ),
            "product_state": "VERIFIED / READY_FOR_SETTLEMENT without automated payout",
        },
    )
