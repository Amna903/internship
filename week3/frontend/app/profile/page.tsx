"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { DISCLAIMER, FieldError, Shell } from "@/components/Shell";
import { ApiError, Profile, SECTION_LABELS, userApi } from "@/lib/api";

const AGE_RANGES = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"];
const toLines = (items: string[]) => items.join("\n");
const fromLines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean);

type Form = {
  full_name: string; ageMode: "dob" | "range"; date_of_birth: string; age_range: string;
  contact_preference: Profile["contact_preference"]; goals: string; allergies: string;
  ec_name: string; ec_phone: string; ec_rel: string; notes: string;
};

function toForm(p: Profile): Form {
  return {
    full_name: p.full_name, ageMode: p.age_range ? "range" : "dob", date_of_birth: p.date_of_birth ?? "",
    age_range: p.age_range, contact_preference: p.contact_preference, goals: toLines(p.wellness_goals),
    allergies: toLines(p.allergies), ec_name: p.emergency_contact_name, ec_phone: p.emergency_contact_phone,
    ec_rel: p.emergency_contact_relationship, notes: p.lifestyle_notes,
  };
}

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    userApi.getProfile()
      .then((p) => { setProfile(p); setForm(toForm(p)); })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login");
        else setMessage({ kind: "error", text: "Could not load your profile." });
      });
  }, [router]);

  async function logout() {
    try { await userApi.logout(); } finally { router.push("/login"); }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true); setErrors({}); setMessage(null);
    try {
      const updated = await userApi.updateProfile({
        full_name: form.full_name,
        // Only one of DOB / age range is sent (the API rejects both together).
        ...(form.ageMode === "dob"
          ? { date_of_birth: form.date_of_birth || null }
          : { age_range: form.age_range }),
        contact_preference: form.contact_preference,
        wellness_goals: fromLines(form.goals),
        allergies: fromLines(form.allergies),
        emergency_contact_name: form.ec_name,
        emergency_contact_phone: form.ec_phone,
        emergency_contact_relationship: form.ec_rel,
        lifestyle_notes: form.notes,
      } as Partial<Profile>);
      setProfile(updated); setForm(toForm(updated));
      setMessage({ kind: "ok", text: "Profile saved." });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 401) return router.replace("/login");
        setErrors(err.fieldErrors);
        setMessage({ kind: "error", text: err.code === "validation_error" ? "Please fix the highlighted fields." : err.message });
      } else setMessage({ kind: "error", text: "Network error. Please try again." });
    } finally { setBusy(false); }
  }

  const nav = <button className="btn ghost small" onClick={logout}>Sign out</button>;
  if (!profile || !form) {
    return <Shell nav={nav}>{message ? <div className="alert error">{message.text}</div> : <p className="muted">Loading…</p>}</Shell>;
  }
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm({ ...form, [k]: v });

  return (
    <Shell nav={nav}>
      <h1>My profile</h1>
      <p className="muted small">Signed in as {profile.email} · <span className="badge">{profile.status}</span></p>
      <p className="alert warn small">{DISCLAIMER}</p>

      <section className="card" aria-labelledby="completion-heading">
        <h2 id="completion-heading">Profile completion</h2>
        <div className="progress" role="progressbar" aria-valuenow={profile.completion.percent} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completion">
          <span style={{ width: `${profile.completion.percent}%` }} />
        </div>
        <p className="small">
          {profile.completion.percent}% complete ·{" "}
          <span className={`badge ${profile.completion.status === "complete" ? "" : "tone-warn"}`}>{profile.completion.status}</span>
        </p>
        {profile.completion.missing_sections.length > 0 && (
          <>
            <p className="small muted">Still to fill in:</p>
            <ul className="small">{profile.completion.missing_sections.map((s) => <li key={s}>{SECTION_LABELS[s] ?? s}</li>)}</ul>
          </>
        )}
      </section>

      <form className="card" onSubmit={save} noValidate>
        {message && <div className={`alert ${message.kind}`} role="status">{message.text}</div>}

        <h2>About you</h2>
        <label htmlFor="full_name">Full name</label>
        <input id="full_name" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
        <FieldError errors={errors} name="full_name" />

        <div className="grid">
          <div>
            <label htmlFor="agemode">Age information</label>
            <select id="agemode" value={form.ageMode} onChange={(e) => set("ageMode", e.target.value as Form["ageMode"])}>
              <option value="dob">Date of birth</option>
              <option value="range">Age range</option>
            </select>
          </div>
          <div>
            {form.ageMode === "dob" ? (<>
              <label htmlFor="dob">Date of birth</label>
              <input id="dob" type="date" value={form.date_of_birth} onChange={(e) => set("date_of_birth", e.target.value)} />
              <FieldError errors={errors} name="date_of_birth" />
            </>) : (<>
              <label htmlFor="range">Age range</label>
              <select id="range" value={form.age_range} onChange={(e) => set("age_range", e.target.value)}>
                <option value="">Select…</option>
                {AGE_RANGES.map((r) => <option key={r}>{r}</option>)}
              </select>
              <FieldError errors={errors} name="age_range" />
            </>)}
          </div>
        </div>

        <label htmlFor="contact">Contact preference</label>
        <select id="contact" value={form.contact_preference} onChange={(e) => set("contact_preference", e.target.value as Form["contact_preference"])}>
          <option value="email">Email</option><option value="phone">Phone call</option>
          <option value="sms">SMS</option><option value="none">Do not contact</option>
        </select>
        <FieldError errors={errors} name="contact_preference" />

        <h2 style={{ marginTop: 24 }}>Wellness</h2>
        <label htmlFor="goals">Wellness goals</label>
        <textarea id="goals" value={form.goals} onChange={(e) => set("goals", e.target.value)} />
        <div className="hint">One per line, up to 10.</div>
        <FieldError errors={errors} name="wellness_goals" />

        <label htmlFor="allergies">Allergies (optional)</label>
        <textarea id="allergies" value={form.allergies} onChange={(e) => set("allergies", e.target.value)} />
        <div className="hint">One per line, up to 20.</div>
        <FieldError errors={errors} name="allergies" />

        <label htmlFor="notes">Lifestyle notes (optional)</label>
        <textarea id="notes" value={form.notes} onChange={(e) => set("notes", e.target.value)} maxLength={1000} />
        <FieldError errors={errors} name="lifestyle_notes" />

        <h2 style={{ marginTop: 24 }}>Emergency contact (fictional)</h2>
        <div className="grid">
          <div>
            <label htmlFor="ecn">Name</label>
            <input id="ecn" value={form.ec_name} onChange={(e) => set("ec_name", e.target.value)} />
            <FieldError errors={errors} name="emergency_contact_name" />
          </div>
          <div>
            <label htmlFor="ecr">Relationship</label>
            <input id="ecr" value={form.ec_rel} onChange={(e) => set("ec_rel", e.target.value)} />
            <FieldError errors={errors} name="emergency_contact_relationship" />
          </div>
        </div>
        <label htmlFor="ecp">Phone</label>
        <input id="ecp" inputMode="tel" value={form.ec_phone} onChange={(e) => set("ec_phone", e.target.value)} />
        <FieldError errors={errors} name="emergency_contact_phone" />

        <button className="btn block" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button>
      </form>
    </Shell>
  );
}
