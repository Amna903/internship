import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { AppointmentRequestForm } from "@/components/professionals/AppointmentRequestForm";
import { Layout } from "@/components/ui/Layout";
import { getProfessional, professionals } from "@/lib/professionals";

type Props = { params: Promise<{ id: string }> };

export const generateStaticParams = () => professionals.map((p) => ({ id: p.id }));

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const p = getProfessional((await params).id);
  return { title: p ? `Request with ${p.name} · HealthProfile` : "Professional not found · HealthProfile" };
}

/** Server shell resolves the professional (404 if unknown); the form itself is a client component. */
export default async function RequestPage({ params }: Props) {
  const p = getProfessional((await params).id);
  if (!p) notFound();
  return (
    <Layout>
      <p className="small"><Link href={`/professionals/${p.id}`}>← Back to {p.name}</Link></p>
      <h1>Request an appointment</h1>
      <p className="muted">With {p.name}, {p.title}. This is a request form only: no appointment is booked.</p>
      <AppointmentRequestForm professional={p} />
    </Layout>
  );
}
