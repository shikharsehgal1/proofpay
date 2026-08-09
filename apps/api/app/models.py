from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class BountyStatus(str, enum.Enum):
    DRAFT = "draft"
    CONTRACT_PENDING = "contract_pending"
    BASELINE_GENERATING = "baseline_generating"  # Grok Build in progress
    BASELINE_VALIDATING = "baseline_validating"
    READY = "ready"
    PUBLISHED = "published"
    EVALUATING = "evaluating"
    RANKED = "ranked"
    VERIFIED = "verified"
    READY_FOR_SETTLEMENT = "ready_for_settlement"
    SETTLED = "settled"
    CLOSED = "closed"
    FAILED = "failed"
    GROK_CHAMPION = "grok_champion"  # no human beat Grok


class BaselineType(str, enum.Enum):
    GROK_GENERATED = "grok_generated"
    USER_PROVIDED = "user_provided"
    NONE = "none"


class SubmissionSource(str, enum.Enum):
    GROK_BASELINE = "grok_baseline"
    HUMAN = "human"
    OTHER_AGENT = "other_agent"


class SubmissionStatus(str, enum.Enum):
    DETECTED = "detected"
    RESOLVING = "resolving"
    QUEUED = "queued"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    INELIGIBLE = "ineligible"
    ERROR = "error"



class EvalStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SettlementStatus(str, enum.Enum):
    NOT_APPLICABLE = "not_applicable"
    AWAITING_PAYMENT_RAIL = "awaiting_payment_rail"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    x_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    x_username: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    profile_image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    oauth: Mapped[Optional["OAuthToken"]] = relationship(back_populates="user", uselist=False)
    bounties: Mapped[list["Bounty"]] = relationship(back_populates="creator")


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(32), default="x")
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer")
    scope: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="oauth")


class Bounty(Base):
    __tablename__ = "bounties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    creator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    natural_language: Mapped[str] = mapped_column(Text)
    reward_amount: Mapped[float] = mapped_column(Float, default=0.0)
    reward_currency: Mapped[str] = mapped_column(String(16), default="USD")
    repository_url: Mapped[str] = mapped_column(String(512))
    baseline_ref: Mapped[str] = mapped_column(String(256), default="main")
    baseline_commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Seed repository (original target) — may differ from Grok baseline path
    seed_repository_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    mode: Mapped[str] = mapped_column(String(32), default="optimize")  # optimize | beat_grok | product
    baseline_type: Mapped[BaselineType] = mapped_column(
        Enum(BaselineType, name="baseline_type", values_callable=lambda x: [e.value for e in x]),
        default=BaselineType.NONE,
    )
    status: Mapped[BountyStatus] = mapped_column(
        Enum(BountyStatus, name="bounty_status", values_callable=lambda x: [e.value for e in x]),
        default=BountyStatus.DRAFT,
        index=True,
    )
    contract_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    product_spec_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    contract_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    baseline_metrics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Frozen Grok contestant
    baseline_submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    baseline_generation_run_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    baseline_deployment_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    baseline_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    baseline_prompt_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    baseline_generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    baseline_evaluation_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    baseline_eval_vector: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    champion_submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    x_post_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    x_post_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    winner_submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    settlement_status: Mapped[SettlementStatus] = mapped_column(
        Enum(SettlementStatus, name="settlement_status", values_callable=lambda x: [e.value for e in x]),
        default=SettlementStatus.AWAITING_PAYMENT_RAIL,
    )
    settlement_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    public_slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    creator: Mapped[User] = relationship(back_populates="bounties")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="bounty")
    events: Mapped[list["EventLog"]] = relationship(back_populates="bounty")
    proof: Mapped[Optional["ProofOfCompletion"]] = relationship(back_populates="bounty", uselist=False)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("bounty_id", "commit_sha", name="uq_bounty_commit"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[SubmissionSource] = mapped_column(
        Enum(SubmissionSource, name="submission_source", values_callable=lambda x: [e.value for e in x]),
        default=SubmissionSource.HUMAN,
        index=True,
    )
    submitter_x_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    submitter_x_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    x_reply_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)
    x_reply_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    github_url: Mapped[str] = mapped_column(String(512))
    github_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    github_repo: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    github_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    pr_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    deployment_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    generation_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status", values_callable=lambda x: [e.value for e in x]),
        default=SubmissionStatus.DETECTED,
        index=True,
    )
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    beats_grok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    vs_grok_delta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    bounty: Mapped[Bounty] = relationship(back_populates="submissions")
    evaluation: Mapped[Optional["Evaluation"]] = relationship(back_populates="submission", uselist=False)


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[EvalStatus] = mapped_column(
        Enum(EvalStatus, name="eval_status", values_callable=lambda x: [e.value for e in x]),
        default=EvalStatus.PENDING,
        index=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # All numeric results must come from real execution
    visible_tests_passed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    visible_tests_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hidden_tests_passed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hidden_tests_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    baseline_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    candidate_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    improvement_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reproduction_latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reproduction_improvement_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    integrity_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    integrity_findings: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    grok_investigation: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    raw_results: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Multi-dimensional evaluation vector (functionality, performance, …)
    eval_vector: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    event_log: Mapped[Optional[list[Any]]] = mapped_column(JSONB, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    submission: Mapped[Submission] = relationship(back_populates="evaluation")


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    bounty_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("bounties.id", ondelete="CASCADE"), nullable=True, index=True
    )
    submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64), default="system")
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bounty: Mapped[Optional[Bounty]] = relationship(back_populates="events")


class ProofOfCompletion(Base):
    __tablename__ = "proofs_of_completion"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    bounty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bounties.id", ondelete="CASCADE"), unique=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"))
    proof_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    public_url_path: Mapped[str] = mapped_column(String(256))
    winner_card_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    x_announcement_post_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bounty: Mapped[Bounty] = relationship(back_populates="proof")


class XWebhookEvent(Base):
    """Dedup store for inbound X Activity / webhook deliveries."""

    __tablename__ = "x_webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthState(Base):
    """Short-lived PKCE state for X OAuth."""

    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    state: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    code_verifier: Mapped[str] = mapped_column(String(256))
    redirect_after: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
