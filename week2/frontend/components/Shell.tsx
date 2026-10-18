import type { ReactNode } from "react";
import { DISCLAIMER, Layout } from "@/components/ui/Layout";

/**
 * Week 1 pages import Shell/FieldError/DISCLAIMER from here. Kept as a thin adapter over the
 * Week 2 Layout so those pages pick up the new navigation without being edited.
 */
export function Shell({ nav, children }: { nav?: ReactNode; children: ReactNode }) {
  return <Layout actions={nav}>{children}</Layout>;
}

export function FieldError({ errors, name }: { errors: Record<string, string>; name: string }) {
  return errors[name] ? <div className="field-error" role="alert">{errors[name]}</div> : null;
}

export { DISCLAIMER };
