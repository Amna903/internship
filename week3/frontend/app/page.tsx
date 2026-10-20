import Link from "next/link";
import { Shell } from "@/components/Shell";

export default function Home() {
  return (
    <Shell>
      <section className="hero">
        <h1>Your wellness profile, in one place.</h1>
        <p className="muted">
          Set your wellness goals, contact preferences and an emergency contact. Two separate sign-in
          paths: members use short-lived tokens, administrators use server-side sessions.
        </p>
      </section>
      <div className="card">
        <h2>Find a wellness professional</h2>
        <p className="muted small">Search fictional nutritionists, physiotherapists, coaches and more by specialty, city, day and fee.</p>
        <p><Link className="btn" href="/professionals">Browse professionals</Link></p>
      </div>
      <div className="choices">
        <div className="card">
          <h2>Member</h2>
          <p className="muted small">Create an account and manage your own profile.</p>
          <p style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link className="btn" href="/signup">Create account</Link>
            <Link className="btn ghost" href="/login">Sign in</Link>
          </p>
        </div>
        <div className="card">
          <h2>Administrator</h2>
          <p className="muted small">Accounts are provisioned by the team. No self-registration.</p>
          <p><Link className="btn ghost" href="/admin/login">Admin sign in</Link></p>
        </div>
      </div>
    </Shell>
  );
}
