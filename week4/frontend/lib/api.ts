// Thin fetch wrapper. All auth lives in HttpOnly cookies the browser manages; this file never sees
// or stores a token. It only (a) echoes the CSRF cookie in a header and (b) retries once after a
// silent refresh when the short-lived user access cookie has expired. Concurrent 401s share a single
// in-flight refresh, because refresh tokens rotate: a second parallel refresh would present an
// already-blacklisted token and log the user out.

import type { Payload, PredictionResponse } from "./prediction";

export type Role = "user" | "admin";
export interface UserSummary { id: number; email: string; role: Role }

export type CompletionStatus = "complete" | "incomplete";
export interface Completion { status: CompletionStatus; percent: number; missing_sections: string[] }

export interface Profile {
  email: string;
  full_name: string;
  date_of_birth: string | null;
  age_range: string;
  contact_preference: "email" | "phone" | "sms" | "none";
  wellness_goals: string[];
  allergies: string[];
  emergency_contact_name: string;
  emergency_contact_phone: string;
  emergency_contact_relationship: string;
  lifestyle_notes: string;
  status: "active" | "deactivated";
  completion: Completion;
  created_at: string;
  updated_at: string;
}

export interface AdminProfileRow {
  id: number; user_id: number; email: string; full_name: string; age_range: string;
  contact_preference: string; status: "active" | "deactivated"; completion_status: CompletionStatus; created_at: string;
}
export interface AuditEvent {
  id: number; created_at: string; action: string; action_label: string; actor_email: string | null;
  actor_role: "user" | "admin" | "anonymous"; target_email: string | null; profile_id: number | null; changed_fields: string[]; request_id: string;
}
export interface AdminProfileDetail extends Profile {
  id: number; user_id: number; deactivated_at: string | null; account_active: boolean; last_login: string | null;
}
export interface Page<T> { count: number; next: string | null; previous: string | null; results: T[] }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, string[] | string> = {}) {
    super(message);
  }
  /** Field errors flattened to "field: message" lines for display. */
  get fieldErrors(): Record<string, string> {
    return Object.fromEntries(
      Object.entries(this.details).map(([k, v]) => [k, Array.isArray(v) ? v.join(" ") : String(v)]),
    );
  }
}

function readCookie(name: string): string {
  const match = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return match ? decodeURIComponent(match.split("=")[1]) : "";
}

async function ensureCsrf(): Promise<string> {
  let token = readCookie("csrftoken");
  if (!token) {
    await fetch("/api/auth/csrf/", { credentials: "same-origin" });
    token = readCookie("csrftoken");
  }
  return token;
}

async function raw(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = await ensureCsrf();
  return fetch(path, { method, headers, credentials: "same-origin", signal, body: body === undefined ? undefined : JSON.stringify(body) });
}

let refreshInFlight: Promise<boolean> | null = null;

/** Rotate the user cookies. Every caller that arrives while a refresh is running awaits the same one. */
export function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = raw("POST", "/api/auth/user/refresh/")
      .then((r) => r.ok, () => false)
      .finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON (proxy error page) */ }
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "http_error", err?.message ?? `Request failed (${res.status})`, err?.details ?? {});
  }
  return data as T;
}

export interface RequestOpts {
  /** Standard-user flow only: on 401, wait for the shared refresh and retry exactly once. */
  refresh?: boolean;
  /** Abort the request (e.g. a superseded search). Rejects with a DOMException named "AbortError". */
  signal?: AbortSignal;
}

export async function api<T>(method: string, path: string, body?: unknown, opts: RequestOpts = {}): Promise<T> {
  let res = await raw(method, path, body, opts.signal);
  if (res.status === 401 && opts.refresh && (await refreshSession())) {
    res = await raw(method, path, body, opts.signal);
  }
  return parse<T>(res);
}

export const isAbort = (err: unknown) => err instanceof DOMException && err.name === "AbortError";

// ---- standard user (JWT cookies) ----
export const userApi = {
  signup: (name: string, email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/auth/signup/", { name, email, password }),
  login: (email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/auth/user/login/", { email, password }),
  logout: () => api<{ detail: string }>("POST", "/api/auth/user/logout/"),
  getProfile: () => api<Profile>("GET", "/api/profiles/me/", undefined, { refresh: true }),
  updateProfile: (patch: Partial<Profile>) => api<Profile>("PATCH", "/api/profiles/me/", patch, { refresh: true }),
  createProfile: (full_name: string) => api<Profile>("POST", "/api/profiles/me/", { full_name }, { refresh: true }),
  deleteProfile: () => api<null>("DELETE", "/api/profiles/me/", undefined, { refresh: true }),
};

// ---- admin (server-side session cookie) ----
export const adminApi = {
  login: (email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/admin/login/", { email, password }),
  logout: () => api<{ detail: string }>("POST", "/api/admin/logout/"),
  me: () => api<{ user: UserSummary }>("GET", "/api/admin/me/"),
  list: (params: Record<string, string>, signal?: AbortSignal) =>
    api<Page<AdminProfileRow>>("GET", "/api/admin/profiles/?" + new URLSearchParams(params), undefined, { signal }),
  detail: (id: string | number) => api<AdminProfileDetail>("GET", `/api/admin/profiles/${id}/`),
  setStatus: (id: string | number, action: "activate" | "deactivate") => api<AdminProfileDetail>("POST", `/api/admin/profiles/${id}/${action}/`),
  auditEvents: (params: Record<string, string>, signal?: AbortSignal) =>
    api<Page<AuditEvent>>("GET", "/api/admin/audit-events/?" + new URLSearchParams(params), undefined, { signal }),
};

export const SECTION_LABELS: Record<string, string> = {
  demographics: "Demographics (name and date of birth or age range)",
  emergency_contact: "Emergency contact (name, relationship and phone)",
  wellness_preferences: "Wellness preferences (contact preference and at least one goal)",
};

// ---- Week 3: no-show estimate (admin session; same CSRF and error handling as above) ----

export interface ModelCard {
  model_version: string;
  task: string;
  estimator: string;
  disclaimer: string;
  inputs_note: string;
  decision: { threshold: number; rule: string };
  metrics: { validation: Record<string, number>; test: Record<string, number> };
  training_data: { sha256: string; average_no_show_rate: number; split_rows: Record<string, number> };
  artifact_sha256: string;
}

export const predictionApi = {
  predict: (input: Payload) => api<PredictionResponse>("POST", "/api/v1/predictions/no-show/", input),
  model: () => api<ModelCard>("GET", "/api/v1/models/no-show/"),
};

// ---- Week 4: clusters and the policy assistant (admin session) ----

export interface ClusterSummary {
  cluster: number; size: number; share: number; description: string;
  most_common_planted_habit?: { habit: string; share: number };
}

export interface MethodRow {
  method: string; real_structure_found: boolean; real_silhouette: number; real_baseline_bar: number;
  real_chosen_k: number; control_chosen_k: number; control_ari: number;
}

export interface ClusterView {
  results_version: string;
  disclaimer: string;
  control: {
    label: string; patients: number; k: number; pca_variance: number[]; ari: number; recovery: string;
    clusters: ClusterSummary[]; points: { x: number; y: number; cluster: number; planted_habit: string }[];
  };
  real: {
    patients: number; k: number; silhouette: number; baseline_bar: number; appointments_share_of_split: number;
    structure_found: Record<string, boolean>; misleading_clusters: ClusterSummary[];
  };
  methods: MethodRow[];
}

export interface AssistantStatus {
  provider: string; model: string; embedder: string; temperature: number; data_policy: string;
  limits: { question_chars: number };
}

export interface Citation { passage_id: string; quote: string; source: string }

export interface AskResponse {
  status: "answered" | "insufficient_information" | "refused";
  answer: string;
  citations: Citation[];
  reason: string | null;
  usage: { prompt_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number;
           hosted_equivalent_usd: number; note: string } | null;
  model: string;
  model_called: boolean;
  settings: { floor: number; top_k: number; groundedness_threshold: number };
  disclaimer: string;
}

export const clustersApi = {
  view: () => api<ClusterView>("GET", "/api/v1/clusters/"),
};

export const assistantApi = {
  status: () => api<AssistantStatus>("GET", "/api/v1/assistant/status/"),
  ask: (question: string) => api<AskResponse>("POST", "/api/v1/assistant/ask/", { question }),
};
