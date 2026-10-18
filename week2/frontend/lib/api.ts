// Thin fetch wrapper. All auth lives in HttpOnly cookies the browser manages; this file never sees
// or stores a token. It only (a) echoes the CSRF cookie in a header and (b) retries once after a
// silent refresh when the short-lived user access cookie has expired.

export type Role = "user" | "admin";
export interface UserSummary { id: number; email: string; role: Role }

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
  created_at: string;
  updated_at: string;
}

export interface AdminProfileRow {
  id: number; user_id: number; email: string; full_name: string; age_range: string;
  contact_preference: string; status: "active" | "deactivated"; created_at: string;
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

async function raw(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRFToken"] = await ensureCsrf();
  return fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : JSON.stringify(body) });
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

/** `refresh: true` is for the standard-user flow only: on 401, rotate cookies once and retry. */
export async function api<T>(method: string, path: string, body?: unknown, opts: { refresh?: boolean } = {}): Promise<T> {
  let res = await raw(method, path, body);
  if (res.status === 401 && opts.refresh) {
    const refreshed = await raw("POST", "/api/auth/user/refresh/");
    if (refreshed.ok) res = await raw(method, path, body);
  }
  return parse<T>(res);
}

// ---- standard user (JWT cookies) ----
export const userApi = {
  signup: (name: string, email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/auth/signup/", { name, email, password }),
  login: (email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/auth/user/login/", { email, password }),
  logout: () => api<{ detail: string }>("POST", "/api/auth/user/logout/"),
  getProfile: () => api<Profile>("GET", "/api/profiles/me/", undefined, { refresh: true }),
  updateProfile: (patch: Partial<Profile>) => api<Profile>("PATCH", "/api/profiles/me/", patch, { refresh: true }),
};

// ---- admin (server-side session cookie) ----
export const adminApi = {
  login: (email: string, password: string) => api<{ user: UserSummary }>("POST", "/api/admin/login/", { email, password }),
  logout: () => api<{ detail: string }>("POST", "/api/admin/logout/"),
  me: () => api<{ user: UserSummary }>("GET", "/api/admin/me/"),
  list: (params: Record<string, string>) => api<Page<AdminProfileRow>>("GET", "/api/admin/profiles/?" + new URLSearchParams(params)),
  detail: (id: string | number) => api<AdminProfileDetail>("GET", `/api/admin/profiles/${id}/`),
  setStatus: (id: string | number, action: "activate" | "deactivate") => api<AdminProfileDetail>("POST", `/api/admin/profiles/${id}/${action}/`),
};
