import { describe, expect, it } from "vitest";
import raw from "@/data/professionals.json";
import { availableDays, getProfessional, professionals, validateDirectory } from "@/lib/professionals";

const clone = () => structuredClone(raw) as typeof raw;

describe("data/professionals.json", () => {
  it("is valid", () => {
    expect(validateDirectory(raw)).toEqual([]);
  });

  it("has enough variety to exercise every filter", () => {
    expect(professionals.length).toBeGreaterThanOrEqual(12);
    expect(new Set(professionals.map((p) => p.specialtyId)).size).toBe(raw.specialties.length);
    expect(new Set(professionals.map((p) => p.locationId)).size).toBe(raw.locations.length);
  });
});

describe("validateDirectory catches broken data", () => {
  it("rejects a non-object root", () => {
    expect(validateDirectory(null)).toEqual(["root must be an object"]);
  });

  it("flags duplicate ids", () => {
    const d = clone();
    d.professionals[1].id = d.professionals[0].id;
    expect(validateDirectory(d).join()).toMatch(/duplicate id/);
  });

  it("flags references to unknown specialties and locations", () => {
    const d = clone();
    d.professionals[0].specialtyId = "astrology";
    d.professionals[0].locationId = "atlantis";
    const errors = validateDirectory(d).join("\n");
    expect(errors).toMatch(/unknown specialtyId "astrology"/);
    expect(errors).toMatch(/unknown locationId "atlantis"/);
  });

  it("flags bad fees, visit types and times", () => {
    const d = clone() as any;
    d.professionals[0].feePkr = -5;
    d.professionals[1].visitTypes = ["teleport"];
    d.professionals[2].availability = { mon: ["9am"] };
    d.professionals[3].availability = { funday: ["10:00"] };
    const errors = validateDirectory(d).join("\n");
    expect(errors).toMatch(/feePkr must be a positive integer/);
    expect(errors).toMatch(/visitTypes must be a non-empty subset/);
    expect(errors).toMatch(/HH:MM/);
    expect(errors).toMatch(/unknown day "funday"/);
  });

  it("enforces that online-only professionals can't offer in-person visits", () => {
    const d = clone();
    const online = d.professionals.find((p) => p.locationId === "online")!;
    online.visitTypes = ["in_person", "video"];
    expect(validateDirectory(d).join()).toMatch(/online-only professional cannot offer in-person/);
  });
});

describe("lookups", () => {
  it("returns undefined for unknown ids (drives the not-found page)", () => {
    expect(getProfessional("does-not-exist")).toBeUndefined();
    expect(getProfessional("ayesha-siddiqui")?.name).toBe("Ayesha Siddiqui");
  });

  it("lists available days in week order", () => {
    expect(availableDays(getProfessional("ayesha-siddiqui")!)).toEqual(["mon", "wed", "sat"]);
  });
});
