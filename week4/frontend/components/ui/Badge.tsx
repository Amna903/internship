import type { ReactNode } from "react";

export type BadgeTone = "brand" | "neutral" | "warn" | "danger";

export function Badge({ children, tone = "brand" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}
