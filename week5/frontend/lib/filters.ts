/**
 * Directory filters. The URL query string is the single source of truth for filter state:
 * parse it on the server to render results, write it from the client when a control changes.
 * Everything here is pure so it can run on either side and be unit-tested.
 */
import {
  DAYS, VISIT_TYPES, locations, specialtyName, specialties, type Day, type Professional, type VisitType,
} from "@/lib/professionals";

export const SORTS = {
  name: "Name (A–Z)",
  fee_asc: "Fee: low to high",
  fee_desc: "Fee: high to low",
  experience: "Most experienced",
} as const;
export type Sort = keyof typeof SORTS;

/** Fee caps offered in the UI. Any positive value in the URL is still honoured. */
export const FEE_CAPS = [2000, 3000, 4000, 5000] as const;

export type Filters = {
  q: string;
  specialties: string[]; // multi-select: match any
  location: string; // "" = any
  visit: VisitType | "";
  day: Day | "";
  maxFee: number | null;
  sort: Sort;
};

export const EMPTY_FILTERS: Filters = { q: "", specialties: [], location: "", visit: "", day: "", maxFee: null, sort: "name" };

type Params = Record<string, string | string[] | undefined>;
const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? "";
const oneOf = <T extends string>(v: string, allowed: readonly T[]): T | "" => ((allowed as readonly string[]).includes(v) ? (v as T) : "");

/** Unknown or malformed values are dropped rather than trusted: a hand-edited URL can't break the page. */
export function parseFilters(params: Params): Filters {
  const specialtyIds = specialties.map((s) => s.id);
  const fee = Number.parseInt(first(params.maxFee), 10);
  const sort = first(params.sort);
  return {
    q: first(params.q).trim().slice(0, 80),
    specialties: [...new Set(first(params.specialty).split(","))].filter((s) => specialtyIds.includes(s)),
    location: oneOf(first(params.location), locations.map((l) => l.id)),
    visit: oneOf(first(params.visit), VISIT_TYPES),
    day: oneOf(first(params.day), DAYS),
    maxFee: Number.isFinite(fee) && fee > 0 ? fee : null,
    sort: sort in SORTS ? (sort as Sort) : "name",
  };
}

/** Inverse of parseFilters. Defaults are omitted so the URL stays short and shareable. */
export function toSearchParams(f: Filters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.specialties.length) p.set("specialty", f.specialties.join(","));
  if (f.location) p.set("location", f.location);
  if (f.visit) p.set("visit", f.visit);
  if (f.day) p.set("day", f.day);
  if (f.maxFee) p.set("maxFee", String(f.maxFee));
  if (f.sort !== "name") p.set("sort", f.sort);
  return p;
}

export const activeFilterCount = (f: Filters) =>
  [f.q.trim(), f.specialties.length, f.location, f.visit, f.day, f.maxFee].filter(Boolean).length;

function matches(p: Professional, f: Filters): boolean {
  if (f.specialties.length && !f.specialties.includes(p.specialtyId)) return false;
  if (f.location && p.locationId !== f.location) return false;
  if (f.visit && !p.visitTypes.includes(f.visit)) return false;
  if (f.day && !p.availability[f.day]?.length) return false;
  if (f.maxFee && p.feePkr > f.maxFee) return false;
  if (f.q) {
    const haystack = [p.name, p.title, p.clinic, p.bio, specialtyName(p.specialtyId), ...p.languages].join(" ").toLowerCase();
    // Every word must appear somewhere, so "urdu physio" narrows instead of widening.
    if (!f.q.toLowerCase().split(/\s+/).every((word) => haystack.includes(word))) return false;
  }
  return true;
}

const comparators: Record<Sort, (a: Professional, b: Professional) => number> = {
  name: (a, b) => a.name.localeCompare(b.name),
  fee_asc: (a, b) => a.feePkr - b.feePkr || a.name.localeCompare(b.name),
  fee_desc: (a, b) => b.feePkr - a.feePkr || a.name.localeCompare(b.name),
  experience: (a, b) => b.yearsExperience - a.yearsExperience || a.name.localeCompare(b.name),
};

export function applyFilters(list: readonly Professional[], f: Filters): Professional[] {
  return list.filter((p) => matches(p, f)).sort(comparators[f.sort]);
}
