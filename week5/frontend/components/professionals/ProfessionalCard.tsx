import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { FavoriteButton } from "@/components/professionals/FavoriteButton";
import {
  DAY_LABELS, VISIT_LABELS, availableDays, formatFee, locationName, specialtyName, type Professional,
} from "@/lib/professionals";

export function ProfessionalCard({ professional: p }: { professional: Professional }) {
  const days = availableDays(p);
  return (
    <Card
      as="article"
      className="pro-card"
      title={<Link href={`/professionals/${p.id}`}>{p.name}</Link>}
      headingLevel={3}
      footer={
        <>
          <span className="fee">{formatFee(p.feePkr)} <span className="muted small">/ session</span></span>
          <FavoriteButton id={p.id} name={p.name} />
        </>
      }
    >
      <p className="muted small pro-title">{p.title} · {locationName(p.locationId)}</p>
      <div className="badges">
        <Badge>{specialtyName(p.specialtyId)}</Badge>
        {p.visitTypes.map((v) => <Badge key={v} tone="neutral">{VISIT_LABELS[v]}</Badge>)}
      </div>
      <p className="small">{p.bio}</p>
      <p className="muted small">
        {p.yearsExperience} yrs experience · Available {days.map((d) => DAY_LABELS[d].slice(0, 3)).join(", ")}
      </p>
    </Card>
  );
}
