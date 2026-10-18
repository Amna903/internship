"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Shell } from "@/components/Shell";
import { adminApi, ApiError } from "@/lib/api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await adminApi.login(email, password);
      router.push("/admin");
    } catch (err) {
      setError(err instanceof ApiError
        ? err.code === "throttled" ? "Too many attempts. Please wait a minute and try again." : err.message
        : "Network error. Please try again.");
    } finally { setBusy(false); }
  }

  return (
    <Shell nav={<Link href="/login">Member sign in</Link>}>
      <form className="card narrow" onSubmit={submit}>
        <h1>Admin sign in</h1>
        <p className="muted small">Server-side session. Nothing about your role is stored in the browser.</p>
        {error && <div className="alert error" role="alert">{error}</div>}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button className="btn block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </Shell>
  );
}
