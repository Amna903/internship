"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useFavorites } from "@/lib/favorites";

const LINKS = [
  { href: "/professionals", label: "Find professionals" },
  { href: "/saved", label: "Saved" },
  { href: "/profile", label: "My profile" },
] as const;

/**
 * Primary navigation. On small screens it collapses behind a disclosure button
 * (aria-expanded + aria-controls; Escape closes it and returns focus to the button).
 */
export function SiteNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const { ids, hydrated } = useFavorites();

  useEffect(() => setOpen(false), [pathname]); // close after navigating

  return (
    <nav className="site-nav" aria-label="Primary">
      <button
        ref={button}
        type="button"
        className="btn ghost small menu-toggle"
        aria-expanded={open}
        aria-controls="primary-menu"
        onClick={() => setOpen((o) => !o)}
      >
        Menu
      </button>
      <ul
        id="primary-menu"
        className={`menu ${open ? "open" : ""}`}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            setOpen(false);
            button.current?.focus();
          }
        }}
      >
        {LINKS.map((l) => {
          const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
          return (
            <li key={l.href}>
              <Link href={l.href} aria-current={active ? "page" : undefined}>
                {l.label}
                {l.href === "/saved" && hydrated && ids.length > 0 && (
                  <>
                    <span className="count" aria-hidden="true">{ids.length}</span>
                    <span className="visually-hidden"> ({ids.length} saved)</span>
                  </>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
