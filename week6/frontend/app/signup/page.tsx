"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { FieldError, Shell } from "@/components/Shell";
import { BrandMark } from "@/components/ui/BrandMark";
import { ApiError, userApi } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErrors({});
    setMessage("");
    try {
      await userApi.signup(form.name, form.email, form.password);
      await userApi.login(form.email, form.password); // go straight into the app
      router.push("/profile");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors);
        if (!Object.keys(err.details).length) setMessage(err.message);
      } else setMessage("Network error. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell nav={<Link href="/login">Sign in</Link>}>
      <div className="auth">
        <form className="card" onSubmit={submit} noValidate>
          <div className="auth-head">
            <BrandMark />
            <h1>Create account</h1>
            <p className="muted small">Use a fictional name and email for this demo.</p>
          </div>
          {message && (
            <div className="alert error" role="alert">
              {message}
            </div>
          )}

          <label htmlFor="name">Full name</label>
          <input id="name" autoComplete="name" value={form.name} onChange={set("name")} required />
          <FieldError errors={errors} name="name" />

          <label htmlFor="email">Email</label>
          <input id="email" type="email" autoComplete="email" value={form.email} onChange={set("email")} required />
          <FieldError errors={errors} name="email" />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={set("password")}
            required
          />
          <div className="hint">At least 10 characters; not a common or all-numeric password.</div>
          <FieldError errors={errors} name="password" />

          <button className="btn block" disabled={busy}>
            {busy ? "Creating…" : "Create account"}
          </button>
          <p className="small muted auth-foot">
            Already have an account? <Link href="/login">Sign in</Link>
          </p>
        </form>
      </div>
    </Shell>
  );
}
