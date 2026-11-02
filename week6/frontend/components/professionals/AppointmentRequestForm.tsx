"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { FormField } from "@/components/ui/FormField";
import { Stepper } from "@/components/ui/Stepper";
import {
  CONTACT_METHODS, NOTE_MAX, REASONS, STEPS, emptyDraft, firstInvalidStep, isDraft, validateStep,
  type ContactMethod, type Draft, type Errors, type Reason,
} from "@/lib/appointment";
import { localStore, useLocalStore } from "@/lib/localStore";
import { DAY_LABELS, VISIT_LABELS, availableDays, formatFee, type Day, type Professional, type VisitType } from "@/lib/professionals";

/** Where the error-summary link sends focus for each field (radio groups focus their first option). */
const focusTarget = (field: keyof Draft, d: Draft, p: Professional): string => {
  if (field === "visitType") return `visitType-${p.visitTypes[0]}`;
  if (field === "time") return d.day ? `time-${p.availability[d.day]?.[0]}` : "day";
  if (field === "contactMethod") return "contactMethod-email";
  return field;
};

export function AppointmentRequestForm({ professional: p }: { professional: Professional }) {
  // One draft per professional, persisted in localStorage so it survives refresh.
  const store = useMemo(() => localStore<Draft>(`hp.appointmentDraft.v1.${p.id}`, emptyDraft(p), isDraft), [p]);
  const [draft, setDraft, hydrated] = useLocalStore(store);
  const [errors, setErrors] = useState<Errors>({});
  const [submitted, setSubmitted] = useState<Draft | null>(null);
  const [failedAttempts, setFailedAttempts] = useState(0);
  const summaryRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstRender = useRef(true);

  // A restored draft may point past a step that is no longer valid (e.g. data changed): rewind.
  const step = hydrated ? Math.min(draft.step, firstInvalidStep(draft, p)) : 0;
  const current = STEPS[step];
  const update = (patch: Partial<Draft>) => setDraft((prev) => ({ ...prev, ...patch }));
  const goTo = (n: number) => { setErrors({}); update({ step: n }); };

  // Move focus to the new step's heading so keyboard and screen-reader users land in the right place.
  useEffect(() => {
    if (firstRender.current) { firstRender.current = false; return; }
    headingRef.current?.focus();
  }, [step]);

  // Runs after the error summary is in the DOM, on every failed Next (even with identical errors).
  useEffect(() => {
    if (failedAttempts) summaryRef.current?.focus();
  }, [failedAttempts]);

  const next = () => {
    const found = validateStep(step, draft, p);
    setErrors(found);
    if (Object.keys(found).length) {
      setFailedAttempts((n) => n + 1); // focus moves to the summary once it has rendered (effect below)
      return;
    }
    if (step < STEPS.length - 1) goTo(step + 1);
    else {
      setSubmitted(draft);
      store.clear();
    }
  };

  if (submitted) return <Confirmation professional={p} draft={submitted} />;
  if (!hydrated) return <p className="muted" role="status">Loading your saved draft…</p>;

  const err = (k: keyof Draft) => errors[k];
  const errorList = Object.entries(errors) as [keyof Draft, string][];

  return (
    <form className="card request-form" noValidate onSubmit={(e) => { e.preventDefault(); next(); }}>
      <Stepper steps={STEPS} current={step} />

      <h2 ref={headingRef} tabIndex={-1} className="step-heading">{current.label}</h2>

      {errorList.length > 0 && (
        <div ref={summaryRef} tabIndex={-1} className="alert error error-summary" role="alert" aria-labelledby="error-summary-title">
          <p id="error-summary-title"><strong>Please fix {errorList.length === 1 ? "this" : `these ${errorList.length}`} before continuing:</strong></p>
          <ul>
            {errorList.map(([field, message]) => (
              <li key={field}>
                <a href={`#${focusTarget(field, draft, p)}`} onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(focusTarget(field, draft, p))?.focus();
                }}>{message}</a>
              </li>
            ))}
          </ul>
        </div>
      )}

      {current.id === "visit" && (
        <>
          <FormField id="visitType" kind="group" label="How would you like to meet?" required error={err("visitType")}>
            {(c) => (
              <div className="options">
                {p.visitTypes.map((v) => (
                  <label key={v} className="option">
                    <input type="radio" id={`visitType-${v}`} name={c.name} value={v} checked={draft.visitType === v}
                      aria-invalid={c["aria-invalid"]} onChange={() => update({ visitType: v as VisitType })} />
                    {VISIT_LABELS[v]}
                  </label>
                ))}
              </div>
            )}
          </FormField>
          <FormField id="reason" label="Reason for the visit" required error={err("reason")}>
            {(c) => (
              <select {...c} value={draft.reason} onChange={(e) => update({ reason: e.target.value as Reason | "" })}>
                <option value="">Choose a reason…</option>
                {Object.entries(REASONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            )}
          </FormField>
          <FormField id="note" label="Anything else? (optional)" error={err("note")}
            hint={`${draft.note.length}/${NOTE_MAX} characters. Please don't include medical details: this is a demo.`}>
            {(c) => <textarea {...c} value={draft.note} onChange={(e) => update({ note: e.target.value })} />}
          </FormField>
        </>
      )}

      {current.id === "time" && (
        <>
          <FormField id="day" label="Preferred day" required error={err("day")}>
            {(c) => (
              <select {...c} value={draft.day} onChange={(e) => update({ day: e.target.value as Day | "", time: "" })}>
                <option value="">Choose a day…</option>
                {availableDays(p).map((d) => <option key={d} value={d}>{DAY_LABELS[d]}</option>)}
              </select>
            )}
          </FormField>
          <FormField id="time" kind="group" label="Preferred time" required error={err("time")}
            hint={draft.day ? undefined : "Choose a day first to see the available times."}>
            {(c) => (
              <div className="options times">
                {(draft.day ? p.availability[draft.day] ?? [] : []).map((t) => (
                  <label key={t} className="option">
                    <input type="radio" id={`time-${t}`} name={c.name} value={t} checked={draft.time === t}
                      aria-invalid={c["aria-invalid"]} onChange={() => update({ time: t })} />
                    {t}
                  </label>
                ))}
              </div>
            )}
          </FormField>
        </>
      )}

      {current.id === "details" && (
        <>
          <FormField id="fullName" label="Full name" required error={err("fullName")}>
            {(c) => <input {...c} autoComplete="name" value={draft.fullName} onChange={(e) => update({ fullName: e.target.value })} />}
          </FormField>
          <FormField id="email" label="Email" required error={err("email")} hint="Use a made-up address, e.g. you@example.test">
            {(c) => <input {...c} type="email" autoComplete="email" value={draft.email} onChange={(e) => update({ email: e.target.value })} />}
          </FormField>
          <FormField id="contactMethod" kind="group" label="How should they contact you?" required>
            {(c) => (
              <div className="options">
                {Object.entries(CONTACT_METHODS).map(([value, label]) => (
                  <label key={value} className="option">
                    <input type="radio" id={`contactMethod-${value}`} name={c.name} value={value} checked={draft.contactMethod === value}
                      onChange={() => update({ contactMethod: value as ContactMethod })} />
                    {label}
                  </label>
                ))}
              </div>
            )}
          </FormField>
          <FormField id="phone" label={draft.contactMethod === "phone" ? "Phone" : "Phone (optional)"}
            required={draft.contactMethod === "phone"} error={err("phone")}>
            {(c) => <input {...c} type="tel" autoComplete="tel" value={draft.phone} onChange={(e) => update({ phone: e.target.value })} />}
          </FormField>
        </>
      )}

      {current.id === "review" && (
        <>
          <Summary professional={p} draft={draft} onEdit={goTo} />
          <FormField id="acknowledged" kind="group" label="Confirm" required error={err("acknowledged")}>
            {(c) => (
              <label className="option">
                <input type="checkbox" id="acknowledged" checked={draft.acknowledged} aria-invalid={c["aria-invalid"]}
                  onChange={(e) => update({ acknowledged: e.target.checked })} />
                I understand this is a demo: nothing is sent or booked.
              </label>
            )}
          </FormField>
        </>
      )}

      <div className="form-nav">
        <button type="button" className="btn ghost" onClick={() => goTo(step - 1)} disabled={step === 0}>Previous</button>
        <span className="muted small">Draft saved on this device</span>
        <button type="submit" className="btn">{step === STEPS.length - 1 ? "Send request" : "Next"}</button>
      </div>
      <p className="small">
        <button type="button" className="linklike" onClick={() => { store.clear(); setErrors({}); }}>Start over</button>
      </p>
    </form>
  );
}

function Summary({ professional: p, draft: d, onEdit }: { professional: Professional; draft: Draft; onEdit?: (step: number) => void }) {
  const edit = (step: number, what: string) =>
    onEdit && <button type="button" className="linklike small" onClick={() => onEdit(step)}>Edit<span className="visually-hidden"> {what}</span></button>;
  return (
    <dl className="kv summary">
      <dt>Professional</dt><dd>{p.name}, {p.title} · {formatFee(p.feePkr)}</dd>
      <dt>Visit</dt><dd>{d.visitType && VISIT_LABELS[d.visitType]} · {d.reason && REASONS[d.reason]} {edit(0, "visit")}</dd>
      {d.note && (<><dt>Note</dt><dd>{d.note}</dd></>)}
      <dt>When</dt><dd>{d.day && DAY_LABELS[d.day]} at {d.time} {edit(1, "time")}</dd>
      <dt>Contact</dt>
      <dd>{d.fullName} · {d.email}{d.phone && ` · ${d.phone}`} (prefers {CONTACT_METHODS[d.contactMethod].toLowerCase()}) {edit(2, "details")}</dd>
    </dl>
  );
}

function Confirmation({ professional: p, draft }: { professional: Professional; draft: Draft }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="card" ref={ref} tabIndex={-1} aria-labelledby="done-title">
      <h2 id="done-title">Request ready (demo)</h2>
      <p className="alert ok" role="status">Nothing was sent or booked. In a real app, {p.name}&apos;s team would now confirm by {CONTACT_METHODS[draft.contactMethod].toLowerCase()}.</p>
      <Summary professional={p} draft={draft} />
      <p style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
        <Link className="btn" href="/professionals">Back to professionals</Link>
        <Link className="btn ghost" href={`/professionals/${p.id}`}>View {p.name}</Link>
      </p>
    </div>
  );
}
