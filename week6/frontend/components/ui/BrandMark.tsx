import { useId } from "react";

/** Logo: a rounded tile with a heartbeat line. Decorative; the wordmark next to it carries the name. */
export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  const id = useId();
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0f766e" />
          <stop offset=".6" stopColor="#14b8a6" />
          <stop offset="1" stopColor="#5eead4" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${id})`} />
      <path
        d="M6 17h4.5l2.5-5.5 4 11 3-8 1.8 2.5H26"
        fill="none"
        stroke="#fff"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
