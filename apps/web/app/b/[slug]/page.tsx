"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, Bounty, Submission } from "@/lib/api";

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

  return (
    <div className="stack">
      <div className="card">
        <span className="badge info">{bounty.status}</span>
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
        <h2>Contract</h2>
        <pre className="json">{JSON.stringify(bounty.contract_json, null, 2)}</pre>
      </div>
      <div className="card">
        <h2>Leaderboard</h2>
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>Submitter</th>
              <th>Δ</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => (
              <tr key={s.id}>
                <td>{s.rank ?? "—"}</td>
                <td>@{s.submitter_x_username || "?"}</td>
                <td>
                  {s.evaluation?.improvement_pct != null
                    ? `${s.evaluation.improvement_pct.toFixed(1)}%`
                    : "—"}
                </td>
                <td>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
