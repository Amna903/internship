import type { ReactNode } from "react";

/** Title block used at the top of app pages: optional eyebrow, the page's h1, a lead line and actions. */
export function PageHeader({ eyebrow, title, lead, leading, actions }: {
  eyebrow?: ReactNode; title: ReactNode; lead?: ReactNode; leading?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <div className="page-title">
          {leading}
          <div>
            <h1>{title}</h1>
            {lead && <p className="muted">{lead}</p>}
          </div>
        </div>
      </div>
      {actions && <div className="actions">{actions}</div>}
    </div>
  );
}
