// Run with `npm test`. Exercises lib/api.ts against a fake fetch: no browser, no backend.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { api, ApiError, isAbort } from "../lib/api.js";

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
  assert.deepEqual(results.map((r) => r.url), ["/a", "/b", "/c"]);
  assert.equal(calls.filter((c) => c.endsWith("/refresh/")).length, 1);
  assert.equal(calls.length, 3 + 1 + 3);
});

test("a failed refresh fails every waiting request with the original 401, without retrying", async () => {
  handler = async (url) => (url.endsWith("/refresh/") ? (await tick(), json(401)) : json(401, { error: { code: "not_authenticated", message: "x" } }));
  const outcomes = await Promise.allSettled(["/a", "/b"].map((p) => api("GET", p, undefined, { refresh: true })));
  for (const o of outcomes) assert.ok(o.status === "rejected" && o.reason instanceof ApiError && o.reason.status === 401);
  assert.equal(calls.filter((c) => c.endsWith("/refresh/")).length, 1);
  assert.equal(calls.length, 2 + 1);
});

test("a later refresh is not short-circuited by an earlier finished one", async () => {
  handler = async (url) => (url.endsWith("/refresh/") ? json(401) : json(401));
  await api("GET", "/a", undefined, { refresh: true }).catch(() => {});
  await api("GET", "/b", undefined, { refresh: true }).catch(() => {});
  assert.equal(calls.filter((c) => c.endsWith("/refresh/")).length, 2);
});

test("an aborted request rejects with AbortError instead of resolving stale data", async () => {
  handler = (_url, init) => new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve(json(200, { old: true })), 50);
    init.signal?.addEventListener("abort", () => { clearTimeout(t); reject(new DOMException("aborted", "AbortError")); });
  });
  const ctrl = new AbortController();
  const pending = api("GET", "/api/admin/profiles/?search=ol", undefined, { signal: ctrl.signal });
  ctrl.abort();
  await assert.rejects(pending, (err) => isAbort(err));
});
