// Week 5 Step 5: the assistant conversation as plain state, so it can be tested without a browser.
// It lives in React state only: never localStorage or sessionStorage (Week 4's "question never stored in
// the browser" rule). The server signs the history, ties it to the signed-in admin and expires it after
// 30 minutes; the browser only carries it back.
import { ApiError, AskResponse } from "@/lib/api";

export interface ConversationTurn {
  question: string;
  result: AskResponse;
}

export interface Conversation {
  turns: ConversationTurn[];
  history: string | null; // the signed blob to send with the next question
}

export const NEW_CONVERSATION: Conversation = { turns: [], history: null };

export function afterAnswer(c: Conversation, question: string, result: AskResponse): Conversation {
  return { turns: [...c.turns, { question, result }], history: result.history };
}

/** A 400 that means this conversation can't go on: start a new one (and say why). */
export function conversationEnded(err: unknown): string | null {
  if (!(err instanceof ApiError) || err.status !== 400) return null;
  if (err.code === "invalid_history")
    return "This conversation can't be continued (it may have expired). A new conversation has been started.";
  if (err.code === "conversation_limit")
    return "This conversation has reached its limit. A new conversation has been started.";
  return null;
}
