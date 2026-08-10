"""Lightweight ADD COLUMN IF NOT EXISTS for hackathon schema evolution."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def ensure_schema(engine: AsyncEngine) -> None:
    statements = [
        # enums — create if missing (ignore errors)
        """DO $$ BEGIN
            CREATE TYPE baseline_type AS ENUM ('grok_generated','user_provided','none');
        EXCEPTION WHEN duplicate_object THEN null; END $$;""",
        """DO $$ BEGIN
            CREATE TYPE submission_source AS ENUM ('grok_baseline','human','other_agent');
        EXCEPTION WHEN duplicate_object THEN null; END $$;""",
        # bounty columns
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS seed_repository_url VARCHAR(512)",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS mode VARCHAR(32) DEFAULT 'optimize'",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_type baseline_type DEFAULT 'none'",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS product_spec_json JSONB",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_submission_id UUID",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_generation_run_id VARCHAR(128)",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_deployment_url VARCHAR(512)",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_model VARCHAR(128)",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_prompt_version VARCHAR(64)",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_generated_at TIMESTAMPTZ",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_evaluation_id UUID",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS baseline_eval_vector JSONB",
        "ALTER TABLE bounties ADD COLUMN IF NOT EXISTS champion_submission_id UUID",
        # submission columns
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS source_type submission_source DEFAULT 'human'",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS deployment_url VARCHAR(512)",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS generation_metadata JSONB",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS beats_grok BOOLEAN",
        "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS vs_grok_delta JSONB",
        # evaluation
        "ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS eval_vector JSONB",
        # extend bounty_status enum if needed
        """DO $$ BEGIN
            ALTER TYPE bounty_status ADD VALUE IF NOT EXISTS 'baseline_generating';
        EXCEPTION WHEN others THEN null; END $$;""",
        """DO $$ BEGIN
            ALTER TYPE bounty_status ADD VALUE IF NOT EXISTS 'grok_champion';
        EXCEPTION WHEN others THEN null; END $$;""",
        # Reply App Bot enums + tables are created via Base.metadata.create_all;
        # keep lightweight column guards if tables already exist from partial deploys.
        """DO $$ BEGIN
            CREATE TYPE reply_app_job_source AS ENUM ('mention','opportunity','manual','dry_run');
        EXCEPTION WHEN duplicate_object THEN null; END $$;""",
        """DO $$ BEGIN
            CREATE TYPE reply_app_job_status AS ENUM ('draft','queued','running','generated','replied','skipped','failed');
        EXCEPTION WHEN duplicate_object THEN null; END $$;""",
    ]
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
            except Exception:
                # best-effort; create_all handles fresh DBs
                pass
