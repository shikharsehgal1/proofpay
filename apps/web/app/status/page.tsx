"use client";

import { useEffect, useState } from "react";
import { api, IntegrationStatus } from "@/lib/api";

export default function StatusPage() {
  const [data, setData] = useState<IntegrationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .integrations()
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return <div className="card badge bad">{error}</div>;
  if (!data) return <div className="card">Loading integration status…</div>;

  return (
    <div className="stack">
      <div className="card">
        <h1>Integration status</h1>
        <p className="muted">
          ProofPay refuses silent fallbacks. If something is missing, it is listed here with the
          exact credential or setup required.
        </p>
      </div>
      {Object.entries(data).map(([key, value]) => (
        <div className="card" key={key}>
          <h2>{key}</h2>
          <pre className="json">{JSON.stringify(value, null, 2)}</pre>
        </div>
      ))}
    </div>
  );
}
