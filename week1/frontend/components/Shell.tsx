import Link from "next/link";

export function Shell({ nav, children }: { nav?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="shell">
      <header className="topbar">
        <Link href="/" className="brand">Health<span>Profile</span></Link>
        <nav className="nav" aria-label="Main">{nav}</nav>
      </header>
      <main>{children}</main>
    </div>
  );
}

export function FieldError({ errors, name }: { errors: Record<string, string>; name: string }) {
  return errors[name] ? <div className="field-error" role="alert">{errors[name]}</div> : null;
}

export const DISCLAIMER =
  "Demo only: all data is fictional. This app stores wellness preferences, not medical records, and gives no medical advice.";
