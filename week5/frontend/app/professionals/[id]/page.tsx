import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FavoriteButton } from "@/components/professionals/FavoriteButton";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { Layout } from "@/components/ui/Layout";
import {
  DAY_LABELS, VISIT_LABELS, availableDays, formatFee, getProfessional, locationName, professionals, specialtyName,
} from "@/lib/professionals";

type Props = { params: Promise<{ id: string }> };

// Pre-render every known profile at build time; unknown ids still reach the page and 404 below.
export const generateStaticParams = () => professionals.map((p) => ({ id: p.id }));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const p = getProfessional((await params).id);
  return { title: p ? `${p.name}, ${p.title} · HealthProfile` : "Professional not found · HealthProfile" };
}

export default async function ProfessionalPage({ params }: Props) {
  const p = getProfessional((await params).id);
  if (!p) notFound();

  return (
    <Layout>
      <p className="small"><Link href="/professionals">← All professionals</Link></p>
      <div className="detail-head">
        <div>
          <h1>{p.name}</h1>
          <p className="muted">{p.title} · {p.clinic}, {locationName(p.locationId)}</p>
          <div className="badges">
            <Badge>{specialtyName(p.specialtyId)}</Badge>
            {p.visitTypes.map((v) => <Badge key={v} tone="neutral">{VISIT_LABELS[v]}</Badge>)}
          </div>
        </div>
        <div className="detail-cta">
          <Link className="btn" href={`/professionals/${p.id}/request`}>Request an appointment</Link>
          <FavoriteButton id={p.id} name={p.name} />
        </div>
      </div>

      <div className="grid">
        <Card title="About" as="section">
          <p>{p.bio}</p>
          <dl className="kv">
            <dt>Fee</dt><dd>{formatFee(p.feePkr)} per session</dd>
            <dt>Experience</dt><dd>{p.yearsExperience} years</dd>
            <dt>Languages</dt><dd>{p.languages.join(", ")}</dd>
          </dl>
        </Card>
        <Card title="Weekly availability" as="section">
          <table className="availability">
            <caption className="visually-hidden">Available time slots by day</caption>
            <thead><tr><th scope="col">Day</th><th scope="col">Times</th></tr></thead>
            <tbody>
              {availableDays(p).map((d) => (
                <tr key={d}><th scope="row">{DAY_LABELS[d]}</th><td>{p.availability[d]!.join(", ")}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </Layout>
  );
}
