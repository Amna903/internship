"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Shell } from "@/components/Shell";
import { BrandMark } from "@/components/ui/BrandMark";
import { ApiError, userApi } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      await userApi.login(email, password);
      router.push("/profile");
    } catch (err) {
      setError(err instanceof ApiError
        ? err.code === "throttled" ? "Too many attempts. Please wait a minute and try again." : err.message
        : "Network error. Please try again.");
    } finally { setBusy(false); }
  }

  return (
    <Shell nav={<Link href="/signup">Create account</Link>}>
      <div className="auth">
      <form className="card" onSubmit={submit}>
        <div className="auth-head">
          <BrandMark />
          <h1>Sign in</h1>
          <p className="muted small">Welcome back. Manage your wellness profile.</p>
        </div>
        {error && <div className="alert error" role="alert">{error}</div>}
        <label htmlFor="email">Email</label>
        <input id="email" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <label htmlFor="password">Password</label>
        <input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        <button className="btn block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="small muted auth-foot">New here? <Link href="/signup">Create an account</Link></p>
      </form>
      <p className="small muted auth-foot">Administrator? <Link href="/admin/login">Use the admin sign-in</Link>.</p>
      </div>
    </Shell>
  );
}
