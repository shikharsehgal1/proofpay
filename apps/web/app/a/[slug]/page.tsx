"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

/**
 * Public shell for Grok Reply App mini-apps.
 * Loads metadata then embeds the generated HTML in a full-viewport iframe
 * (srcdoc) so the mini-app is isolated from the ProofPay chrome.
 */
export default function ReplyAppPage() {
  const { slug } = useParams<{ slug: string }>();
  const [title, setTitle] = useState("Loading app…");
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const metaRes = await fetch(`/api/reply-app/apps/${slug}`, { cache: "no-store" });
        if (!metaRes.ok) throw new Error("App not found");
        const meta = await metaRes.json();
        if (cancelled) return;
        setTitle(meta.title || "Mini app");
        document.title = meta.title || "Grok Reply App";

        const htmlRes = await fetch(`/api/reply-app/apps/${slug}/html`, { cache: "no-store" });
        if (!htmlRes.ok) throw new Error("Failed to load app HTML");
        const body = await htmlRes.text();
        if (!cancelled) setHtml(body);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [slug]);

  if (error) {
    return (
      <div style={{ padding: 24, fontFamily: "system-ui", color: "#e8eef7", background: "#0b0f14", minHeight: "100vh" }}>
        <h1>App unavailable</h1>
        <p style={{ opacity: 0.7 }}>{error}</p>
      </div>
    );
  }

  if (!html) {
    return (
      <div style={{ padding: 24, fontFamily: "system-ui", color: "#e8eef7", background: "#0b0f14", minHeight: "100vh" }}>
        {title}
      </div>
    );
  }

  return (
    <iframe
      title={title}
      srcDoc={html}
      sandbox="allow-scripts allow-forms allow-modals allow-same-origin"
      style={{
        position: "fixed",
        inset: 0,
        width: "100%",
        height: "100%",
        border: 0,
        background: "#0b0f14",
      }}
    />
  );
}
