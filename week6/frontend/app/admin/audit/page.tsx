"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminTabs, useAdminNav } from "@/components/AdminTabs";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/ui/PageHeader";
import { ApiError, AuditOverview, Ops, auditApi } from "@/lib/api";

const when = (t: string | null) => (t ? new Date(t).toLocaleString() : "—");

function Table({
  id,
  title,
  head,
  rows,
}: {
  id: string;
  title: string;
  head: string[];
  rows: (string | number | null)[][];
}) {
  return (
    <section className="card" aria-labelledby={id} data-testid={id}>
      <h2 id={id}>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted small">Nothing yet.</p>
      ) : (
        <div className="table-wrap">
          <table className="small">
            <thead>
              <tr>
                {head.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  {r.map((c, j) => (
                    <td key={j} className="mono">
                      {c ?? "—"}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function AuditPage() {
  const router = useRouter();
  const nav = useAdminNav();
  const [data, setData] = useState<AuditOverview | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [ops, setOps] = useState<Ops | null>(null);

  useEffect(() => {
    auditApi
      .ops()
      .then(setOps)
      .catch(() => setOps(null));
    auditApi
      .overview()
      .then(setData)
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) router.replace("/admin/login");
        else setFailure("Could not load the audit trail.");
      });
  }, [router]);

  return (
    <Shell nav={nav}>
      <PageHeader
        eyebrow="Admin console · educational prototype"
        title="Audit trail"
        lead="Agent actions, approval decisions, retrieval sources, background jobs and model versions. Ids, codes and versions only: no messages or document text are stored."
      />
      <AdminTabs />
      {failure && (
        <div className="alert warn" role="alert">
          {failure}
        </div>
      )}
      {ops && (
        <>
          <Table
            id="ops-routes"
            title={`Operations: API latency and errors (last ${ops.window_hours} h, ${ops.requests} requests)`}
            head={["Route", "Count", "p50 ms", "p95 ms", "4xx", "5xx"]}
            rows={ops.routes.map((r) => [
              `${r.method} ${r.route}`,
              r.count,
              r.p50_ms,
              r.p95_ms,
              r.rate_4xx,
              r.rate_5xx,
            ])}
          />
          <Table
            id="ops-tokens"
            title="Operations: token usage and cost estimates"
            head={["Day", "Assistant tokens", "Local cost $", "Hosted equivalent $ (illustrative)", "Agent tokens"]}
            rows={ops.tokens_by_day.map((d) => [
              d.day,
              d.assistant.total_tokens,
              d.assistant.cost_usd,
              d.assistant.hosted_equivalent_usd,
              d.agent_tokens,
            ])}
          />
          <p className="disclaimer small">{ops.cost_note}</p>
        </>
      )}
      {data &&
        (() => {
          const m = data.model_versions;
          const mon = data.monitoring;
          return (
            <>
              <section className="card" aria-labelledby="models" data-testid="audit-models">
                <h2 id="models">Model versions</h2>
                <dl className="small">
                  <dt>No-show model (served)</dt>
                  <dd className="mono">{m.no_show_served}</dd>
                  <dt>Monitoring baseline</dt>
                  <dd className="mono">{m.monitoring_baseline ?? "—"}</dd>
                  <dt>LLM / embedder in use</dt>
                  <dd className="mono">
                    {m.llm_configured} / {m.embedder_configured}
                  </dd>
                  <dt>LLMs recorded</dt>
                  <dd className="mono">
                    {[...new Set([...m.llms_on_answers, ...m.llms_on_agent_runs])].join(", ") || "—"}
                  </dd>
                  <dt>Drift (7 days)</dt>
                  <dd>
                    {mon.verdict}
                    {mon.psi !== null ? ` · PSI ${mon.psi}` : ""} · {mon.predictions} predictions · failure rate{" "}
                    {mon.failure_rate ?? "—"}
                    {mon.flags.length ? ` · flags: ${mon.flags.join(", ")}` : ""}
                  </dd>
                </dl>
                <p className="disclaimer small">{mon.disclaimer}</p>
              </section>
              <Table
                id="audit-runs"
                title="Agent runs"
                head={["When", "Status", "Stop", "Tools → result", "Proposal"]}
                rows={data.agent_runs.map((r) => [
                  when(r.created_at),
                  r.status,
                  r.stopped_reason,
                  r.steps
                    .filter((s) => s.tool)
                    .map((s) => `${s.tool}→${s.code}`)
                    .join(", "),
                  r.pending_action_id,
                ])}
              />
              <Table
                id="audit-approvals"
                title="Approval decisions: proposed writes"
                head={["Proposed", "Status", "By agent", "Decided", "Booking"]}
                rows={data.approval_decisions.actions.map((a) => [
                  when(a.created_at),
                  a.status,
                  a.proposed_by_agent ? "yes" : "no",
                  when(a.decided_at),
                  a.booking_id,
                ])}
              />
              <Table
                id="audit-documents"
                title="Approval decisions: document versions"
                head={["Document", "Version", "Status", "Decided by", "When"]}
                rows={data.approval_decisions.document_versions.map((v) => [
                  v.document_id,
                  v.version,
                  v.status,
                  v.decided_by,
                  when(v.decided_at),
                ])}
              />
              <Table
                id="audit-sources"
                title="Retrieval sources (assistant answers)"
                head={["When", "Status", "Given", "Cited"]}
                rows={data.retrieval_sources.map((a) => [
                  when(a.created_at),
                  a.status,
                  a.sources.map((p) => p.passage_id).join(", "),
                  a.citations.map((p) => p.passage_id).join(", "),
                ])}
              />
              <Table
                id="audit-jobs"
                title="Background indexing jobs"
                head={["Job", "Document v", "Status", "Attempts", "Error", "Finished"]}
                rows={data.jobs.map((j) => [
                  j.id,
                  `${j.document_id} v${j.version}`,
                  j.status,
                  `${j.attempts}/${j.max_attempts}`,
                  j.error_code,
                  when(j.finished_at),
                ])}
              />
            </>
          );
        })()}
    </Shell>
  );
}
