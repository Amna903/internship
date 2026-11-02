// Week 5 Step 5: conversation state and the follow-up request shape, without a browser or backend.
import { beforeEach, expect, test } from "vitest";
import { ApiError, AskResponse, assistantApi } from "@/lib/api";
import { NEW_CONVERSATION, afterAnswer, conversationEnded } from "@/lib/conversation";

let bodies: unknown[] = [];
(globalThis as any).document = { cookie: "csrftoken=t" };
globalThis.fetch = ((_url: string, init: RequestInit) => {
  bodies.push(JSON.parse(String(init.body)));
  return Promise.resolve(new Response(JSON.stringify({ history: "signed" }), { status: 200 }));
}) as typeof fetch;
beforeEach(() => {
  bodies = [];
});

const result = (history: string) => ({ history }) as AskResponse;

test("a first question sends no history, exactly as in Week 4", async () => {
  await assistantApi.ask("How long do refunds take?");
  expect(bodies).toEqual([{ question: "How long do refunds take?" }]);
});

test("a follow-up sends back the signed history", async () => {
  await assistantApi.ask("And at the front desk?", "blob");
  expect(bodies).toEqual([{ question: "And at the front desk?", history: "blob" }]);
});

test("each answer appends a turn and replaces the history", () => {
  const one = afterAnswer(NEW_CONVERSATION, "q1", result("h1"));
  const two = afterAnswer(one, "q2", result("h2"));
  expect(two.turns.map((t) => t.question)).toEqual(["q1", "q2"]);
  expect(two.history).toBe("h2");
  expect(NEW_CONVERSATION).toEqual({ turns: [], history: null }); // never mutated
});

test("invalid history and the conversation limit end the conversation; other errors don't", () => {
  expect(conversationEnded(new ApiError(400, "invalid_history", "x"))).toMatch(/can't be continued/);
  expect(conversationEnded(new ApiError(400, "conversation_limit", "x"))).toMatch(/reached its limit/);
  expect(conversationEnded(new ApiError(400, "invalid_question", "x"))).toBeNull();
  expect(conversationEnded(new ApiError(502, "assistant_invalid_output", "x"))).toBeNull();
  expect(conversationEnded(new Error("network"))).toBeNull();
});

test("the conversation module never touches browser storage", async () => {
  const src = await import("node:fs").then(
    (fs) => fs.readFileSync("lib/conversation.ts", "utf8") + fs.readFileSync("app/admin/assistant/page.tsx", "utf8"),
  );
  expect(src.replace(/\/\/.*$/gm, "")).not.toMatch(/localStorage|sessionStorage|indexedDB/);
});
