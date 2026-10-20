"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { FieldError, Shell } from "@/components/Shell";
import { adminApi, ApiError, ModelCard, NoShowInput, NoShowResponse } from "@/lib/api";

const WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"];
const VISIT_TYPES: Record<string, string> = { in_person: "In person", video: "Video", phone: "Phone" };
const CHANNELS = ["web", "phone", "app"];
const MODEL_LABELS: Record<string, string> = {
  logistic_engineered: "Logistic regression + engineered features (served)",
  logistic_raw: "Logistic regression, raw inputs (baseline)",
  hist_gradient_boosting: "Gradient boosting + engineered features",
  majority_prior: "Always predict the average (floor)",
  oracle_ceiling: "Oracle: the generator's true probability (ceiling)",
};

type Form = Record<keyof NoShowInput, string>;
const START: Form = {
  lead_time_days: "14", appointment_weekday: "tuesday", appointment_hour: "10", age_band: "35-44",
  visit_type: "in_person", booking_channel: "web", reminder_sent: "true", prior_appointments: "4",
  prior_no_shows: "0", distance_km: "6.5",
};

function toInput(f: Form): NoShowInput {
  // Numbers are sent as typed; the API does the range checks and reports field errors.
  const num = (v: string) => (v.trim() === "" ? (NaN as number) : Number(v));
  return {
    lead_time_days: num(f.lead_time_days), appointment_weekday: f.appointment_weekday, appointment_hour: num(f.appointment_hour),
    age_band: f.age_band, visit_type: f.visit_type, booking_channel: f.booking_channel, reminder_sent: f.reminder_sent === "true",
    prior_appointments: num(f.prior_appointments), prior_no_shows: num(f.prior_no_shows),
    distance_km: f.distance_km.trim() === "" ? null : num(f.distance_km),
  };
}

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

export default function NoShowPage() {
  const router = useRouter();
  const [form, setForm] = useState<Form>(START);
  const [result, setResult] = useState<NoShowResponse | null>(null);
  const [card, setCard] = useState<ModelCard | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminApi.me().catch(() => router.replace("/admin/login"));
    adminApi.noShowModel().then(setCard).catch((err) => {
      if (err instanceof ApiError && err.status === 503) setMessage("The model is not available right now.");
    });
  }, [router]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setErrors({}); setMessage(""); setResult(null);
    try {
      setResult(await adminApi.predictNoShow(toInput(form)));
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401 || err.status === 403) return router.replace("/admin/login");
        if (err.code === "validation_error") { setErrors(err.fieldErrors); setMessage("Please fix the highlighted fields."); }
        else setMessage(err.status === 503 ? "The model is not available right now. Try again later." : err.message);
      } else setMessage("Network error. Please try again.");
    } finally { setBusy(false); }
  }

  const set = (k: keyof Form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const p = result?.prediction;

  return (
    <Shell nav={<Link href="/admin">← All profiles</Link>}>
      <h1>Appointment no-show estimate</h1>
      <p className="alert warn small">
        Educational prototype trained on synthetic data. It estimates whether an appointment might be missed, to plan
        reminders. It is not a medical assessment and must not be used for clinical decisions.
      </p>

      <form className="card" onSubmit={submit} noValidate>
        {message && <div className="alert error" role="alert">{message}</div>}
        <h2>Appointment (fictional)</h2>
        <div className="grid">
          <div>
            <label htmlFor="lead">Days between booking and visit</label>
            <input id="lead" type="number" inputMode="numeric" value={form.lead_time_days} onChange={set("lead_time_days")} />
            <FieldError errors={errors} name="lead_time_days" />
          </div>
          <div>
            <label htmlFor="hour">Hour (24h)</label>
            <input id="hour" type="number" inputMode="numeric" value={form.appointment_hour} onChange={set("appointment_hour")} />
            <FieldError errors={errors} name="appointment_hour" />
          </div>
          <div>
            <label htmlFor="day">Weekday</label>
            <select id="day" value={form.appointment_weekday} onChange={set("appointment_weekday")}>
              {WEEKDAYS.map((d) => <option key={d} value={d}>{d[0].toUpperCase() + d.slice(1)}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="visit">Visit type</label>
            <select id="visit" value={form.visit_type} onChange={set("visit_type")}>
              {Object.entries(VISIT_TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="channel">Booked via</label>
            <select id="channel" value={form.booking_channel} onChange={set("booking_channel")}>
              {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="reminder">Reminder sent</label>
            <select id="reminder" value={form.reminder_sent} onChange={set("reminder_sent")}>
              <option value="true">Yes</option><option value="false">No</option>
            </select>
          </div>
        </div>

        <h2 style={{ marginTop: 24 }}>History (fictional)</h2>
        <div className="grid">
          <div>
            <label htmlFor="age">Age band</label>
            <select id="age" value={form.age_band} onChange={set("age_band")}>
              {AGE_BANDS.map((a) => <option key={a}>{a}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="dist">Distance (km, optional)</label>
            <input id="dist" type="number" inputMode="decimal" value={form.distance_km} onChange={set("distance_km")} />
            <FieldError errors={errors} name="distance_km" />
          </div>
          <div>
            <label htmlFor="prior">Prior appointments</label>
            <input id="prior" type="number" inputMode="numeric" value={form.prior_appointments} onChange={set("prior_appointments")} />
            <FieldError errors={errors} name="prior_appointments" />
          </div>
          <div>
            <label htmlFor="missed">Prior no-shows</label>
            <input id="missed" type="number" inputMode="numeric" value={form.prior_no_shows} onChange={set("prior_no_shows")} />
            <FieldError errors={errors} name="prior_no_shows" />
          </div>
        </div>
        <button className="btn block" disabled={busy}>{busy ? "Estimating…" : "Estimate no-show risk"}</button>
      </form>

      {p && result && (
        <section className="card" aria-live="polite" aria-labelledby="result-heading">
          <h2 id="result-heading">Estimate</h2>
          <p className="result-number">{pct(p.no_show_probability)}</p>
          <p>
            <span className={`badge ${p.risk_band === "high" ? "tone-danger" : p.risk_band === "medium" ? "tone-warn" : ""}`}>
              {p.risk_band} risk
            </span>{" "}
            <span className="small muted">
              Average no-show rate {pct(p.baseline_no_show_rate)} · flagged as high at {pct(p.decision_threshold)} or more
            </span>
          </p>
          <p className="small muted">Model {result.model_version}. {result.disclaimer}</p>
        </section>
      )}

      {card && (
        <section className="card" aria-labelledby="card-heading">
          <h2 id="card-heading">About this model</h2>
          <p className="small">{card.task} Trained on {card.data.rows.toLocaleString()} synthetic appointments; {card.data.split}.</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Model (test set)</th><th>ROC-AUC</th><th>PR-AUC</th><th>Brier</th></tr></thead>
              <tbody>
                {Object.entries(card.test_metrics).map(([name, m]) => (
                  <tr key={name}>
                    <td className="wrap">{MODEL_LABELS[name] ?? name}</td>
                    <td>{m.roc_auc}</td><td>{m.pr_auc}</td><td>{m.brier}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Higher AUC is better, lower Brier is better. The served model is close to the ceiling: most of what is left is
            randomness in the synthetic data, not something a better model could learn.
          </p>
        </section>
      )}
    </Shell>
  );
}
