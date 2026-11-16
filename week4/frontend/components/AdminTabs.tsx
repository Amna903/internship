"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminApi } from "@/lib/api";

const TABS = [
  { href: "/admin/predictions", label: "Predictions" },
  { href: "/admin/clusters", label: "Clusters" },
  { href: "/admin/assistant", label: "Assistant" },
];

/** The three Week 4 ML tabs. Each tab is its own route, so it can be linked and reloaded. */
export function AdminTabs() {
  const path = usePathname();
  return (
    <nav className="admin-tabs" aria-label="Machine learning tools">
      {TABS.map((t) => (
        <Link key={t.href} href={t.href} className={path === t.href ? "active" : ""}
              aria-current={path === t.href ? "page" : undefined}>{t.label}</Link>
      ))}
    </nav>
  );
}

/** Header links shared by the ML tabs. The redirect is convenience; the API enforces admin access. */
export function useAdminNav() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  useEffect(() => {
    adminApi.me().then((r) => setEmail(r.user.email)).catch(() => router.replace("/admin/login"));
  }, [router]);

  async function logout() {
    try { await adminApi.logout(); } finally { router.push("/admin/login"); }
  }

  return (
    <>
      <Link className="btn ghost small" href="/admin">Member profiles</Link>
      <span className="muted small">{email}</span>
      <button className="btn ghost small" onClick={logout}>Sign out</button>
    </>
  );
}
