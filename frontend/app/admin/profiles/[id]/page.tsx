"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { adminApi, AdminProfileDetail, ApiError } from "@/lib/api";

const dash = (v: string | null | undefined) => (v ? v : "—");
const list = (v: string[]) => (v.length ? v.join(", ") : "—");
const when = (v: string | null) => (v ? new Date(v).toLocaleString() : "—");

export default function AdminProfileDetailPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [p, setP] = useState<AdminProfileDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi.detail(id).then(setP).catch((err) => {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) router.replace("/admin/login");
      else setError(err instanceof ApiError && err.status === 404 ? "Profile not found." : "Could not load profile.");
    });
  }, [id, router]);

  async function toggle() {
    if (!p) return;
    const action = p.status === "active" ? "deactivate" : "activate";
    if (action === "deactivate" && !confirm(`Deactivate ${p.full_name}? They will be signed out and unable to sign in.`)) return;
    setBusy(true); setError("");
    try { setP(await adminApi.setStatus(id, action)); }
    catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/admin/login");
      else setError(err instanceof ApiError ? err.message : "Network error.");
    } finally { setBusy(false); }
  }

  const back = <Link href="/admin">← All profiles</Link>;
  if (!p) return <Shell nav={back}>{error ? <div className="alert error">{error}</div> : <p className="muted">Loading…</p>}</Shell>;

  return (
    <Shell nav={back}>
      <h1>{p.full_name}</h1>
      <p className="muted small">{p.email} · <span className={`badge ${p.status === "active" ? "" : "off"}`}>{p.status}</span></p>
      {error && <div className="alert error" role="alert">{error}</div>}

      <div className="card">
        <h2>Profile</h2>
        <dl className="kv">
          <dt>Date of birth</dt><dd>{dash(p.date_of_birth)}</dd>
          <dt>Age range</dt><dd>{dash(p.age_range)}</dd>
          <dt>Contact preference</dt><dd>{p.contact_preference}</dd>
          <dt>Wellness goals</dt><dd>{list(p.wellness_goals)}</dd>
          <dt>Allergies</dt><dd>{list(p.allergies)}</dd>
          <dt>Lifestyle notes</dt><dd>{dash(p.lifestyle_notes)}</dd>
        </dl>
      </div>
      <div className="card">
        <h2>Emergency contact (fictional)</h2>
        <dl className="kv">
          <dt>Name</dt><dd>{dash(p.emergency_contact_name)}</dd>
          <dt>Relationship</dt><dd>{dash(p.emergency_contact_relationship)}</dd>
          <dt>Phone</dt><dd>{dash(p.emergency_contact_phone)}</dd>
        </dl>
      </div>
      <div className="card">
        <h2>Account</h2>
        <dl className="kv">
          <dt>Created</dt><dd>{when(p.created_at)}</dd>
          <dt>Last updated</dt><dd>{when(p.updated_at)}</dd>
          <dt>Last sign-in</dt><dd>{when(p.last_login)}</dd>
          <dt>Deactivated at</dt><dd>{when(p.deactivated_at)}</dd>
        </dl>
        <p>
          <button className={`btn small ${p.status === "active" ? "danger" : ""}`} onClick={toggle} disabled={busy}>
            {p.status === "active" ? "Deactivate profile" : "Reactivate profile"}
          </button>
        </p>
      </div>
    </Shell>
  );
}
