"use client";
/**
 * Tiny typed wrapper around localStorage for client-only state (favourites, form drafts).
 *
 * Built on useSyncExternalStore so that:
 *  - the server render and first client render both use the fallback (no hydration mismatch),
 *  - every component reading the same key stays in sync, including across browser tabs,
 *  - a corrupt or hand-edited value falls back safely instead of crashing the page.
 */
import { useCallback, useSyncExternalStore } from "react";

export type Store<T> = {
  fallback: T;
  get: () => T;
  set: (next: T | ((prev: T) => T)) => void;
  clear: () => void;
  subscribe: (cb: () => void) => () => void;
};

const stores = new Map<string, Store<unknown>>();

export function localStore<T>(key: string, fallback: T, isValid: (v: unknown) => v is T): Store<T> {
  const existing = stores.get(key);
  if (existing) return existing as Store<T>;

  const listeners = new Set<() => void>();
  let cachedRaw: string | null | undefined;
  let cachedValue: T = fallback;

  const read = (): T => {
    let rawValue: string | null = null;
    try {
      rawValue = window.localStorage.getItem(key);
    } catch {
      return fallback; // storage blocked (private mode, disabled cookies)
    }
    if (rawValue !== cachedRaw) {
      cachedRaw = rawValue;
      try {
        const parsed: unknown = rawValue === null ? fallback : JSON.parse(rawValue);
        cachedValue = isValid(parsed) ? parsed : fallback;
      } catch {
        cachedValue = fallback;
      }
    }
    return cachedValue;
  };
  const emit = () => listeners.forEach((l) => l());
  const write = (rawValue: string | null) => {
    try {
      if (rawValue === null) window.localStorage.removeItem(key);
      else window.localStorage.setItem(key, rawValue);
    } catch {
      /* quota exceeded or storage blocked: the change is simply not persisted */
    }
    emit();
  };

  const store: Store<T> = {
    fallback,
    get: read,
    set: (next) => {
      const value = typeof next === "function" ? (next as (prev: T) => T)(read()) : next;
      write(JSON.stringify(value));
    },
    clear: () => write(null),
    subscribe: (cb) => {
      listeners.add(cb);
      const onStorage = (e: StorageEvent) => e.key === key && cb();
      window.addEventListener("storage", onStorage);
      return () => {
        listeners.delete(cb);
        window.removeEventListener("storage", onStorage);
      };
    },
  };
  stores.set(key, store as Store<unknown>);
  return store;
}

/** Returns [value, setValue, hydrated]. `hydrated` is false during SSR and the first client render. */
export function useLocalStore<T>(store: Store<T>): [T, Store<T>["set"], boolean] {
  const value = useSyncExternalStore(store.subscribe, store.get, () => store.fallback);
  const hydrated = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const set = useCallback<Store<T>["set"]>((next) => store.set(next), [store]);
  return [value, set, hydrated];
}

const noopSubscribe = () => () => {};
