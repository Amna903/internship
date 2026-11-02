"use client";
import { useFavorites } from "@/lib/favorites";

/** Toggle button (aria-pressed). Disabled until hydrated so the first click can't hit stale state. */
export function FavoriteButton({ id, name }: { id: string; name: string }) {
  const { has, toggle, hydrated } = useFavorites();
  const saved = hydrated && has(id);
  return (
    <button
      type="button"
      className={`btn small ${saved ? "" : "ghost"} fav`}
      aria-pressed={saved}
      aria-label={saved ? `Remove ${name} from saved` : `Save ${name}`}
      disabled={!hydrated}
      onClick={() => toggle(id)}
    >
      <span aria-hidden="true">{saved ? "★" : "☆"}</span> {saved ? "Saved" : "Save"}
    </button>
  );
}
