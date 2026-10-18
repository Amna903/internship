import Link from "next/link";
import type { ReactNode } from "react";
import { SiteNav } from "@/components/ui/SiteNav";

export const DISCLAIMER =
  "Demo only: all people and data are fictional. This app stores wellness preferences, not medical records, and gives no medical advice.";

type LayoutProps = {
  children: ReactNode;
  /** Page-specific actions shown at the right of the header (e.g. "Sign out"). */
  actions?: ReactNode;
};

/** Page frame shared by every route: skip link, header with primary nav, main, footer. */
export function Layout({ children, actions }: LayoutProps) {
  return (
    <div className="shell">
      <a href="#main" className="skip-link">Skip to content</a>
      <header className="topbar">
        <Link href="/" className="brand">Health<span>Profile</span></Link>
        <SiteNav />
        {actions && <div className="actions">{actions}</div>}
      </header>
      <main id="main" tabIndex={-1}>{children}</main>
      <footer className="footer muted small">{DISCLAIMER}</footer>
    </div>
  );
}
