import { describe, expect, it } from "vitest";
import { NOTE_MAX, emptyDraft, firstInvalidStep, isDraft, validateStep, type Draft } from "@/lib/appointment";
import { getProfessional } from "@/lib/professionals";

const ayesha = getProfessional("ayesha-siddiqui")!; // in person + video; Mon/Wed/Sat
const omar = getProfessional("omar-farooq")!; // in person only

const valid = (): Draft => ({
  ...emptyDraft(ayesha),
  visitType: "video",
  reason: "first_visit",
  day: "mon",
  time: "10:00",
  fullName: "Test Person",
  email: "test@example.test",
  acknowledged: true,
});

describe("emptyDraft", () => {
  it("pre-selects the visit type when only one is offered", () => {
    expect(emptyDraft(omar).visitType).toBe("in_person");
    expect(emptyDraft(ayesha).visitType).toBe("");
  });
});

describe("validateStep", () => {
  it("accepts a complete draft on every step", () => {
    for (const step of [0, 1, 2, 3]) expect(validateStep(step, valid(), ayesha)).toEqual({});
  });

  it("step 1: requires visit type and reason, limits note length", () => {
    const e = validateStep(0, { ...valid(), visitType: "", reason: "", note: "x".repeat(NOTE_MAX + 1) }, ayesha);
    expect(Object.keys(e).sort()).toEqual(["note", "reason", "visitType"]);
  });

  it("step 1: rejects a visit type the professional doesn't offer", () => {
    expect(validateStep(0, { ...valid(), visitType: "video" }, omar).visitType).toMatch(/doesn't offer/);
  });

  it("step 2: rejects a day or time outside availability", () => {
    expect(validateStep(1, { ...valid(), day: "tue" }, ayesha).day).toMatch(/isn't available/);
    expect(validateStep(1, { ...valid(), time: "23:00" }, ayesha).time).toMatch(/isn't available/);
  });

  it("step 3: validates name and email; phone required only when chosen", () => {
    const e = validateStep(2, { ...valid(), fullName: " ", email: "nope" }, ayesha);
    expect(Object.keys(e).sort()).toEqual(["email", "fullName"]);
    expect(validateStep(2, { ...valid(), contactMethod: "phone" }, ayesha).phone).toMatch(/phone number/);
    expect(validateStep(2, { ...valid(), contactMethod: "phone", phone: "+92 300 1234567" }, ayesha)).toEqual({});
    expect(validateStep(2, { ...valid(), phone: "abc" }, ayesha).phone).toMatch(/doesn't look right/);
  });

  it("step 4: requires the demo acknowledgement", () => {
    expect(validateStep(3, { ...valid(), acknowledged: false }, ayesha).acknowledged).toBeTruthy();
  });
});

describe("restored drafts", () => {
  it("isDraft rejects corrupted storage", () => {
    expect(isDraft(valid())).toBe(true);
    expect(isDraft(null)).toBe(false);
    expect(isDraft({ ...valid(), step: 99 })).toBe(false);
    expect(isDraft({ ...valid(), day: "funday" })).toBe(false);
    expect(isDraft({ ...valid(), email: 42 })).toBe(false);
  });

  it("firstInvalidStep rewinds past steps that are no longer valid", () => {
    expect(firstInvalidStep({ ...valid(), step: 3 }, ayesha)).toBe(3);
    expect(firstInvalidStep({ ...valid(), step: 3, time: "" }, ayesha)).toBe(1);
  });
});
