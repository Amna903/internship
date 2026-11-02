import type { AgentStep } from "./api";

/** A fresh Idempotency-Key for confirming one action (8-100 letters, digits, '-' or '_'). */
export function newIdempotencyKey(random: () => string = () => crypto.randomUUID()): string {
  return `confirm-${random()}`;
}

/** Keys per action: a retried click on the same card reuses its key, so the server replays, never double-books. */
export class ConfirmKeys {
  private keys = new Map<string, string>();
  constructor(private make: () => string = () => newIdempotencyKey()) {}
  for(actionId: string): string {
    let key = this.keys.get(actionId);
    if (!key) { key = this.make(); this.keys.set(actionId, key); }
    return key;
  }
}

/** One readable line per trace step: ids and codes only (the server never sends free text in steps). */
export function formatStep(s: AgentStep): string {
  const parts = [`${s.n}. ${s.state}`];
  if (s.tool) parts.push(s.tool);
  if (s.code) parts.push(`→ ${s.code}`);
  if (typeof s.seconds === "number") parts.push(`(${Math.round(s.seconds * 1000)} ms)`);
  return parts.join(" ");
}

export const STOP_REASONS: Record<string, string> = {
  steps: "Stopped: the 4-tool-call limit was reached.",
  tokens: "Stopped: the 8,000-token budget was used up.",
  time: "Stopped: the 60-second limit was reached.",
  tool_failed: "Stopped: a tool failed again after one retry.",
  model_unavailable: "The model is unavailable right now.",
  invalid_output: "The model's reply could not be read, so nothing is shown.",
  medical: "Not answered: medical question.",
};
