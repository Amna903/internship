"use client";
import Link from "next/link";
import { ProfessionalCard } from "@/components/professionals/ProfessionalCard";
import { Card } from "@/components/ui/Card";
import { useFavorites } from "@/lib/favorites";
import { getProfessional, type Professional } from "@/lib/professionals";

export function SavedList() {
  const { ids, clear, hydrated } = useFavorites();
  if (!hydrated)
    return (
      <p className="muted" role="status">
        Loading saved professionals…
      </p>
    );

  // Ids of profiles that were removed from the data file are skipped, not shown as broken cards.
  const saved = ids.map(getProfessional).filter((p): p is Professional => Boolean(p));
  if (saved.length === 0) {
    return (
      <Card className="empty" title="Nothing saved yet">
        <p className="muted">Use the ☆ Save button on any professional to keep them here.</p>
        <Link className="btn" href="/professionals">
          Find professionals
        </Link>
      </Card>
    );
  }
  return (
    <>
      <p className="result-count" role="status">
        {saved.length} saved ·{" "}
        <button type="button" className="linklike" onClick={clear}>
          Clear all
        </button>
      </p>
      <ul className="pro-grid" aria-label="Saved professionals">
        {saved.map((p) => (
          <li key={p.id}>
            <ProfessionalCard professional={p} />
          </li>
        ))}
      </ul>
    </>
  );
}
