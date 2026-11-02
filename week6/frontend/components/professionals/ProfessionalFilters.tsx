"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useOptimistic, useState, useTransition } from "react";
import { ChipFilter, SelectFilter } from "@/components/ui/Filter";
import {
  EMPTY_FILTERS,
  FEE_CAPS,
  SORTS,
  activeFilterCount,
  parseFilters,
  toSearchParams,
  type Filters,
} from "@/lib/filters";
import { DAYS, DAY_LABELS, VISIT_LABELS, VISIT_TYPES, formatFee, locations, specialties } from "@/lib/professionals";

const SEARCH_DEBOUNCE_MS = 300;

/**
 * Filter controls. They hold no filter state of their own: the URL is the state. Each change
 * builds the next query string and replaces the URL; the server page re-renders the results.
 * The only local state is the search box text, so typing isn't throttled by navigation.
 * useOptimistic shows the new value immediately while the URL update is in flight; without it a
 * checkbox stayed unticked until the server round-trip finished (caught by the browser test).
 */
export function ProfessionalFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const committed = parseFilters(Object.fromEntries(params));
  const [filters, setOptimistic] = useOptimistic(committed);
  const [pending, startTransition] = useTransition();
  const [query, setQuery] = useState(filters.q);

  const navigate = (next: Filters) => {
    const qs = toSearchParams(next).toString();
    startTransition(() => {
      setOptimistic(next);
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    });
  };
  const update = (patch: Partial<Filters>) => navigate({ ...filters, ...patch });

  // Keep the box in sync when the URL changes from elsewhere (Reset, back/forward).
  useEffect(() => setQuery(filters.q), [filters.q]);

  // Debounced search: write the URL once typing pauses.
  useEffect(() => {
    if (query.trim() === filters.q) return;
    const t = setTimeout(() => update({ q: query }), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only re-arm when the typed text changes
  }, [query]);

  const active = activeFilterCount(filters);

  return (
    <form
      className="filters card"
      role="search"
      aria-label="Filter professionals"
      onSubmit={(e) => {
        e.preventDefault();
        update({ q: query });
      }}
    >
      <div className="filter search">
        <label htmlFor="q">Search</label>
        <input
          id="q"
          type="search"
          value={query}
          placeholder="Name, specialty, language…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <ChipFilter
        label="Specialty"
        values={filters.specialties}
        options={specialties.map((s) => ({ value: s.id, label: s.name }))}
        onChange={(v) => update({ specialties: v })}
      />

      <div className="filter-row">
        <SelectFilter
          id="location"
          label="Location"
          anyLabel="Any location"
          value={filters.location}
          options={locations.map((l) => ({ value: l.id, label: l.name }))}
          onChange={(v) => update({ location: v })}
        />
        <SelectFilter
          id="visit"
          label="Visit type"
          anyLabel="Any visit type"
          value={filters.visit}
          options={VISIT_TYPES.map((v) => ({ value: v, label: VISIT_LABELS[v] }))}
          onChange={(v) => update({ visit: v as Filters["visit"] })}
        />
        <SelectFilter
          id="day"
          label="Available on"
          anyLabel="Any day"
          value={filters.day}
          options={DAYS.map((d) => ({ value: d, label: DAY_LABELS[d] }))}
          onChange={(v) => update({ day: v as Filters["day"] })}
        />
        <SelectFilter
          id="maxFee"
          label="Max fee"
          anyLabel="Any fee"
          value={filters.maxFee ? String(filters.maxFee) : ""}
          options={FEE_CAPS.map((f) => ({ value: String(f), label: `Up to ${formatFee(f)}` }))}
          onChange={(v) => update({ maxFee: v ? Number(v) : null })}
        />
        <div className="filter">
          <label htmlFor="sort">Sort by</label>
          <select id="sort" value={filters.sort} onChange={(e) => update({ sort: e.target.value as Filters["sort"] })}>
            {Object.entries(SORTS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="filter-actions">
        <button
          type="button"
          className="btn ghost small"
          disabled={active === 0 && filters.sort === "name"}
          onClick={() => {
            setQuery("");
            navigate(EMPTY_FILTERS);
          }}
        >
          Reset filters{active ? ` (${active})` : ""}
        </button>
        <span className="muted small" aria-hidden={!pending}>
          {pending ? "Updating…" : ""}
        </span>
      </div>
    </form>
  );
}
