// Form logic for the no-show estimate page: no React here, so every rule is unit-tested
// (tests/prediction.test.ts). Option lists, ranges and presets come from noShowSchema.json, the same
// file backend tests compare with the API's own schema, so the form and the API cannot drift apart.
//
// The browser checks below are only for quick feedback. The server is the authority: any 400 it
// returns is shown next to the matching field.

import schemaDoc from "./noShowSchema.json";
import { ApiError } from "./api";

type IntegerSpec = { type: "integer"; min: number; max: number; at_most?: string };
type NumberSpec = { type: "number"; min: number; max: number; nullable?: boolean };
type CategorySpec = { type: "category"; values: string[] };
type BooleanSpec = { type: "boolean" };
type Spec = IntegerSpec | NumberSpec | CategorySpec | BooleanSpec;

export const SCHEMA = schemaDoc.features as Record<string, Spec>;
export const ACTIONS = schemaDoc.actions as Record<ActionId, string>;
export const FIELDS = Object.keys(SCHEMA) as FieldName[];

export type FieldName =
  | "lead_time_days" | "appointment_weekday" | "appointment_hour" | "age_band" | "visit_type"
  | "booking_channel" | "reminder_sent" | "prior_appointments" | "prior_no_shows" | "distance_km";
export type ActionId = "extra_reminder_suggested" | "standard_reminder";

/** What the inputs hold: text for numbers (so a field can be blank while typing), a real boolean for the toggle. */
export type FormState = Record<Exclude<FieldName, "reminder_sent">, string> & { reminder_sent: boolean };
export type Payload = Record<FieldName, string | number | boolean | null>;

export interface Prediction {
  no_show_probability: number;
  suggested_action: ActionId;
  suggested_action_label: string;
  decision_threshold: number;
  average_no_show_rate: number;
}
export interface PredictionResponse { model_version: string; prediction: Prediction; disclaimer: string }

export const LABELS: Record<FieldName, string> = {
  lead_time_days: "Days between booking and appointment",
  appointment_weekday: "Weekday",
  appointment_hour: "Hour (24 h clock)",
  age_band: "Age band",
  visit_type: "Visit type",
  booking_channel: "Booking channel",
  reminder_sent: "Standard reminder already sent",
  prior_appointments: "Earlier appointments",
  prior_no_shows: "Earlier appointments missed",
  distance_km: "Distance to clinic (km)",
};

const OPTION_TEXT: Record<string, string> = {
  in_person: "In person", telehealth: "Telehealth", web: "Web", phone: "Phone", app: "App",
};
export const optionText = (value: string) => OPTION_TEXT[value] ?? value.charAt(0).toUpperCase() + value.slice(1);

export interface Preset { id: string; label: string; expected_action: ActionId; values: Payload }
export const PRESETS = schemaDoc.presets as Preset[];

export function presetToForm(values: Payload): FormState {
  const form = {} as FormState;
  for (const name of FIELDS) {
    const value = values[name];
    if (name === "reminder_sent") form.reminder_sent = Boolean(value);
    else (form as Record<string, string>)[name] = value === null || value === undefined ? "" : String(value);
  }
  return form;
}

export const DEFAULT_FORM: FormState = presetToForm(PRESETS[0].values);

/** Turn the form into the exact API body, or field errors. Numbers are sent as JSON numbers, never strings. */
export function buildRequest(form: FormState): { payload: Payload | null; errors: Partial<Record<FieldName, string>> } {
  const errors: Partial<Record<FieldName, string>> = {};
  const payload = {} as Payload;
  for (const name of FIELDS) {
    const spec = SCHEMA[name];
    if (spec.type === "boolean") { payload[name] = form.reminder_sent; continue; }
    const raw = (form as Record<string, string>)[name].trim();
    if (spec.type === "category") {
      if (!spec.values.includes(raw)) errors[name] = "Choose one of the options.";
      else payload[name] = raw;
      continue;
    }
    if (raw === "") {
      if (spec.type === "number" && spec.nullable) { payload[name] = null; continue; }
      errors[name] = "Required.";
      continue;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) { errors[name] = "Enter a number."; continue; }
    if (spec.type === "integer" && !Number.isInteger(value)) { errors[name] = "Enter a whole number."; continue; }
    if (value < spec.min || value > spec.max) { errors[name] = `Must be between ${spec.min} and ${spec.max}.`; continue; }
    payload[name] = value;
  }
  for (const name of FIELDS) {
    const spec = SCHEMA[name];
    if (spec.type === "integer" && spec.at_most && !errors[name] && !errors[spec.at_most as FieldName]) {
      const limitField = spec.at_most as FieldName;
      if ((payload[name] as number) > (payload[limitField] as number)) {
        errors[name] = `Cannot be more than ${LABELS[limitField].toLowerCase()} (${payload[limitField]}).`;
      }
    }
  }
  return Object.keys(errors).length ? { payload: null, errors } : { payload, errors };
}

export const percent = (x: number) => `${(100 * x).toFixed(1)}%`;

/** Everything the result card says, in plain words. Kept here so a test can scan it for clinical wording. */
export function describe(response: PredictionResponse) {
  const p = response.prediction;
  return {
    headline: p.suggested_action_label,
    chance: `${percent(p.no_show_probability)} estimated chance this appointment is missed`,
    comparison: `Average across the synthetic training data: ${percent(p.average_no_show_rate)}. ` +
      `An extra reminder is suggested from ${percent(p.decision_threshold)} upwards.`,
    meaning: "This only suggests whether to send an extra reminder. It does not describe anyone's health.",
    version: `Model ${response.model_version}`,
    disclaimer: response.disclaimer,
  };
}

export type ErrorView =
  | { kind: "fields"; message: string; fields: Partial<Record<string, string>> }
  | { kind: "unavailable" | "throttled" | "too_large" | "network" | "unknown"; message: string }
  | { kind: "signed_out" };

/** Map any failure to what the page shows. The form keeps its values in every case. */
export function errorView(err: unknown): ErrorView {
  if (!(err instanceof ApiError)) {
    return { kind: "network", message: "Could not reach the server. Check your connection and try again." };
  }
  if (err.status === 401 || err.status === 403) return { kind: "signed_out" };
  if (err.status === 400) {
    return { kind: "fields", message: "Some values were not accepted. See the highlighted fields.", fields: err.fieldErrors };
  }
  if (err.status === 413) return { kind: "too_large", message: "The request was too large." };
  if (err.status === 429) {
    const wait = Number((err.details as Record<string, unknown>).retry_after_seconds);
    return { kind: "throttled", message: `Too many requests. Try again in ${Number.isFinite(wait) ? wait : "a few"} seconds.` };
  }
  if (err.status === 503) {
    return { kind: "unavailable", message: "The estimate service is temporarily unavailable. Try again later." };
  }
  return { kind: "unknown", message: "Something went wrong. Try again." };
}
