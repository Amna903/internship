"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AdminTabs, useAdminNav } from "@/components/AdminTabs";
import { Shell } from "@/components/Shell";
import { FormField } from "@/components/ui/FormField";
import { PageHeader } from "@/components/ui/PageHeader";
import { ModelCard, predictionApi } from "@/lib/api";
import {
  buildRequest,
  DEFAULT_FORM,
  describe,
  ErrorView,
  errorView,
  FieldName,
  FormState,
  LABELS,
  optionText,
  percent,
  PredictionResponse,
  PRESETS,
  presetToForm,
  SCHEMA,
} from "@/lib/prediction";

const HINTS: Partial<Record<FieldName, string>> = {
  prior_appointments: "Enter the counts yourself; nothing is looked up.",
  prior_no_shows: "Cannot be more than the earlier appointments.",
  distance_km: "Leave blank if unknown.",
};

export default function NoShowEstimatePage() {
  const router = useRouter();
  const nav = useAdminNav();
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<string, string>>>({});
  const [result, setResult] = useState<PredictionResponse | null>(null);
  const [failure, setFailure] = useState<Exclude<ErrorView, { kind: "signed_out" }> | null>(null);
  const [busy, setBusy] = useState(false);
  const [card, setCard] = useState<ModelCard | null | "unavailable">(null);
  // Each submit gets a number; only the newest one may show its answer (no stale results).
  const latest = useRef(0);

  useEffect(() => {
    predictionApi
      .model()
      .then(setCard)
      .catch(() => setCard("unavailable"));
  }, [router]);

  function change(next: FormState) {
    latest.current += 1; // any edit makes an in-flight answer stale
    setForm(next);
    setResult(null); // never show an old estimate next to new inputs
    setFieldErrors({});
    setFailure(null);
  }

  function set(name: FieldName, value: string | boolean) {
    change({ ...form, [name]: value } as FormState);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const { payload, errors } = buildRequest(form);
    if (!payload) {
      setFieldErrors(errors);
      setFailure(null);
      setResult(null);
      return;
    }
    const ticket = ++latest.current;
    setBusy(true);
    setFailure(null);
    setFieldErrors({});
    try {
      const response = await predictionApi.predict(payload);
      if (ticket === latest.current) setResult(response);
    } catch (err) {
      if (ticket !== latest.current) return;
      const view = errorView(err);
      if (view.kind === "signed_out") {
        router.replace("/admin/login");
        return;
      }
      if (view.kind === "fields") setFieldErrors(view.fields);
      setFailure(view);
    } finally {
      if (ticket === latest.current) setBusy(false);
    }
  }

  const control = (name: FieldName) => {
    const spec = SCHEMA[name];
    return (
      <FormField
        key={name}
        id={name}
        label={LABELS[name]}
        hint={HINTS[name]}
        error={fieldErrors[name]}
        required={!(spec.type === "number" && spec.nullable)}
        kind={spec.type === "boolean" ? "group" : "single"}
      >
        {(props) => {
          if (spec.type === "category") {
            return (
              <select
                {...props}
                value={form[name as Exclude<FieldName, "reminder_sent">]}
                onChange={(e) => set(name, e.target.value)}
              >
                {spec.values.map((v) => (
                  <option key={v} value={v}>
                    {optionText(v)}
                  </option>
                ))}
              </select>
            );
          }
          if (spec.type === "boolean") {
            return (
              <div className="choice-row" role="radiogroup">
                {[true, false].map((v) => (
                  <label key={String(v)} className="choice">
                    <input
                      type="radio"
                      name={props.name}
                      checked={form.reminder_sent === v}
                      onChange={() => set(name, v)}
                    />
                    {v ? "Yes" : "No"}
                  </label>
                ))}
              </div>
            );
          }
          return (
            <input
              {...props}
              type="number"
              inputMode={spec.type === "integer" ? "numeric" : "decimal"}
              min={spec.min}
              max={spec.max}
              step={spec.type === "integer" ? 1 : 0.1}
              value={form[name as Exclude<FieldName, "reminder_sent">]}
              onChange={(e) => set(name, e.target.value)}
            />
          );
        }}
      </FormField>
    );
  };

  const text = result ? describe(result) : null;

  return (
    <Shell nav={nav}>
      <PageHeader
        eyebrow="Admin console · educational prototype"
        title="Appointment no-show estimate"
        lead="Estimate whether a fictional appointment may be missed, to decide on an extra reminder. Synthetic data only."
      />
      <AdminTabs />

      <div className="estimate-layout">
        <form className="card" onSubmit={submit} noValidate aria-describedby="estimate-intro">
          <p id="estimate-intro" className="muted small">
            Enter the appointment details. Nothing is looked up: the history counts are whatever you type.
          </p>
          <div className="preset-row" aria-label="Fill example">
            <span className="muted small">Fill example:</span>
            {PRESETS.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="btn ghost small"
                onClick={() => change(presetToForm(preset.values))}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <h2 className="form-section">Appointment</h2>
          <div className="grid">
            {(
              [
                "lead_time_days",
                "appointment_weekday",
                "appointment_hour",
                "visit_type",
                "booking_channel",
                "reminder_sent",
              ] as FieldName[]
            ).map(control)}
          </div>
          <h2 className="form-section">Person and history</h2>
          <div className="grid">
            {(["age_band", "distance_km", "prior_appointments", "prior_no_shows"] as FieldName[]).map(control)}
          </div>

          {failure && (
            <div
              className={`alert ${failure.kind === "unavailable" || failure.kind === "throttled" ? "warn" : "error"}`}
              role="alert"
            >
              {failure.message}
            </div>
          )}

          <div className="form-actions">
            <button type="submit" className="btn" disabled={busy}>
              {busy ? "Estimating…" : "Estimate"}
            </button>
            <button type="button" className="btn ghost" onClick={() => change(DEFAULT_FORM)} disabled={busy}>
              Reset
            </button>
          </div>
        </form>

        <section className="card estimate-result" aria-labelledby="result-title">
          <h2 id="result-title">Result</h2>
          <div aria-live="polite" aria-atomic="true">
            {text ? (
              <>
                <p className="suggestion">{text.headline}</p>
                <p className="chance">{text.chance}</p>
                <p className="muted small">{text.comparison}</p>
                <p className="small">{text.meaning}</p>
                <p className="disclaimer small" data-testid="disclaimer">
                  {text.disclaimer}
                </p>
                <p className="muted small mono">{text.version}</p>
              </>
            ) : (
              <p className="muted">
                {busy ? "Estimating…" : "Fill in the form (or pick an example) and press Estimate."}
              </p>
            )}
          </div>

          <details className="model-card">
            <summary>About this model</summary>
            {card === null && <p className="muted small">Loading…</p>}
            {card === "unavailable" && <p className="muted small">Model details are unavailable right now.</p>}
            {card && card !== "unavailable" && (
              <dl className="small">
                <dt>Version</dt>
                <dd className="mono">{card.model_version}</dd>
                <dt>Model</dt>
                <dd>{card.estimator}</dd>
                <dt>Test scores (synthetic data)</dt>
                <dd>
                  PR-AUC {card.metrics.test.pr_auc.toFixed(3)} · ROC-AUC {card.metrics.test.roc_auc.toFixed(3)}
                </dd>
                <dt>Extra reminder from</dt>
                <dd>{percent(card.decision.threshold)}</dd>
                <dt>Inputs</dt>
                <dd>{card.inputs_note}</dd>
              </dl>
            )}
            {card && card !== "unavailable" && <p className="disclaimer small">{card.disclaimer}</p>}
          </details>
        </section>
      </div>
    </Shell>
  );
}
