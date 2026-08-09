"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Bounty, Submission } from "@/lib/api";

function metric(sub: Submission, key: string): string {
  const cm = (sub.evaluation?.raw_results as { candidate_metrics?: Record<string, number> } | undefined)
    ?.candidate_metrics;
  const v = cm?.[key];
  if (v == null) return "—";
  if (key === "p95_ms") return Number(v).toFixed(3);
  if (typeof v === "number" && v < 2) return v.toFixed(4);
  return Number(v).toFixed(2);
}

export default function PublicBountyPage() {
  const { slug } = useParams<{ slug: string }>();
  const [bounty, setBounty] = useState<Bounty | null>(null);
  const [subs, setSubs] = useState<Submission[]>([]);

  useEffect(() => {
    api.getBySlug(slug).then(async (b) => {
      setBounty(b);
      setSubs(await api.submissions(b.id));
    });
  }, [slug]);

  if (!bounty) return <div className="card">Loading…</div>;

  const bench = (bounty.contract_json?.benchmark as Record<string, unknown> | undefined) || {};
  const formula =
    (bench.formula as string) ||
    "100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1+p95_ms)";
  const sorted = [...subs].sort((a, b) => {
    if (a.rank != null && b.rank != null) return a.rank - b.rank;
    if (a.rank != null) return -1;
    if (b.rank != null) return 1;
    return 0;
  });

  return (
    <div className="stack">
      <div className="card">
        <span className="badge info">{bounty.status}</span>
        {bounty.baseline_type === "grok_generated" && (
          <span className="badge warn" style={{ marginLeft: 8 }}>
            Beat Grok
          </span>
        )}
        <h1>{bounty.title}</h1>
        <p className="muted">{bounty.natural_language}</p>
        <div className="metric">
          ${bounty.reward_amount}
          <span> {bounty.reward_currency}</span>
        </div>
        {bounty.x_post_url && (
          <p>
            <a href={bounty.x_post_url} target="_blank" rel="noreferrer">
              Discuss / submit on X
            </a>
          </p>
        )}
        <p className="muted">
          Settlement: {bounty.settlement_status}. {bounty.settlement_note}
        </p>
      </div>

      <div className="card">
        <h2>Scoring metric</h2>
        <pre className="json" style={{ whiteSpace: "pre-wrap" }}>
          {`composite_score (higher is better) =\n  ${formula}\n\nReported: NDCG@10 · MRR · p95 latency · composite`}
        </pre>
        <p className="muted">
          Hard gates: visible tests, hidden ranking quality (holdout queries), integrity scan,
          clean-sandbox reproduction. Challengers must beat frozen Grok Baseline V0 on the same
          pipeline.
        </p>
      </div>

      <div className="card">
        <h2>Leaderboard</h2>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Submitter</th>
              <th>Composite</th>
              <th>NDCG@10</th>
              <th>MRR</th>
              <th>p95 ms</th>
              <th>vs Grok</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => (
              <tr key={s.id}>
                <td>{s.rank ?? "—"}</td>
                <td>
                  @{s.submitter_x_username || "?"}
                  {s.source_type === "grok_baseline" ? " (Grok V0)" : ""}
                </td>
                <td className="mono">{metric(s, "composite_score")}</td>
                <td className="mono">{metric(s, "ndcg_at_10")}</td>
                <td className="mono">{metric(s, "mrr")}</td>
                <td className="mono">{metric(s, "p95_ms")}</td>
                <td>
                  {s.beats_grok === true
                    ? "✓ beats"
                    : s.beats_grok === false
                      ? "no"
                      : s.source_type === "grok_baseline"
                        ? "champion ref"
                        : "—"}
                </td>
                <td>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Executable contract</h2>
        <pre className="json">{JSON.stringify(bounty.contract_json, null, 2)}</pre>
      </div>
    </div>
  );
}
