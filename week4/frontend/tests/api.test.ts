// Exercises lib/api.ts against a fake fetch: no browser, no backend.
import { beforeEach, expect, test } from "vitest";
import { api, ApiError, isAbort } from "@/lib/api";

type Handler = (url: string, init: RequestInit) => Promise<Response>;
let calls: string[] = [];
let handler: Handler;

(globalThis as any).document = { cookie: "csrftoken=t" };
globalThis.fetch = ((url: string, init: RequestInit) => { calls.push(`${init.method} ${url}`); return handler(url, init); }) as typeof fetch;

const json = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status });
const tick = () => new Promise((r) => setTimeout(r, 5));

beforeEach(() => { calls = []; });

test("concurrent 401s share one refresh, then every request retries once", async () => {
  let fresh = false;
  handler = async (url) => {
    if (url.endsWith("/refresh/")) { await tick(); fresh = true; return json(200); }
    return fresh ? json(200, { url }) : json(401);
  };
  const results = await Promise.all(["/a", "/b", "/c"].map((p) => api<{ url: string }>("GET", p, undefined, { refresh: true })));
  expect(results.map((r) => r.url)).toEqual(["/a", "/b", "/c"]);
  expect(calls.filter((c) => c.endsWith("/refresh/")).length).toBe(1);
  expect(calls.length).toBe(3 + 1 + 3);
});

test("a failed refresh fails every waiting request with the original 401, without retrying", async () => {
  handler = async (url) => (url.endsWith("/refresh/") ? (await tick(), json(401)) : json(401, { error: { code: "not_authenticated", message: "x" } }));
  const outcomes = await Promise.allSettled(["/a", "/b"].map((p) => api("GET", p, undefined, { refresh: true })));
  for (const o of outcomes) expect(o.status === "rejected" && o.reason instanceof ApiError && o.reason.status === 401).toBe(true);
  expect(calls.filter((c) => c.endsWith("/refresh/")).length).toBe(1);
  expect(calls.length).toBe(2 + 1);
});

test("a later refresh is not short-circuited by an earlier finished one", async () => {
  handler = async (url) => (url.endsWith("/refresh/") ? json(401) : json(401));
  await api("GET", "/a", undefined, { refresh: true }).catch(() => {});
  await api("GET", "/b", undefined, { refresh: true }).catch(() => {});
  expect(calls.filter((c) => c.endsWith("/refresh/")).length).toBe(2);
});

test("an aborted request rejects with AbortError instead of resolving stale data", async () => {
  handler = (_url, init) => new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve(json(200, { old: true })), 50);
    init.signal?.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("aborted", "AbortError")); });
  });
  const ctrl = new AbortController();
  const pending = api("GET", "/api/admin/profiles/?search=ol", undefined, { signal: ctrl.signal });
  ctrl.abort();
  await expect(pending.catch((err) => isAbort(err))).resolves.toBe(true);
});
