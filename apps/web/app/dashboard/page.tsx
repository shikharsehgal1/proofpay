"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Bounty, User } from "@/lib/api";

const DEFAULT_NL = `Implement a high-quality production search ranker in searchlab.ranker.rank(query, documents) -> list[doc_ids]. Maximize composite_score = 100*(0.7*NDCG@10 + 0.3*MRR) - 5.0*log10(1 + p95_latency_ms). Corpus has title/body/tags. Hidden holdout queries test generalization. No hardcoding, no env detection. Beat Grok's frozen baseline on the same sandbox pipeline.`;

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [title, setTitle] = useState("Beat Grok: Complex Multi-Metric Search Ranking");
  const [nl, setNl] = useState(DEFAULT_NL);
  const [repo, setRepo] = useState("");
  const [reward, setReward] = useState(100);
  const [baseline, setBaseline] = useState("main");
  const [mode, setMode] = useState<"beat_grok" | "optimize">("beat_grok");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mine, setMine] = useState<Bounty[]>([]);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null));
    api.listBounties().then(setMine).catch(() => setMine([]));
    setRepo(detectDemoRepo());
  }, []);

  function detectDemoRepo() {
    // Prefer SearchLab multi-metric seed; Fly image path falls back via API DEMO_SEARCH_PATH
    return (
      process.env.NEXT_PUBLIC_DEMO_REPO ||
      "/Users/shikharsehgal/grokathon/demo-search"
    );
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      if (!user) {
        const { authorize_url } = await api.startXAuth("/dashboard");
        window.location.href = authorize_url;
        return;
      }
      const b = await api.createBounty({
        title,
        natural_language: nl,
        repository_url: repo,
        baseline_ref: baseline,
        reward_amount: reward,
        reward_currency: "USD",
        mode,
      });
      router.push(`/bounty/${b.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Create bounty</h1>
        <p className="muted">
          Grok will compile your natural language into an executable evaluation contract. Nothing is
          published to X until you approve and click Publish.
        </p>
        {!user && (
          <p className="badge warn">Sign in with X required to create and publish bounties.</p>
        )}
        <label>Title</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
        <label>Natural language brief</label>
        <textarea value={nl} onChange={(e) => setNl(e.target.value)} />
        <div className="grid-2">
          <div>
            <label>Repository URL or local path</label>
            <input value={repo} onChange={(e) => setRepo(e.target.value)} />
          </div>
          <div>
            <label>Baseline ref</label>
            <input value={baseline} onChange={(e) => setBaseline(e.target.value)} />
          </div>
        </div>
        <label>Reward (USD)</label>
        <input
          type="number"
          value={reward}
          onChange={(e) => setReward(Number(e.target.value))}
          min={0}
        />
        <label>Mode</label>
        <select value={mode} onChange={(e) => setMode(e.target.value as "beat_grok" | "optimize")}>
          <option value="beat_grok">Beat Grok — Grok builds baseline first</option>
          <option value="optimize">Classic optimize (user-provided baseline)</option>
        </select>
        <p className="muted">
          Thesis: <strong>Get Grok to build it. Pay humans only if they can beat it.</strong>
        </p>
        {error && <p className="badge bad">{error}</p>}
        <button className="btn btn-primary" disabled={busy} onClick={create}>
          {busy ? "Working…" : "Compile contract with Grok"}
        </button>
      </div>

      <div className="card">
        <h2>Your pipeline</h2>
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Slug</th>
            </tr>
          </thead>
          <tbody>
            {mine.map((b) => (
              <tr key={b.id}>
                <td>
                  <a href={`/bounty/${b.id}`}>{b.title}</a>
                </td>
                <td>
                  <span className="badge info">{b.status}</span>
                </td>
                <td className="mono">{b.public_slug}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
