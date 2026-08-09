"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, Bounty, Submission } from "@/lib/api";

export default function BountyDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [bounty, setBounty] = useState<Bounty | null>(null);
  const [subs, setSubs] = useState<Submission[]>([]);
  const [events, setEvents] = useState<Array<{ event_type: string; source: string; created_at: string; payload?: unknown }>>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [manualUrl, setManualUrl] = useState("");
  const [manualUser, setManualUser] = useState("alice");
  const [verdict, setVerdict] = useState<{
    verdict: string;
    champion: string;
    baseline_eval_vector?: Record<string, unknown> | null;
    challengers?: Array<Record<string, unknown>>;
  } | null>(null);

  const reload = useCallback(async () => {
    const b = await api.getBounty(id);
    setBounty(b);
    setSubs(await api.submissions(id));
    setEvents(await api.events(id));
    try {
      setVerdict(await api.beatGrok(id));
    } catch {
      setVerdict(null);
    }
  }, [id]);

  useEffect(() => {
    reload().catch((e) => setError(String(e)));
    const t = setInterval(() => reload().catch(() => null), 5000);
    return () => clearInterval(t);
  }, [reload]);

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!bounty) {
    return <div className="card">{error || "Loading…"}</div>;
  }

  return (
    <div className="stack">
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="pill-list">
              <span className="badge info">{bounty.status}</span>
              <span className="badge warn">{bounty.settlement_status}</span>
            </div>
            <h1 style={{ marginTop: 12 }}>{bounty.title}</h1>
            <p className="muted">{bounty.natural_language}</p>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="metric">
              ${bounty.reward_amount}
              <span> {bounty.reward_currency}</span>
            </div>
            {bounty.x_post_url && (
              <a href={bounty.x_post_url} target="_blank" rel="noreferrer">
                Open X post
              </a>
            )}
          </div>
        </div>

        <div className="row" style={{ marginTop: 16 }}>
          <button
            className="btn"
            disabled={!!busy}
            onClick={() => act("compile", () => api.compile(id))}
          >
            Recompile with Grok
          </button>
          <button
            className="btn btn-primary"
            disabled={!!busy || bounty.contract_approved}
            onClick={() => act("approve", () => api.approve(id, true))}
          >
            Approve contract + seed validate
          </button>
          <button
            className="btn btn-primary"
            disabled={
              !!busy ||
              !bounty.contract_approved ||
              !!bounty.baseline_submission_id ||
              bounty.baseline_type === "none"
            }
            onClick={() => act("grok-baseline", () => api.generateGrokBaseline(id))}
          >
            Generate Grok Baseline V0
          </button>
          <button
            className="btn btn-success"
            disabled={
              !!busy ||
              !bounty.contract_approved ||
              (bounty.baseline_type === "grok_generated" && !bounty.baseline_submission_id)
            }
            onClick={() => act("publish", () => api.publish(id))}
          >
            Publish BEAT GROK to X
          </button>
          <button className="btn" disabled={!!busy} onClick={() => act("poll", () => api.pollX())}>
            Poll X replies (real API)
          </button>
        </div>

        {bounty.baseline_type === "grok_generated" && (
          <div className="card" style={{ marginTop: 16, background: "rgba(110,203,255,0.06)" }}>
            <h3>Grok is the baseline</h3>
            <p className="muted">
              Mode: <span className="badge info">{bounty.mode}</span>{" "}
              <span className="badge info">{bounty.baseline_type}</span>
            </p>
            {bounty.baseline_submission_id ? (
              <>
                <p>
                  Frozen commit:{" "}
                  <span className="mono">{bounty.baseline_commit_sha}</span>
                </p>
                <p className="muted">
                  Model: {bounty.baseline_model} · prompt {bounty.baseline_prompt_version} · run{" "}
                  {bounty.baseline_generation_run_id}
                </p>
                {bounty.baseline_eval_vector && (
                  <pre className="json">{JSON.stringify(bounty.baseline_eval_vector, null, 2)}</pre>
                )}
              </>
            ) : (
              <p className="muted">
                Approve the contract, then generate Grok Baseline V0. Grok is evaluated with the same
                pipeline as humans — no privileged scores.
              </p>
            )}
            {verdict && (
              <div style={{ marginTop: 12 }}>
                <span
                  className={`badge ${
                    verdict.verdict === "VERIFIED_IMPROVEMENT_OVER_GROK" ? "ok" : "warn"
                  }`}
                >
                  {verdict.verdict}
                </span>{" "}
                Champion: <strong>{verdict.champion}</strong>
              </div>
            )}
          </div>
        )}
        {error && <p className="badge bad" style={{ marginTop: 12 }}>{error}</p>}
        {bounty.settlement_note && (
          <p className="muted" style={{ marginTop: 12 }}>
            {bounty.settlement_note}
          </p>
        )}
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Executable contract</h2>
          {bounty.contract_json ? (
            <pre className="json">{JSON.stringify(bounty.contract_json, null, 2)}</pre>
          ) : (
            <p className="muted">Waiting for Grok compilation…</p>
          )}
        </div>
        <div className="card">
          <h2>Baseline metrics</h2>
          {bounty.baseline_metrics ? (
            <pre className="json">{JSON.stringify(bounty.baseline_metrics, null, 2)}</pre>
          ) : (
            <p className="muted">Approve contract to run real baseline evaluation.</p>
          )}
          <h3 style={{ marginTop: 18 }}>Event log</h3>
          <div className="timeline">
            {events.map((e, i) => (
              <div className="timeline-item" key={i}>
                <div className="mono">
                  {e.event_type} · {e.source}
                </div>
                <div className="muted">{new Date(e.created_at).toLocaleString()}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Submissions</h2>
        <p className="muted">
          Live path: X replies with GitHub URLs. Demo path: submit local variant folders through the
          same evaluation pipeline (no hardcoded winners).
        </p>
        <div className="row">
          <input
            style={{ flex: 1, marginBottom: 0 }}
            placeholder="GitHub URL or local path e.g. .../demo-bounty/variants/alice"
            value={manualUrl}
            onChange={(e) => setManualUrl(e.target.value)}
          />
          <input
            style={{ width: 140, marginBottom: 0 }}
            placeholder="x username"
            value={manualUser}
            onChange={(e) => setManualUser(e.target.value)}
          />
          <button
            className="btn btn-primary"
            disabled={!!busy || !manualUrl}
            onClick={() =>
              act("submit", async () => {
                const s = await api.addSubmission(id, {
                  github_url: manualUrl,
                  submitter_x_username: manualUser,
                  x_reply_text: `Submission: ${manualUrl}`,
                });
                await api.evaluate(id, s.id);
              })
            }
          >
            Ingest + evaluate
          </button>
        </div>

        <table className="table" style={{ marginTop: 18 }}>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Contestant</th>
              <th>Status</th>
              <th>vs Grok</th>
              <th>Latency / Δ seed</th>
              <th>Tests</th>
              <th>Integrity</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => {
              const ev = s.evaluation;
              return (
                <tr key={s.id}>
                  <td>{s.rank ?? "—"}</td>
                  <td>
                    @{s.submitter_x_username || "unknown"}
                    <div className="mono muted">{s.commit_sha?.slice(0, 10)}</div>
                    <span className="badge info">{s.source_type || "human"}</span>
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        s.status === "completed"
                          ? "ok"
                          : s.status === "ineligible"
                            ? "bad"
                            : "info"
                      }`}
                    >
                      {s.status}
                    </span>
                    {s.is_winner && <span className="badge ok">winner</span>}
                  </td>
                  <td>
                    {s.source_type === "grok_baseline" ? (
                      <span className="badge warn">BASELINE</span>
                    ) : s.beats_grok === true ? (
                      <span className="badge ok">BEATS GROK</span>
                    ) : s.beats_grok === false ? (
                      <span className="badge bad">LOSES</span>
                    ) : (
                      "—"
                    )}
                    {s.vs_grok_delta && (
                      <div className="muted" style={{ maxWidth: 180, fontSize: 12 }}>
                        {(s.vs_grok_delta as { reason?: string }).reason}
                      </div>
                    )}
                  </td>
                  <td>
                    {ev?.candidate_latency_ms != null
                      ? `${ev.candidate_latency_ms.toFixed(3)} ms`
                      : "—"}
                    {ev?.improvement_pct != null && (
                      <div className="muted">vs seed {ev.improvement_pct.toFixed(1)}%</div>
                    )}
                  </td>
                  <td className="mono">
                    vis {ev?.visible_tests_passed ?? "?"}/{ev?.visible_tests_total ?? "?"}
                    <br />
                    hid {ev?.hidden_tests_passed ?? "?"}/{ev?.hidden_tests_total ?? "?"}
                  </td>
                  <td>
                    {ev?.integrity_ok == null ? (
                      "—"
                    ) : ev.integrity_ok ? (
                      <span className="badge ok">ok</span>
                    ) : (
                      <span className="badge bad">flagged</span>
                    )}
                  </td>
                  <td>
                    <div className="row">
                      <button
                        className="btn"
                        disabled={!!busy}
                        onClick={() => act("eval", () => api.evaluate(id, s.id))}
                      >
                        Re-run
                      </button>
                      <button
                        className="btn btn-success"
                        disabled={!!busy || s.status !== "completed"}
                        onClick={() => act("winner", () => api.selectWinner(id, s.id))}
                      >
                        Select winner
                      </button>
                    </div>
                    {ev?.error_message && (
                      <div className="muted" style={{ maxWidth: 220 }}>
                        {ev.error_message}
                      </div>
                    )}
                    {ev?.grok_investigation && (
                      <details>
                        <summary>Grok investigation</summary>
                        <pre className="json">
                          {JSON.stringify(ev.grok_investigation, null, 2)}
                        </pre>
                      </details>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
