# Week 2: architecture decisions

## Route map

| Route | Rendering | Why |
|---|---|---|
| `/professionals` | Server component, dynamic (reads `searchParams`) | Filtering happens on the server from the URL, so refresh / shared links / back-forward render the right results with no flash. |
| `/professionals/[id]` | Server component, statically generated (`generateStaticParams`) | Pure data from JSON; 16 HTML pages built ahead of time. Unknown ids call `notFound()` → 404. |
| `/professionals/[id]/request` | Server shell (resolves professional, 404s) + client form | The form needs browser state; the lookup and 404 do not. |
| `/saved` | Server shell + client list | Favourites live in `localStorage`, which only exists in the browser. |

## Client / server component boundary

```
Layout (server)
├─ SiteNav ("use client")          active link, mobile menu, saved count
└─ page (server)
   ├─ ProfessionalFilters ("use client")   reads/writes the URL
   ├─ ProfessionalCard (server)
   │  └─ FavoriteButton ("use client")     small interactive island
   ├─ AppointmentRequestForm ("use client")
   └─ SavedList ("use client")
```

Rule I followed: **a component is a client component only if it needs browser APIs, event handlers or
hooks.** Cards, badges, detail pages and the data itself stay on the server, so the JSON isn't shipped to
the browser for the list page, and the interactive parts are small islands.

## State management: no global store

There are three kinds of state, and each one has a natural home. None of them needs Redux or Zustand.

| State | Home | Reason |
|---|---|---|
| Filters, search, sort | **URL query string** | It must survive refresh, be shareable and work with back/forward. The URL already does all of that, so a store would just be a second copy to keep in sync. `parseFilters` / `toSearchParams` are the only two functions that touch it, and they round-trip (unit-tested). |
| Favourites, form draft | **`localStorage`** via a small `useSyncExternalStore` hook (`lib/localStore.ts`) | Must survive refresh. `useSyncExternalStore` gives hydration-safe reads (server and first client render use the fallback), keeps every component on the same key in sync (nav count + buttons), syncs across tabs through the `storage` event, and validates stored JSON so a corrupt value falls back instead of crashing. |
| Transient UI (menu open, current errors, search box text while typing) | **`useState`** in the component | Nothing else needs it. |

Optimistic UI: filter controls render through `useOptimistic`, so a ticked checkbox shows immediately
while `router.replace` is still in flight (see the bug write-up in `ai-workflow.md`).

## Data: one typed source, validated

`data/professionals.json` holds specialties, locations and professionals, and references between them are
by id. `lib/professionals.ts` validates it once at import time: unique slug ids, known
`specialtyId`/`locationId`, positive integer fees, valid visit types, `HH:MM` slots on real days, and a
business rule (an online-only professional can't offer in-person visits). It then exports typed lookups.
Because every directory page imports it during `next build`, **invalid data fails the build** instead of
rendering a broken card. Labels for days, visit types, sorts, reasons and fee caps are config objects, not
strings repeated in JSX.

## Forms and accessibility

- `FormField` wires `label`/`legend`, hint and error ids into `aria-describedby`, and sets `aria-invalid` on error.
- On a failed **Next**, an error summary (`role="alert"`) appears and takes focus. Each entry links to its field.
- On a step change, focus moves to the step heading. `Stepper` marks the current step with `aria-current="step"` and announces "Step n of 4".
- Validation rules live in `lib/appointment.ts` (pure, unit-tested). The component only renders them.
- A restored draft that points past an invalid step is rewound (`firstInvalidStep`).
- Navigation: skip link, `aria-current="page"`, and a mobile disclosure menu (`aria-expanded`, `aria-controls`, Escape closes and returns focus).

## Design tokens

`app/globals.css` defines colour, spacing (`--space-1…6`), type (`--text-*`), radius, shadow and focus
tokens, with a dark-mode override. Week 1 styles and Week 2 components both consume them.

## Blast radius

Existing files changed: `app/page.tsx` (one card linking to the directory), `app/globals.css` (tokens and
new classes appended; existing rules kept), and `components/Shell.tsx`, which became a thin adapter over the new
`Layout` so every Week 1 page picked up the new navigation without being edited. The backend is untouched
(`git diff --stat -- week2/backend` is empty). Everything else is new files.
