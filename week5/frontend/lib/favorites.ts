"use client";
import { useCallback } from "react";
import { localStore, useLocalStore } from "@/lib/localStore";

const isIdList = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === "string");
const EMPTY: string[] = [];
const favoritesStore = () => localStore<string[]>("hp.favorites.v1", EMPTY, isIdList);

export function useFavorites() {
  const [ids, setIds, hydrated] = useLocalStore(favoritesStore());
  const toggle = useCallback(
    (id: string) => setIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id])),
    [setIds],
  );
  const clear = useCallback(() => setIds([]), [setIds]);
  return { ids, has: (id: string) => ids.includes(id), toggle, clear, hydrated };
}
