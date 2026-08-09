"""Background worker entrypoint (optional Redis ARQ).

For the hackathon, evaluations also run inline/background tasks from the API.
This module can process a Redis queue when REDIS is available.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionLocal
from app.services.eval_pipeline import run_evaluation_job


async def evaluate_submission_task(ctx, submission_id: str) -> dict:
    async with SessionLocal() as session:
        ev = await run_evaluation_job(session, UUID(submission_id))
        return {"evaluation_id": str(ev.id), "status": ev.status.value}


class WorkerSettings:
    functions = [evaluate_submission_task]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)


async def main() -> None:
    print("ProofPay worker starting (ARQ). Enqueue evaluate_submission_task jobs.")
    # Keep process alive with ARQ CLI typically: arq app.worker.WorkerSettings
    # This module supports: python -m app.worker for health message.
    try:
        pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        await pool.aclose()
        print("Redis OK. Run: arq app.worker.WorkerSettings")
    except Exception as e:
        print(f"Redis not available ({e}). API background tasks will run evaluations.")


if __name__ == "__main__":
    asyncio.run(main())
