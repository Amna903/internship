import type { ReactNode } from "react";

type CardProps = {
  children: ReactNode;
  /** Rendered as a heading at `headingLevel` (default h2). */
  title?: ReactNode;
  headingLevel?: 2 | 3;
  /** `article` for self-contained items in a list, `section` for page regions. */
  as?: "div" | "article" | "section";
  className?: string;
  footer?: ReactNode;
};

export function Card({ children, title, headingLevel = 2, as: Tag = "div", className = "", footer }: CardProps) {
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <Tag className={`card ${className}`.trim()}>
      {title && <Heading className="card-title">{title}</Heading>}
      {children}
      {footer && <div className="card-footer">{footer}</div>}
    </Tag>
  );
}
