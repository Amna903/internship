"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/Shell";
import { adminApi, AdminProfileRow, ApiError, Page } from "@/lib/api";

export default function AdminDashboard() {
  const router = useRouter();
  const [adminEmail, setAdminEmail] = useState("");
  const [data, setData] = useState<Page<AdminProfileRow> | null>(null);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [ordering, setOrdering] = useState("-created_at");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");

  // The server decides who is an admin. If this call fails, we are not one, whatever the UI says.
  useEffect(() => {
    adminApi.me().then((r) => setAdminEmail(r.user.email)).catch(() => router.replace("/admin/login"));
  }, [router]);

  const load = useCallback(async () => {
    setError("");
    try {
      const params: Record<string, string> = { page: String(page), ordering };
      if (query) params.search = query;
      if (status) params.status = status;
      setData(await adminApi.list(params));
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) router.replace("/admin/login");
      else if (err instanceof ApiError && err.status === 404 && page > 1) setPage(1); // page past the end after filtering
      else setError("Could not load profiles.");
    }
  }, [page, query, status, ordering, router]);

  useEffect(() => { load(); }, [load]);

  // Debounce the search box so we do not fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => { setPage(1); setQuery(search.trim()); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  async function logout() {
    try { await adminApi.logout(); } finally { router.push("/admin/login"); }
  }

  const pages = data ? Math.max(1, Math.ceil(data.count / 10)) : 1;
  const nav = (<><span className="muted small">{adminEmail}</span><button className="btn ghost small" onClick={logout}>Sign out</button></>);

  return (
    <Shell nav={nav}>
      <h1>Member profiles</h1>
      <p className="muted small">{data ? `${data.count} profile${data.count === 1 ? "" : "s"}` : "Loading…"}</p>

      <div className="card">
        <div className="toolbar">
          <input aria-label="Search name or email" placeholder="Search name or email…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <select aria-label="Status" value={status} onChange={(e) => { setPage(1); setStatus(e.target.value); }}>
            <option value="">All statuses</option><option value="active">Active</option><option value="deactivated">Deactivated</option>
          </select>
          <select aria-label="Sort" value={ordering} onChange={(e) => { setPage(1); setOrdering(e.target.value); }}>
            <option value="-created_at">Newest first</option><option value="created_at">Oldest first</option>
            <option value="full_name">Name A–Z</option><option value="-full_name">Name Z–A</option>
          </select>
        </div>

        {error && <div className="alert error" role="alert">{error}</div>}

        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Age</th><th>Contact</th><th>Status</th><th>Joined</th><th /></tr></thead>
            <tbody>
              {data?.results.map((p) => (
                <tr key={p.id}>
                  <td>{p.full_name}</td>
                  <td>{p.email}</td>
                  <td>{p.age_range || "—"}</td>
                  <td>{p.contact_preference}</td>
                  <td><span className={`badge ${p.status === "active" ? "" : "off"}`}>{p.status}</span></td>
                  <td>{new Date(p.created_at).toLocaleDateString()}</td>
                  <td><Link href={`/admin/profiles/${p.id}`}>View</Link></td>
                </tr>
              ))}
              {data && data.results.length === 0 && <tr><td colSpan={7} className="muted">No profiles match.</td></tr>}
            </tbody>
          </table>
        </div>

        <div className="pager">
          <button className="btn ghost small" disabled={!data?.previous} onClick={() => setPage(page - 1)}>← Previous</button>
          <span className="muted small">Page {page} of {pages}</span>
          <button className="btn ghost small" disabled={!data?.next} onClick={() => setPage(page + 1)}>Next →</button>
        </div>
      </div>
    </Shell>
  );
}
