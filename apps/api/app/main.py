from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.db import Base, engine
from app.db_migrate import ensure_schema
from app.routes import auth, bounties, system, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.workspaces_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
    # Auto-create tables for hackathon velocity; Alembic also provided
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_schema(engine)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ProofPay API",
        version="0.1.0",
        description=(
            "Verified bounties on X with real Grok investigation and sandboxed evaluation. "
            "No synthetic X/Grok/evaluation results."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(system.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(bounties.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")

    artifacts = Path(settings.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts)), name="artifacts")
    return app


app = create_app()
