const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

export type IntegrationStatus = {
  xai: Record<string, unknown>;
  x_oauth: Record<string, unknown>;
  x_webhooks: Record<string, unknown>;
  github: Record<string, unknown>;
  evaluator: Record<string, unknown>;
  x_money: Record<string, unknown>;
};

export type User = {
  id: string;
  x_user_id: string;
  x_username: string;
  display_name?: string | null;
  profile_image_url?: string | null;
};

export type Bounty = {
  id: string;
  title: string;
  natural_language: string;
  reward_amount: number;
  reward_currency: string;
  repository_url: string;
  baseline_ref: string;
  baseline_commit_sha?: string | null;
  seed_repository_url?: string | null;
  mode?: string;
  baseline_type?: string;
  status: string;
  contract_json?: Record<string, unknown> | null;
  product_spec_json?: Record<string, unknown> | null;
  contract_approved: boolean;
  baseline_metrics?: Record<string, unknown> | null;
  baseline_submission_id?: string | null;
  baseline_generation_run_id?: string | null;
  baseline_deployment_url?: string | null;
  baseline_model?: string | null;
  baseline_prompt_version?: string | null;
  baseline_generated_at?: string | null;
  baseline_evaluation_id?: string | null;
  baseline_eval_vector?: Record<string, unknown> | null;
  champion_submission_id?: string | null;
  x_post_id?: string | null;
  x_post_url?: string | null;
  public_slug: string;
  settlement_status: string;
  settlement_note?: string | null;
  winner_submission_id?: string | null;
  created_at: string;
  published_at?: string | null;
  creator?: User | null;
};

export type Evaluation = {
  id: string;
  status: string;
  visible_tests_passed?: number | null;
  visible_tests_total?: number | null;
  hidden_tests_passed?: number | null;
  hidden_tests_total?: number | null;
  baseline_latency_ms?: number | null;
  candidate_latency_ms?: number | null;
  improvement_pct?: number | null;
  reproduction_latency_ms?: number | null;
  reproduction_improvement_pct?: number | null;
  integrity_ok?: boolean | null;
  integrity_findings?: Record<string, unknown> | null;
  grok_investigation?: Record<string, unknown> | null;
  raw_results?: Record<string, unknown> | null;
  event_log?: unknown[] | null;
  error_message?: string | null;
};

export type Submission = {
  id: string;
  bounty_id: string;
  source_type?: string;
  submitter_x_username?: string | null;
  github_url: string;
  commit_sha?: string | null;
  status: string;
  rank?: number | null;
  is_winner: boolean;
  beats_grok?: boolean | null;
  vs_grok_delta?: Record<string, unknown> | null;
  evaluation?: Evaluation | null;
  created_at: string;
  x_reply_text?: string | null;
  generation_metadata?: Record<string, unknown> | null;
};

export type BeatGrokVerdict = {
  bounty_id: string;
  champion: string;
  verdict: string;
  baseline_commit_sha?: string | null;
  baseline_eval_vector?: Record<string, unknown> | null;
  challengers: Array<Record<string, unknown>>;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string; integrations: Record<string, boolean> }>("/api/health"),
  integrations: () => req<IntegrationStatus>("/api/integrations"),
  me: () => req<User>("/api/auth/me"),
  startXAuth: (redirect = "/") =>
    req<{ authorize_url: string }>(`/api/auth/x/start?redirect=${encodeURIComponent(redirect)}`),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  listBounties: () => req<Bounty[]>("/api/bounties"),
  getBounty: (id: string) => req<Bounty>(`/api/bounties/${id}`),
  getBySlug: (slug: string) => req<Bounty>(`/api/bounties/slug/${slug}`),
  createBounty: (
    body: Partial<Bounty> & {
      natural_language: string;
      title: string;
      repository_url: string;
      mode?: string;
    }
  ) => req<Bounty>("/api/bounties", { method: "POST", body: JSON.stringify(body) }),
  compile: (id: string) => req<Bounty>(`/api/bounties/${id}/compile`, { method: "POST" }),
  approve: (id: string, approved = true) =>
    req<Bounty>(`/api/bounties/${id}/approve-contract`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  generateGrokBaseline: (id: string) =>
    req<Bounty>(`/api/bounties/${id}/generate-grok-baseline`, { method: "POST" }),
  beatGrok: (id: string) => req<BeatGrokVerdict>(`/api/bounties/${id}/beat-grok`),
  publish: (id: string) => req<Bounty>(`/api/bounties/${id}/publish`, { method: "POST" }),
  submissions: (id: string) => req<Submission[]>(`/api/bounties/${id}/submissions`),
  addSubmission: (
    id: string,
    body: { github_url: string; submitter_x_username?: string; x_reply_text?: string }
  ) =>
    req<Submission>(`/api/bounties/${id}/submissions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  evaluate: (bountyId: string, submissionId: string) =>
    req<Submission>(`/api/bounties/${bountyId}/submissions/${submissionId}/evaluate`, {
      method: "POST",
    }),
  selectWinner: (bountyId: string, submissionId: string) =>
    req(`/api/bounties/${bountyId}/select-winner`, {
      method: "POST",
      body: JSON.stringify({ submission_id: submissionId, post_announcement: true }),
    }),
  events: (id: string) => req<Array<{ event_type: string; source: string; payload?: unknown; created_at: string }>>(`/api/bounties/${id}/events`),
  pollX: () => req("/api/webhooks/x/poll-conversations", { method: "POST" }),
};
