import { describe, expect, it } from "vitest";
import {
  EMPTY_FILTERS,
  activeFilterCount,
  applyFilters,
  parseFilters,
  toSearchParams,
  type Filters,
} from "@/lib/filters";
import { professionals } from "@/lib/professionals";

const run = (patch: Partial<Filters>) => applyFilters(professionals, { ...EMPTY_FILTERS, ...patch });
const ids = (list: { id: string }[]) => list.map((p) => p.id);

describe("parseFilters", () => {
  it("returns defaults for an empty query", () => {
    expect(parseFilters({})).toEqual(EMPTY_FILTERS);
  });

  it("drops unknown or malformed values instead of trusting the URL", () => {
    const f = parseFilters({
      specialty: "nutrition,astrology",
      location: "atlantis",
      visit: "teleport",
      day: "funday",
      maxFee: "-3",
      sort: "random",
    });
    expect(f).toEqual({ ...EMPTY_FILTERS, specialties: ["nutrition"] });
  });

  it("takes the first value when a key repeats", () => {
    expect(parseFilters({ location: ["lahore", "karachi"] }).location).toBe("lahore");
  });

  it("round-trips through the query string", () => {
    const f: Filters = {
      q: "urdu",
      specialties: ["nutrition", "fitness"],
      location: "lahore",
      visit: "video",
      day: "mon",
      maxFee: 4000,
      sort: "fee_asc",
    };
    expect(parseFilters(Object.fromEntries(toSearchParams(f)))).toEqual(f);
  });

  it("keeps the URL minimal when nothing is set", () => {
    expect(toSearchParams(EMPTY_FILTERS).toString()).toBe("");
  });
});

describe("applyFilters", () => {
  it("returns everyone, sorted by name, with no filters", () => {
    const all = run({});
    expect(all).toHaveLength(professionals.length);
    expect(ids(all)).toEqual(ids([...professionals].sort((a, b) => a.name.localeCompare(b.name))));
  });

  it("matches any of several specialties", () => {
    const r = run({ specialties: ["sleep", "fitness"] });
    expect(r.length).toBeGreaterThan(0);
    expect(r.every((p) => ["sleep", "fitness"].includes(p.specialtyId))).toBe(true);
  });

  it("combines filters with AND", () => {
    const r = run({ location: "lahore", visit: "video", maxFee: 3500 });
    expect(r.length).toBeGreaterThan(0);
    for (const p of r) {
      expect(p.locationId).toBe("lahore");
      expect(p.visitTypes).toContain("video");
      expect(p.feePkr).toBeLessThanOrEqual(3500);
    }
  });

  it("filters by availability day", () => {
    expect(run({ day: "sun" }).every((p) => (p.availability.sun?.length ?? 0) > 0)).toBe(true);
  });

  it("requires every search word to match (narrows, not widens)", () => {
    const one = run({ q: "urdu" }).length;
    const two = run({ q: "urdu physiotherapist" }).length;
    expect(two).toBeGreaterThan(0);
    expect(two).toBeLessThan(one);
  });

  it("searches specialty names too, case-insensitively", () => {
    expect(ids(run({ q: "SLEEP coaching" }))).toEqual(expect.arrayContaining(["hina-rauf"]));
  });

  it("returns an empty list (empty state) for impossible combinations", () => {
    expect(run({ location: "online", visit: "in_person" })).toEqual([]);
  });

  it("sorts by fee both ways and by experience", () => {
    const asc = run({ sort: "fee_asc" }).map((p) => p.feePkr);
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    const desc = run({ sort: "fee_desc" }).map((p) => p.feePkr);
    expect(desc).toEqual([...desc].sort((a, b) => b - a));
    const exp = run({ sort: "experience" }).map((p) => p.yearsExperience);
    expect(exp).toEqual([...exp].sort((a, b) => b - a));
  });

  it("does not mutate the source list", () => {
    const before = ids(professionals);
    run({ sort: "fee_desc" });
    expect(ids(professionals)).toEqual(before);
  });
});

it("counts active filters (sort is not a filter)", () => {
  expect(activeFilterCount({ ...EMPTY_FILTERS, sort: "fee_desc" })).toBe(0);
  expect(activeFilterCount({ ...EMPTY_FILTERS, q: "x", specialties: ["sleep"], maxFee: 2000 })).toBe(3);
});
