"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AdminTabs, useAdminNav } from "@/components/AdminTabs";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/ui/PageHeader";
import { ConfirmKeys, STOP_REASONS, formatStep } from "@/lib/agent";
import { ActionCard, AgentRunResponse, ApiError, agentApi } from "@/lib/api";

const EXAMPLES = [
  { label: "Multi-tool", message: "Is there a telehealth slot next Tuesday morning, and what is the late cancellation fee?" },
  { label: "Booking (needs approval)", message: "Please book the first telehealth slot next Wednesday." },
  { label: "Missing details", message: "Will this patient miss their appointment?" },
];

function failureText(err: unknown): string | "signed_out" {
  if (!(err instanceof ApiError)) return "Could not reach the server. Try again.";
  if (err.status === 401 || err.status === 403) return "signed_out";
  if (err.status === 429) return "Too many requests in a short time. Wait a minute and try again.";
  if (err.status === 409) return err.message;
  return "Something went wrong. Try again.";
}

export default function AgentPage() {
  const router = useRouter();
  const nav = useAdminNav();
  // The message and the run live in component state only: never stored in the browser.
  const [message, setMessage] = useState("");
  const [run, setRun] = useState<AgentRunResponse | null>(null);
  const [card, setCard] = useState<ActionCard | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const keys = useRef(new ConfirmKeys());

  function fail(err: unknown) {
    const text = failureText(err);
    if (text === "signed_out") router.replace("/admin/login");
    else setFailure(text);
  }

  async function send(text: string) {
    setBusy(true); setFailure(null); setRun(null); setCard(null);
    try {
      const r = await agentApi.run(text);
      setRun(r);
      // The card comes from the server's stored action, never from the model's text.
      if (r.pending_action) setCard(await agentApi.action(r.pending_action.action_id));
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  async function decide(confirm: boolean) {
    if (!card) return;
    setBusy(true); setFailure(null);
    try {
      setCard(confirm ? await agentApi.confirm(card.action_id, keys.current.for(card.action_id))
                      : await agentApi.decline(card.action_id));
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  return (
    <Shell nav={nav}>
      <PageHeader eyebrow="Admin console · educational prototype" title="Clinic admin agent"
                  lead="A controlled agent over five typed tools. The server checks every call; a booking is only proposed until you confirm it." />
      <AdminTabs />
      <section className="card" aria-labelledby="agent-title">
        <h2 id="agent-title">Ask the agent</h2>
        <div className="preset-row" aria-label="Examples">
          <span className="muted small">Try:</span>
          {EXAMPLES.map((e) => (
            <button key={e.label} type="button" className="btn ghost small" disabled={busy}
                    onClick={() => { setMessage(e.message); send(e.message); }}>{e.label}</button>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (message.trim()) send(message.trim()); }}>
          <label htmlFor="agent-message" className="small">Request</label>
          <div className="ask-row">
            <textarea id="agent-message" value={message} maxLength={500} onChange={(e) => setMessage(e.target.value)} />
            <button type="submit" className="btn" disabled={busy || !message.trim()}>{busy ? "Working…" : "Run"}</button>
          </div>
        </form>

        <div aria-live="polite" data-testid="agent-result">
          {failure && <div className="alert warn" role="alert">{failure}</div>}
          {run && (
            <>
              <p className="suggestion" data-testid="agent-status">
                {run.status === "done" ? "Done" : STOP_REASONS[run.stopped_reason ?? ""] ?? `Ended: ${run.status}`}
              </p>
              {run.answer && <p data-testid="agent-answer">{run.answer}</p>}
              {run.citations?.map((c, i) => (
                <blockquote key={i} className="citation"><p className="small">“{c.quote}”</p>
                  <span className="mono muted">{c.source} · {c.passage_id}</span></blockquote>
              ))}
              {run.results.map((r, i) => (
                <details key={i} className="small" data-testid="agent-tool-result" open>
                  <summary className="mono">{r.tool} (shown by the server, not written by the model)</summary>
                  <pre className="mono small">{JSON.stringify(r.output, null, 2)}</pre>
                </details>
              ))}
              <h3 className="form-section">Trace</h3>
              <ol className="mono small" data-testid="agent-trace">
                {run.steps.map((s) => <li key={s.n}>{formatStep(s)}</li>)}
              </ol>
              <p className="muted small">{run.tool_calls} tool call(s) · about {run.tokens.toLocaleString()} tokens · {run.model}</p>
              <p className="disclaimer small">{run.disclaimer}</p>
            </>
          )}
          {card && (
            <section className="card" aria-labelledby="card-title" data-testid="approval-card">
              <h3 id="card-title">{card.proposed_by}</h3>
              <p>{card.summary}</p>
              <p className="small muted">Status: <strong data-testid="card-status">{card.status}</strong>
                {card.status === "pending" && ` · expires ${new Date(card.expires_at).toLocaleTimeString()}`}</p>
              {card.status === "pending" && (
                <div className="preset-row">
                  <button className="btn" disabled={busy} onClick={() => decide(true)} data-testid="confirm">Confirm booking</button>
                  <button className="btn ghost" disabled={busy} onClick={() => decide(false)} data-testid="decline">Decline</button>
                </div>
              )}
              {card.booking && <p className="small">Booked (fictional): {card.booking.date} {card.booking.time} with {card.booking.clinician}.</p>}
            </section>
          )}
        </div>
      </section>
    </Shell>
  );
}
