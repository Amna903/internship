/**
 * Appointment *request* form model (no booking happens: Week 2 is frontend-only).
 * Steps, draft shape and per-step validation live here, separate from the UI, so the rules are
 * unit-tested and the component only renders state.
 */
import { DAYS, VISIT_TYPES, type Day, type Professional, type VisitType } from "@/lib/professionals";

export const STEPS = [
  { id: "visit", label: "Visit" },
  { id: "time", label: "Time" },
  { id: "details", label: "Your details" },
  { id: "review", label: "Review" },
] as const;
export type StepId = (typeof STEPS)[number]["id"];

export const REASONS = {
  first_visit: "First consultation",
  follow_up: "Follow-up",
  wellness_plan: "Wellness plan review",
  other: "Something else",
} as const;
export type Reason = keyof typeof REASONS;

export const CONTACT_METHODS = { email: "Email", phone: "Phone call" } as const;
export type ContactMethod = keyof typeof CONTACT_METHODS;

export type Draft = {
  step: number;
  visitType: VisitType | "";
  reason: Reason | "";
  note: string;
  day: Day | "";
  time: string;
  fullName: string;
  email: string;
  phone: string;
  contactMethod: ContactMethod;
  acknowledged: boolean;
};

export const NOTE_MAX = 300;

export function emptyDraft(p: Professional): Draft {
  return {
    step: 0,
    // Pre-select when there is only one option: fewer clicks, nothing to get wrong.
    visitType: p.visitTypes.length === 1 ? p.visitTypes[0] : "",
    reason: "",
    note: "",
    day: "",
    time: "",
    fullName: "",
    email: "",
    phone: "",
    contactMethod: "email",
    acknowledged: false,
  };
}

/** Shape check for whatever comes back out of localStorage (it may be stale or hand-edited). */
export function isDraft(v: unknown): v is Draft {
  if (typeof v !== "object" || v === null) return false;
  const d = v as Record<string, unknown>;
  return (
    Number.isInteger(d.step) && (d.step as number) >= 0 && (d.step as number) < STEPS.length &&
    (d.visitType === "" || (VISIT_TYPES as readonly unknown[]).includes(d.visitType)) &&
    (d.reason === "" || (typeof d.reason === "string" && d.reason in REASONS)) &&
    (d.day === "" || (DAYS as readonly unknown[]).includes(d.day)) &&
    ["note", "time", "fullName", "email", "phone"].every((k) => typeof d[k] === "string") &&
    typeof d.contactMethod === "string" && d.contactMethod in CONTACT_METHODS &&
    typeof d.acknowledged === "boolean"
  );
}

export type Errors = Partial<Record<keyof Draft, string>>;

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE = /^\+?[0-9][0-9\s-]{6,18}$/;

export function validateStep(step: number, d: Draft, p: Professional): Errors {
  const e: Errors = {};
  switch (STEPS[step]?.id) {
    case "visit":
      if (!d.visitType) e.visitType = "Choose how you'd like to meet.";
      else if (!p.visitTypes.includes(d.visitType)) e.visitType = "This professional doesn't offer that visit type.";
      if (!d.reason) e.reason = "Choose a reason for the visit.";
      if (d.note.length > NOTE_MAX) e.note = `Keep the note under ${NOTE_MAX} characters.`;
      break;
    case "time":
      if (!d.day) e.day = "Choose a day.";
      else if (!p.availability[d.day]?.length) e.day = "This professional isn't available that day.";
      if (!d.time) e.time = "Choose a time.";
      else if (d.day && !p.availability[d.day]?.includes(d.time)) e.time = "That time isn't available on the chosen day.";
      break;
    case "details":
      if (d.fullName.trim().length < 2) e.fullName = "Enter your name (at least 2 characters).";
      if (!EMAIL.test(d.email.trim())) e.email = "Enter a valid email address, like name@example.com.";
      if (d.contactMethod === "phone" && !PHONE.test(d.phone.trim())) e.phone = "Enter a phone number so we can call you.";
      else if (d.phone.trim() && !PHONE.test(d.phone.trim())) e.phone = "That phone number doesn't look right.";
      break;
    case "review":
      if (!d.acknowledged) e.acknowledged = "Please confirm you understand this is a demo request.";
      break;
  }
  return e;
}

/** First step that still has errors, so a restored draft can't skip past invalid data. */
export function firstInvalidStep(d: Draft, p: Professional): number {
  for (let i = 0; i < d.step; i++) if (Object.keys(validateStep(i, d, p)).length) return i;
  return d.step;
}
