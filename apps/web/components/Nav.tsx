"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, User } from "@/lib/api";

export function Nav() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  async function login() {
    const { authorize_url } = await api.startXAuth("/dashboard");
    window.location.href = authorize_url;
  }

  async function logout() {
    await api.logout();
    setUser(null);
    window.location.href = "/";
  }

  return (
    <header className="nav">
      <Link href="/" className="brand">
        <span className="logo-mark" />
        Proof<span>Pay</span>
      </Link>
      <div className="nav-actions">
        <Link href="/dashboard">Dashboard</Link>
        <Link href="/status">Integrations</Link>
        {user ? (
          <>
            <span className="badge info">@{user.x_username}</span>
            <button className="btn" onClick={logout}>
              Sign out
            </button>
          </>
        ) : (
          <button className="btn btn-primary" onClick={login}>
            Sign in with X
          </button>
        )}
      </div>
    </header>
  );
}
