"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, Bounty } from "@/lib/api";

export default function HomePage() {
  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [integrations, setIntegrations] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    api.listBounties().then(setBounties).catch(() => setBounties([]));
    api.integrations().then((i) => setIntegrations(i as unknown as Record<string, unknown>)).catch(() => null);
  }, []);

  return (
    <div className="stack">
      <section className="hero">
        <div className="card">
          <div className="pill-list" style={{ marginBottom: 14 }}>
            <span className="badge info">Grok is the baseline</span>
            <span className="badge info">Real evaluation</span>
            <span className="badge info">Beat Grok</span>
            <span className="badge warn">No fake settlement</span>
          </div>
          <h1>Get Grok to build it. Pay humans only if they can beat it.</h1>
          <p className="muted">
            ProofPay is AI escrow for verifiable work. Grok produces Baseline V0 first — a real
            repository, frozen commit, same evaluator as every human challenger. Humans win only with
            verified improvement over Grok.
          </p>
          <div className="row" style={{ marginTop: 18 }}>
            <Link className="btn btn-primary" href="/dashboard">
              Create a bounty
            </Link>
            <Link className="btn" href="/status">
              Integration status
            </Link>
          </div>
          <div className="footer-note">
            X Money has no public developer API for this project. Verified winners stop at{" "}
            <strong>READY FOR SETTLEMENT</strong> until a legitimate payment rail exists.
          </div>
        </div>
        <div className="card">
          <h3>Live pipeline</h3>
          <div className="timeline">
            {[
              "Sign in with X (OAuth 2.0 PKCE)",
              "Grok compiles executable contract",
              "Baseline validated on real repo commit",
              "Bounty post published via X API",
              "Replies → GitHub SHA resolution",
              "Sandboxed tests + hidden tests + bench",
              "Grok tool-loop investigation",
              "Proof of Completion + winner card",
            ].map((step) => (
              <div className="timeline-item" key={step}>
                <div>{step}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Open bounties</h2>
        {bounties.length === 0 ? (
          <p className="muted">No bounties yet. Create one after signing in with X.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Reward</th>
                <th>Status</th>
                <th>X</th>
              </tr>
            </thead>
            <tbody>
              {bounties.map((b) => (
                <tr key={b.id}>
                  <td>
                    <Link href={`/b/${b.public_slug}`}>{b.title}</Link>
                  </td>
                  <td>
                    ${b.reward_amount} {b.reward_currency}
                  </td>
                  <td>
                    <span className="badge info">{b.status}</span>
                  </td>
                  <td>
                    {b.x_post_url ? (
                      <a href={b.x_post_url} target="_blank" rel="noreferrer">
                        View post
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {integrations && (
        <section className="card">
          <h3>Platform boundaries (honest)</h3>
          <pre className="json">{JSON.stringify(integrations, null, 2)}</pre>
        </section>
      )}
    </div>
  );
}
