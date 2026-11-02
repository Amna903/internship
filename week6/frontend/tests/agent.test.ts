import { describe, expect, it } from "vitest";
import { ConfirmKeys, formatStep, newIdempotencyKey } from "../lib/agent";

describe("idempotency keys", () => {
  it("match the server's format", () => {
    expect(newIdempotencyKey()).toMatch(/^[A-Za-z0-9_-]{8,100}$/);
  });
  it("are reused for the same action and fresh for another", () => {
    let n = 0;
    const keys = new ConfirmKeys(() => `k-${++n}-abcdefgh`);
    expect(keys.for("a")).toBe(keys.for("a"));
    expect(keys.for("b")).not.toBe(keys.for("a"));
  });
});

describe("formatStep", () => {
  it("shows state, tool, code and time", () => {
    expect(formatStep({ n: 2, state: "execute", tool: "check_availability", code: "ok", seconds: 0.0124 })).toBe(
      "2. execute check_availability → ok (12 ms)",
    );
  });
  it("omits what is missing", () => {
    expect(formatStep({ n: 1, state: "respond", code: "answer" })).toBe("1. respond → answer");
  });
});
