/**
 * Typed access to data/professionals.json, the single source for the directory.
 *
 * The JSON is validated once at import time. A broken data file fails the build (every
 * professionals page imports this module during prerender) instead of rendering half a card.
 */
import raw from "@/data/professionals.json";

export const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
export type Day = (typeof DAYS)[number];
export const DAY_LABELS: Record<Day, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export const VISIT_TYPES = ["in_person", "video"] as const;
export type VisitType = (typeof VISIT_TYPES)[number];
export const VISIT_LABELS: Record<VisitType, string> = { in_person: "In person", video: "Video call" };

export type Specialty = { id: string; name: string };
export type Location = { id: string; name: string };
export type Professional = {
  id: string;
  name: string;
  title: string;
  specialtyId: string;
  locationId: string;
  clinic: string;
  languages: string[];
  yearsExperience: number;
  feePkr: number;
  visitTypes: VisitType[];
  availability: Partial<Record<Day, string[]>>;
  bio: string;
};
export type Directory = { specialties: Specialty[]; locations: Location[]; professionals: Professional[] };

const ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const isStrList = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");

/** Returns every problem found (empty array = valid). Exported so tests can feed it bad data. */
export function validateDirectory(data: unknown): string[] {
  const errors: string[] = [];
  if (!isObj(data)) return ["root must be an object"];
  const { specialties, locations, professionals } = data;

  const ids = (list: unknown, name: string): Set<string> => {
    const seen = new Set<string>();
    if (!Array.isArray(list) || list.length === 0) {
      errors.push(`${name} must be a non-empty array`);
      return seen;
    }
    list.forEach((item, i) => {
      if (
        !isObj(item) ||
        typeof item.id !== "string" ||
        !ID.test(item.id) ||
        typeof item.name !== "string" ||
        !item.name.trim()
      ) {
        errors.push(`${name}[${i}] needs a slug id and a name`);
      } else if (seen.has(item.id)) errors.push(`${name}[${i}] duplicate id "${item.id}"`);
      else seen.add(item.id);
    });
    return seen;
  };
  const specialtyIds = ids(specialties, "specialties");
  const locationIds = ids(locations, "locations");
  const proIds = ids(professionals, "professionals");
  if (!Array.isArray(professionals)) return errors;

  professionals.forEach((p, i) => {
    if (!isObj(p)) return;
    const at = `professionals[${i}] (${String(p.id)})`;
    for (const key of ["title", "clinic", "bio"]) {
      if (typeof p[key] !== "string" || !(p[key] as string).trim()) errors.push(`${at}: ${key} is required`);
    }
    if (!specialtyIds.has(p.specialtyId as string))
      errors.push(`${at}: unknown specialtyId "${String(p.specialtyId)}"`);
    if (!locationIds.has(p.locationId as string)) errors.push(`${at}: unknown locationId "${String(p.locationId)}"`);
    if (!isStrList(p.languages) || p.languages.length === 0)
      errors.push(`${at}: languages must be a non-empty string array`);
    if (!Number.isInteger(p.yearsExperience) || (p.yearsExperience as number) < 0)
      errors.push(`${at}: yearsExperience must be an integer >= 0`);
    if (!Number.isInteger(p.feePkr) || (p.feePkr as number) <= 0)
      errors.push(`${at}: feePkr must be a positive integer`);

    const visits = p.visitTypes;
    if (
      !isStrList(visits) ||
      visits.length === 0 ||
      !visits.every((v) => (VISIT_TYPES as readonly string[]).includes(v))
    ) {
      errors.push(`${at}: visitTypes must be a non-empty subset of ${VISIT_TYPES.join(", ")}`);
    } else if (p.locationId === "online" && visits.includes("in_person")) {
      errors.push(`${at}: an online-only professional cannot offer in-person visits`);
    }

    if (!isObj(p.availability) || Object.keys(p.availability).length === 0) {
      errors.push(`${at}: availability needs at least one day`);
    } else {
      for (const [day, slots] of Object.entries(p.availability)) {
        if (!(DAYS as readonly string[]).includes(day)) errors.push(`${at}: unknown day "${day}"`);
        else if (!isStrList(slots) || slots.length === 0 || !slots.every((s) => TIME.test(s))) {
          errors.push(`${at}: ${day} slots must be a non-empty list of HH:MM times`);
        } else if (new Set(slots).size !== slots.length) errors.push(`${at}: ${day} has duplicate slots`);
      }
    }
  });
  if (proIds.size === 0) errors.push("professionals must not be empty");
  return errors;
}

function load(): Directory {
  const errors = validateDirectory(raw);
  if (errors.length) throw new Error(`data/professionals.json is invalid:\n- ${errors.join("\n- ")}`);
  return raw as Directory;
}

export const directory: Directory = load();
export const { specialties, locations, professionals } = directory;

const specialtyById = new Map(specialties.map((s) => [s.id, s]));
const locationById = new Map(locations.map((l) => [l.id, l]));
const professionalById = new Map(professionals.map((p) => [p.id, p]));

export const getProfessional = (id: string): Professional | undefined => professionalById.get(id);
export const specialtyName = (id: string) => specialtyById.get(id)?.name ?? id;
export const locationName = (id: string) => locationById.get(id)?.name ?? id;
export const availableDays = (p: Professional): Day[] => DAYS.filter((d) => (p.availability[d]?.length ?? 0) > 0);
export const languages: string[] = [...new Set(professionals.flatMap((p) => p.languages))].sort();

const pkr = new Intl.NumberFormat("en-PK", { style: "currency", currency: "PKR", maximumFractionDigits: 0 });
export const formatFee = (amount: number) => pkr.format(amount);
