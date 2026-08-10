from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


# ─── Contracts (Grok structured output) ─────────────────


class BenchmarkSpec(BaseModel):
    name: str = "latency"
    command: str = Field(description="Shell command that prints a JSON metrics object to stdout")
    metric_key: str = "p95_ms"
    higher_is_better: bool = False
    min_improvement_pct: float = 25.0
    warmup_runs: int = 1
    measured_runs: int = 5


class TestSpec(BaseModel):
    name: str
    command: str
    hidden: bool = False


class IntegrityRules(BaseModel):
    protected_paths: list[str] = Field(default_factory=lambda: ["tests/", "bench/", "eval/"])
    forbid_env_checks: bool = True
    forbid_benchmark_hardcoding: bool = True
    require_semantic_equivalence: bool = True


class ExecutableContract(BaseModel):
    """Structured, executable bounty contract compiled by Grok."""

    summary: str
    target_description: str
    repository_url: str
    baseline_ref: str
    build_command: str = "python3 -m pip install -e '.[dev]' -q || python3 -m pip install -r requirements.txt -q || true"
    setup_notes: str = ""
    visible_tests: list[TestSpec]
    hidden_tests: list[TestSpec]
    benchmark: BenchmarkSpec
    integrity: IntegrityRules
    acceptance_criteria: list[str]
    evaluation_plan: list[str]
    risk_notes: list[str] = Field(default_factory=list)


# ─── API request/response ───────────────────────────────


class HealthResponse(BaseModel):
    status: str
    app: str
    integrations: dict[str, Any]


class UserOut(BaseModel):
    id: UUID
    x_user_id: str
    x_username: str
    display_name: Optional[str] = None
    profile_image_url: Optional[str] = None

    model_config = {"from_attributes": True}


class BountyCreate(BaseModel):
    title: str = Field(min_length=3, max_length=256)
    natural_language: str = Field(min_length=10)
    reward_amount: float = Field(ge=0)
    reward_currency: str = "USD"
    repository_url: str
    baseline_ref: str = "main"
    # optimize (legacy) | beat_grok (Grok baseline first) | product (app gen — scaffold)
    mode: str = "beat_grok"


class BountyOut(BaseModel):
    id: UUID
    title: str
    natural_language: str
    reward_amount: float
    reward_currency: str
    repository_url: str
    baseline_ref: str
    baseline_commit_sha: Optional[str] = None
    seed_repository_url: Optional[str] = None
    mode: str = "optimize"
    baseline_type: str = "none"
    status: str
    contract_json: Optional[dict[str, Any]] = None
    product_spec_json: Optional[dict[str, Any]] = None
    contract_approved: bool
    baseline_metrics: Optional[dict[str, Any]] = None
    baseline_submission_id: Optional[UUID] = None
    baseline_generation_run_id: Optional[str] = None
    baseline_deployment_url: Optional[str] = None
    baseline_model: Optional[str] = None
    baseline_prompt_version: Optional[str] = None
    baseline_generated_at: Optional[datetime] = None
    baseline_evaluation_id: Optional[UUID] = None
    baseline_eval_vector: Optional[dict[str, Any]] = None
    champion_submission_id: Optional[UUID] = None
    x_post_id: Optional[str] = None
    x_post_url: Optional[str] = None
    public_slug: str
    settlement_status: str
    settlement_note: Optional[str] = None
    winner_submission_id: Optional[UUID] = None
    created_at: datetime
    published_at: Optional[datetime] = None
    creator: Optional[UserOut] = None

    model_config = {"from_attributes": True}


class ContractApprove(BaseModel):
    approved: bool = True
    edits: Optional[dict[str, Any]] = None


class SubmissionCreateManual(BaseModel):
    """Manual submission path (still real GitHub + same pipeline). For demo ops if needed."""

    github_url: str
    submitter_x_username: Optional[str] = None
    x_reply_id: Optional[str] = None
    x_reply_text: Optional[str] = None


class EvaluationOut(BaseModel):
    id: UUID
    status: str
    visible_tests_passed: Optional[int] = None
    visible_tests_total: Optional[int] = None
    hidden_tests_passed: Optional[int] = None
    hidden_tests_total: Optional[int] = None
    baseline_latency_ms: Optional[float] = None
    candidate_latency_ms: Optional[float] = None
    improvement_pct: Optional[float] = None
    reproduction_latency_ms: Optional[float] = None
    reproduction_improvement_pct: Optional[float] = None
    integrity_ok: Optional[bool] = None
    integrity_findings: Optional[dict[str, Any]] = None
    grok_investigation: Optional[dict[str, Any]] = None
    raw_results: Optional[dict[str, Any]] = None
    eval_vector: Optional[dict[str, Any]] = None
    event_log: Optional[list[Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SubmissionOut(BaseModel):
    id: UUID
    bounty_id: UUID
    source_type: str = "human"
    submitter_x_username: Optional[str] = None
    submitter_x_user_id: Optional[str] = None
    x_reply_id: Optional[str] = None
    x_reply_text: Optional[str] = None
    github_url: str
    commit_sha: Optional[str] = None
    deployment_url: Optional[str] = None
    generation_metadata: Optional[dict[str, Any]] = None
    status: str
    rank: Optional[int] = None
    is_winner: bool
    beats_grok: Optional[bool] = None
    vs_grok_delta: Optional[dict[str, Any]] = None
    evaluation: Optional[EvaluationOut] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BeatGrokVerdict(BaseModel):
    bounty_id: UUID
    champion: str  # grok | human username
    verdict: str  # VERIFIED_IMPROVEMENT_OVER_GROK | GROK_REMAINS_CHAMPION
    baseline_commit_sha: Optional[str] = None
    baseline_eval_vector: Optional[dict[str, Any]] = None
    challengers: list[dict[str, Any]] = Field(default_factory=list)


class SelectWinner(BaseModel):
    submission_id: UUID
    post_announcement: bool = True


class ProofOut(BaseModel):
    id: UUID
    bounty_id: UUID
    submission_id: UUID
    proof_json: dict[str, Any]
    public_url_path: str
    winner_card_path: Optional[str] = None
    x_announcement_post_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EventOut(BaseModel):
    id: UUID
    event_type: str
    source: str
    payload: Optional[dict[str, Any]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrationStatus(BaseModel):
    xai: dict[str, Any]
    x_oauth: dict[str, Any]
    x_webhooks: dict[str, Any]
    github: dict[str, Any]
    evaluator: dict[str, Any]
    x_money: dict[str, Any]
    reply_app_bot: dict[str, Any] = Field(default_factory=dict)
